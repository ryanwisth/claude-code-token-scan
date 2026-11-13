"""Pass 4: usage by session kind (user, side session, continued chat, subagent), start_session initiation, Agent spawns by model, output mix.

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
_A = _ap.parse_args()
ROOT = os.path.expanduser(_A.root).rstrip('/'); START = _A.start; END = _A.end
# ---------------------------------------------------------------------------------------------
starter=collections.defaultdict(lambda: collections.Counter()); init=collections.Counter(); init_ctx=collections.Counter()
ctxshare=collections.Counter(); out_comp=collections.Counter(); agent_spawn=collections.Counter(); sub_models=collections.Counter()
reads_of_transcripts=0; handoff_reads=0; effort_tags=collections.Counter()
for path in glob.glob(ROOT+'/**/*.jsonl', recursive=True):
    if datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime('%Y-%m-%d')<START: continue
    sid=os.path.basename(path)[:-6]; seen=set(); kind=None; is_sub='/subagents/' in path
    with open(path,errors='ignore') as f:
        for line in f:
            try: d=json.loads(line)
            except: continue
            ts=d.get('timestamp','')[:10]
            if not (START<=ts<END): continue
            t=d.get('type'); m=d.get('message') or {}
            if t=='user' and kind is None:
                c=m.get('content'); txt=c if isinstance(c,str) else ' '.join(x.get('text','') for x in c if isinstance(x,dict) and x.get('type')=='text') if isinstance(c,list) else ''
                if txt:
                    if is_sub: kind='subagent'
                    elif 'Background (from the session that started this one)' in txt or 'from the session that started this one' in txt: kind='side_session'
                    elif txt.lstrip().startswith('Continue the'): kind='continue_chat'
                    else: kind='user'
            if t=='assistant':
                mid=m.get('id'); u=m.get('usage') or {}
                for c in m.get('content') or []:
                    if not isinstance(c,dict): continue
                    if c.get('type')=='tool_use':
                        inp=c.get('input') or {}; 
                        if c['name']=='mcp__ccd_session__start_session': init[inp.get('initiation','?')]+=1; init_ctx[inp.get('context','?')]+=1
                        if c['name']=='Agent': agent_spawn[(inp.get('subagent_type','?'),inp.get('model','NONE'))]+=1
                        if c['name']=='Read' and ('.jsonl' in str(inp.get('file_path','')) or '/projects/-Users' in str(inp.get('file_path',''))): reads_of_transcripts+=1
                        if c['name']=='Bash' and '.jsonl' in str(inp.get('command','')) and '.claude/projects' in str(inp.get('command','')): reads_of_transcripts+=1
                        if c['name'] in('Read','Bash') and 'HANDOFF' in json.dumps(inp): handoff_reads+=1
                        out_comp['tool_input_chars']+=len(json.dumps(inp))
                    elif c.get('type')=='text': out_comp['text_chars']+=len(c.get('text',''))
                    elif c.get('type')=='thinking': out_comp['thinking_chars']+=len(c.get('thinking',''))
                if not u or mid in seen: continue
                seen.add(mid)
                ctx=u.get('input_tokens',0)+u.get('cache_creation_input_tokens',0)+u.get('cache_read_input_tokens',0)
                w=u.get('input_tokens',0)+1.25*u.get('cache_creation_input_tokens',0)+0.1*u.get('cache_read_input_tokens',0)+5*u.get('output_tokens',0)
                k=kind or 'user'
                starter[k]['calls']+=1; starter[k]['w']+=w; starter[k]['out']+=u.get('output_tokens',0); starter[k]['cw']+=u.get('cache_creation_input_tokens',0); starter[k]['cr']+=u.get('cache_read_input_tokens',0); starter[k]['think']+=(u.get('output_tokens_details') or {}).get('thinking_tokens',0)
                b='>240k' if ctx>240000 else '200-240k' if ctx>200000 else '<200k'
                ctxshare[(k,b)]+=u.get('cache_read_input_tokens',0)
                if is_sub: sub_models[m.get('model')]+=1
    if kind: starter[kind]['sessions']+=1
print('## by session kind'); 
for k,v in starter.items(): print(f"{k:14s} sessions={v['sessions']:4d} calls={v['calls']:6d} calls/sess={v['calls']/max(v['sessions'],1):5.0f} W={v['w']/1e6:6.1f}M out={v['out']/1e6:5.2f}M think={v['think']/1e6:5.2f}M cw={v['cw']/1e6:5.1f}M cr={v['cr']/1e6:7.1f}M")
print('\n## cache-read share by kind x context bucket (M)'); [print(k,round(v/1e6,1)) for k,v in sorted(ctxshare.items())]
print('\n## start_session initiation',init,'context',init_ctx)
print('## Agent spawns (type,model)',agent_spawn.most_common(12)); print('## subagent models',sub_models)
print('## transcript re-reads',reads_of_transcripts,' HANDOFF reads',handoff_reads)
print('## output composition chars',dict(out_comp))
