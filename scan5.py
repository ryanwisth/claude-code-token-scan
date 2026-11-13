"""Pass 5: how many bytes went to re-reading HANDOFF / START-HERE / TRAPS notes and old transcripts.

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
hb=collections.Counter(); hn=collections.Counter(); tb=0; tn=0; bashcmd_handoff=0; bashcmd_handoff_bytes=0
for path in glob.glob(ROOT+'/**/*.jsonl', recursive=True):
    if datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime('%Y-%m-%d')<START: continue
    tu={}
    with open(path,errors='ignore') as f:
        for line in f:
            try: d=json.loads(line)
            except: continue
            ts=d.get('timestamp','')[:10]
            if not (START<=ts<END): continue
            m=d.get('message') or {}
            if d.get('type')=='assistant':
                for c in m.get('content') or []:
                    if isinstance(c,dict) and c.get('type')=='tool_use': tu[c['id']]=(c['name'],c.get('input') or {})
            elif d.get('type')=='user' and isinstance(m.get('content'),list):
                for x in m['content']:
                    if isinstance(x,dict) and x.get('type')=='tool_result':
                        name,inp=tu.get(x.get('tool_use_id'),('?',{})); cont=x.get('content'); s=len(json.dumps(cont)) if cont else 0
                        p=str(inp.get('file_path','')) if name=='Read' else str(inp.get('command','')) if name=='Bash' else ''
                        if 'HANDOFF' in p or 'START-HERE' in p or 'TRAPS' in p:
                            key=('HANDOFF' if 'HANDOFF' in p else 'TRAPS' if 'TRAPS' in p else 'START-HERE', name); hb[key]+=s; hn[key]+=1
                        if '.claude/projects' in p or '.jsonl' in p: tb+=s; tn+=1
print('## HANDOFF/TRAPS/START-HERE reads: bytes by (file,tool)'); [print(k, round(v/1e6,2),'MB n=',hn[k], 'avg', round(v/hn[k]/1e3,1),'k') for k,v in hb.most_common()]
print('## old-transcript reads: n',tn,'bytes',round(tb/1e6,1),'MB')
