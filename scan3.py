"""Pass 3: cache-write tokens by cause, image exposure, Read/Bash output volume, side-session share and session-size buckets.

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
FLOOR_TOKENS = int(os.environ.get('SCAN_FLOOR_TOKENS', '83000'))  # assumed fixed context per call (system prompt + tools)
# ---------------------------------------------------------------------------------------------
cw_cause=collections.Counter(); cw_n=collections.Counter()
img_exposure=0; img_tokens_est=0; img_by_src=collections.Counter()
sess_kind=collections.defaultdict(lambda: collections.Counter())
read_text_bytes=0; read_img_n=0; read_paths=collections.Counter(); read_big=[]
bash_out=0; bash_n=0
idle_gaps=[]
per_sess=[]
for path in glob.glob(ROOT+'/**/*.jsonl', recursive=True):
    if datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime('%Y-%m-%d')<START: continue
    sid=os.path.basename(path)[:-6]
    seen=set(); last_ts=None; just_compacted=False; first=True; n=0; imgs_in_ctx=0; w=0; started_by=None
    tu={}
    with open(path,errors='ignore') as f:
        for line in f:
            try: d=json.loads(line)
            except: continue
            ts=d.get('timestamp','')[:10]
            if not (START<=ts<END): continue
            t=d.get('type'); m=d.get('message') or {}
            if d.get('isCompactSummary') or t=='summary': just_compacted=True; imgs_in_ctx=0
            if t=='assistant':
                mid=m.get('id'); u=m.get('usage') or {}
                for c in m.get('content') or []:
                    if isinstance(c,dict) and c.get('type')=='tool_use': tu[c['id']]=c['name']
                if not u or mid in seen: continue
                seen.add(mid); n+=1
                cw=u.get('cache_creation_input_tokens',0)
                w+=u.get('input_tokens',0)+1.25*cw+0.1*u.get('cache_read_input_tokens',0)+5*u.get('output_tokens',0)
                tnow=datetime.datetime.fromisoformat(d['timestamp'].replace('Z','+00:00'))
                gap=(tnow-last_ts).total_seconds()/60 if last_ts else 0
                if first: cause='session_start'; first=False
                elif just_compacted: cause='after_compaction'
                elif gap>60: cause='idle_gap>60min'
                elif cw>20000: cause='big_other'
                else: cause='normal_turn'
                just_compacted=False
                cw_cause[cause]+=cw; cw_n[cause]+=1
                if cause=='idle_gap>60min': idle_gaps.append((round(gap),cw))
                last_ts=tnow
                img_exposure+=imgs_in_ctx
            elif t=='user':
                c=m.get('content')
                if started_by is None:
                    txt=c if isinstance(c,str) else ' '.join(x.get('text','') for x in c if isinstance(x,dict) and x.get('type')=='text') if isinstance(c,list) else ''
                    if txt: started_by='side_session' if ('Background (from the session that started this one)' in txt or 'Linked sessions now' in txt[:200] or txt.startswith('Continue the')) else 'user'
                if isinstance(c,list):
                    for x in c:
                        if isinstance(x,dict) and x.get('type')=='tool_result':
                            name=tu.get(x.get('tool_use_id'),'?'); cont=x.get('content')
                            if isinstance(cont,list):
                                for y in cont:
                                    if isinstance(y,dict) and y.get('type')=='image':
                                        imgs_in_ctx+=1; img_by_src[name]+=1
                                        b=len((y.get('source') or {}).get('data',''))
                                        img_tokens_est+=min(1600,int(b*0.75/750*0.3)) # rough
                                    elif isinstance(y,dict) and y.get('type')=='text' and name=='Read':
                                        read_text_bytes+=len(y.get('text',''))
                            elif isinstance(cont,str):
                                if name=='Read': read_text_bytes+=len(cont)
                                if name=='Bash': bash_out+=len(cont); bash_n+=1
                            if name=='Read' and isinstance(cont,list) and any(isinstance(y,dict) and y.get('type')=='image' for y in cont): read_img_n+=1
                    tr=d.get('toolUseResult')
                    if isinstance(tr,dict) and tr.get('type')=='image': pass
                    if isinstance(tr,dict) and 'file' in tr and isinstance(tr['file'],dict):
                        fp=tr['file'].get('filePath','')
                        ext=os.path.splitext(fp)[1].lower(); read_paths[ext]+=1
                        if tr['file'].get('numLines',0)>1500: read_big.append((tr['file'].get('numLines'),fp))
    if n: per_sess.append((sid,started_by or 'user',n,w))
print('## cache-write tokens by cause (M), events')
for k,v in cw_cause.most_common(): print(f'{k:20s}{v/1e6:7.1f}M events={cw_n[k]:6d} avg={v/max(cw_n[k],1)/1e3:6.1f}k')
print('\n## idle gaps >60min: n',len(idle_gaps),'total cw',round(sum(c for g,c in idle_gaps)/1e6,1),'M; top', sorted(idle_gaps,key=lambda x:-x[1])[:8])
print('\n## images: exposure (image x later calls in same context)',img_exposure,' est tokens per image ~1.2k -> re-read tokens',round(img_exposure*1.2/1e3,1),'M ; images by source',img_by_src.most_common(8))
print('## Read: text bytes',round(read_text_bytes/1e6,1),'MB; image reads',read_img_n,'; by ext',read_paths.most_common(12))
print('## Read >1500 lines:',len(read_big), sorted(read_big,reverse=True)[:12])
print('## Bash outputs: n',bash_n,'bytes',round(bash_out/1e6,1),'MB')
print('\n## sessions by starter')
for kind in ('user','side_session'):
    rows=[r for r in per_sess if r[1]==kind]
    print(kind, 'sessions',len(rows),'calls',sum(r[2] for r in rows),'weight',round(sum(r[3] for r in rows)/1e6,1),'M')
print('\n## session size buckets (calls): sessions, weight share')
tot=sum(r[3] for r in per_sess)
for lo,hi in ((0,20),(20,100),(100,300),(300,9999)):
    rows=[r for r in per_sess if lo<=r[2]<hi]; print(f'{lo}-{hi}: n={len(rows)} weight={100*sum(r[3] for r in rows)/tot:.1f}% floor-only-weight({FLOOR_TOKENS//1000}k x0.1 x calls)={sum(r[2] for r in rows)*FLOOR_TOKENS*0.1/1e6:.0f}M')
print('\n## total weight',round(tot/1e6),'M; floor share =',round(100*sum(r[2] for r in per_sess)*FLOOR_TOKENS*0.1/tot,1),'%')
