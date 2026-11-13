"""Pass 2: tool-result bytes and images by tool, compactions, calls per user turn, and the heaviest sessions (needs scan.py output).

Weight W = input + 1.25*cache_write + 0.1*cache_read + 5*output (API-style price ratios)."""
import json, os, glob, collections, datetime
# --- configuration: CLI flags, else env vars, else defaults (last 7 days of ~/.claude/projects) ---
import argparse
_ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
_ap.add_argument('--root', default=os.environ.get('CLAUDE_PROJECTS_DIR', '~/.claude/projects'),
                 help='Claude Code transcript directory (env CLAUDE_PROJECTS_DIR, default ~/.claude/projects)')
_ap.add_argument('--start', default=os.environ.get('SCAN_START') or (datetime.date.today() - datetime.timedelta(days=7)).isoformat(),
                 help='first day, YYYY-MM-DD, inclusive (env SCAN_START, default 7 days ago)')
_ap.add_argument('--end', default=os.environ.get('SCAN_END') or (datetime.date.today() + datetime.timedelta(days=1)).isoformat(),
                 help='end day, YYYY-MM-DD, exclusive (env SCAN_END, default tomorrow)')
_ap.add_argument('usage_json', nargs='?', default=os.environ.get('SCAN_USAGE_JSON', 'usage.json'),
                 help='JSON written by scan.py (env SCAN_USAGE_JSON, default usage.json)')
_A = _ap.parse_args()
ROOT = os.path.expanduser(_A.root).rstrip('/'); START = _A.start; END = _A.end
HOME_PREFIX = os.path.expanduser('~').replace('/', '-') + '-'  # transcript folders are named after the encoded cwd
# ---------------------------------------------------------------------------------------------
res_by_tool=collections.Counter(); n_by_tool=collections.Counter(); img_by_tool=collections.Counter()
sess=collections.defaultdict(lambda: collections.Counter()); first_prompt={}; compact=collections.Counter(); titles={}
calls_per_turn=[]
for path in glob.glob(ROOT+'/**/*.jsonl', recursive=True):
    if datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime('%Y-%m-%d')<START: continue
    sid=os.path.basename(path)[:-6]; proj=path[len(ROOT)+1:].split('/')[0]
    tu={}  # tool_use id -> name
    run=0; seen=set()
    with open(path,errors='ignore') as f:
        for line in f:
            try: d=json.loads(line)
            except: continue
            ts=d.get('timestamp','')[:10]
            if not (START<=ts<END): continue
            t=d.get('type'); m=d.get('message') or {}
            if t=='summary' or d.get('isCompactSummary') or (t=='system' and 'compact' in str(d.get('subtype',''))): compact[sid]+=1
            if t=='assistant':
                mid=m.get('id')
                if mid in seen: 
                    for c in m.get('content') or []:
                        if isinstance(c,dict) and c.get('type')=='tool_use': tu[c['id']]=c['name']
                    continue
                seen.add(mid); run+=1; sess[sid]['calls']+=1
                for c in m.get('content') or []:
                    if isinstance(c,dict) and c.get('type')=='tool_use': tu[c['id']]=c['name']
                    if isinstance(c,dict) and c.get('type')=='text': sess[sid]['text_chars']+=len(c.get('text',''))
            elif t=='user':
                c=m.get('content')
                if isinstance(c,str):
                    sess[sid]['user_msgs']+=1; first_prompt.setdefault(sid,(proj,ts,c[:110].replace('\n',' ')))
                    if run: calls_per_turn.append(run); run=0
                elif isinstance(c,list):
                    txt=[x for x in c if isinstance(x,dict) and x.get('type')=='text']
                    if txt and not any(isinstance(x,dict) and x.get('type')=='tool_result' for x in c):
                        sess[sid]['user_msgs']+=1; first_prompt.setdefault(sid,(proj,ts,txt[0].get('text','')[:110].replace('\n',' ')))
                        if run: calls_per_turn.append(run); run=0
                    for x in c:
                        if isinstance(x,dict) and x.get('type')=='tool_result':
                            name=tu.get(x.get('tool_use_id'),'?'); cont=x.get('content')
                            s=len(json.dumps(cont)) if cont else 0
                            imgs=sum(1 for y in cont if isinstance(y,dict) and y.get('type')=='image') if isinstance(cont,list) else 0
                            res_by_tool[name]+=s; n_by_tool[name]+=1; img_by_tool[name]+=imgs
                            sess[sid]['res_bytes']+=s; sess[sid]['imgs']+=imgs
print('## tool result bytes (MB) by tool, n, images')
for k,v in res_by_tool.most_common(25): print(f'{k:45s}{v/1e6:8.1f}MB n={n_by_tool[k]:5d} avg={v/max(n_by_tool[k],1)/1e3:6.1f}k imgs={img_by_tool[k]}')
print('\n## total images', sum(img_by_tool.values()))
print('\n## compactions', sum(compact.values()), 'sessions with compaction', len(compact))
import statistics
print('\n## calls per user turn: n',len(calls_per_turn),'median',statistics.median(calls_per_turn),'mean',round(statistics.mean(calls_per_turn),1),'p90',sorted(calls_per_turn)[int(len(calls_per_turn)*.9)], 'max',max(calls_per_turn))
u=json.load(open(_A.usage_json))
bs=u['by_sess']; meta=u['sess_meta']
print('\n## sessions total', len(bs))
print('\n## top 30 sessions by weight')
rows=sorted(bs.items(), key=lambda kv:-kv[1].get('w',0))[:30]
tot=sum(v.get('w',0) for v in bs.values())
for sid,v in rows:
    fp=first_prompt.get(sid,('?','?','?')); models=[k[6:] for k in v if k.startswith('model_')]
    print(f"{v['w']/1e6:7.1f}M {100*v['w']/tot:4.1f}% calls={v['calls']:5d} ctx={v['ctxsum']/v['calls']/1e3:4.0f}k out={v['out']/1e3:6.0f}k umsg={sess[sid]['user_msgs']:3d} imgs={sess[sid]['imgs']:3d} cmp={compact[sid]} {','.join(models)} {fp[1]} {fp[0].removeprefix(HOME_PREFIX)[:22]} | {fp[2][:80]}")
print('\n## share of weight in sessions > 20M:', round(100*sum(v['w'] for v in bs.values() if v['w']>20e6)/tot,1))
