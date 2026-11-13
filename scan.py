"""Pass 1: token totals by project, model, day and lane (main vs subagent), context-size buckets and tool-call counts. Writes a JSON summary that scan2.py reads.

Weight W = input + 1.25*cache_write + 0.1*cache_read + 5*output (API-style price ratios)."""
import json, os, sys, glob, collections, datetime
# --- configuration: CLI flags, else env vars, else defaults (last 7 days of ~/.claude/projects) ---
import argparse
_ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
_ap.add_argument('--root', default=os.environ.get('CLAUDE_PROJECTS_DIR', '~/.claude/projects'),
                 help='Claude Code transcript directory (env CLAUDE_PROJECTS_DIR, default ~/.claude/projects)')
_ap.add_argument('--start', default=os.environ.get('SCAN_START') or (datetime.date.today() - datetime.timedelta(days=7)).isoformat(),
                 help='first day, YYYY-MM-DD, inclusive (env SCAN_START, default 7 days ago)')
_ap.add_argument('--end', default=os.environ.get('SCAN_END') or (datetime.date.today() + datetime.timedelta(days=1)).isoformat(),
                 help='end day, YYYY-MM-DD, exclusive (env SCAN_END, default tomorrow)')
_ap.add_argument('out', help='path of the JSON summary to write (read later by scan2.py)')
_A = _ap.parse_args()
ROOT = os.path.expanduser(_A.root).rstrip('/'); START = _A.start; END = _A.end
# ---------------------------------------------------------------------------------------------
def wt(u): return u.get('input_tokens',0)+1.25*u.get('cache_creation_input_tokens',0)+0.1*u.get('cache_read_input_tokens',0)+5*u.get('output_tokens',0)
agg=lambda: collections.defaultdict(lambda: collections.Counter())
by_proj=agg(); by_model=agg(); by_day=agg(); by_sess=agg(); by_lane=agg()
tool_calls=collections.Counter(); tool_result_bytes=collections.Counter(); tool_result_n=collections.Counter()
ctx_buckets=collections.Counter(); ctx_by_proj=collections.defaultdict(list)
sess_meta={}
big_results=[]
seen_msgs=set()
for path in glob.glob(ROOT+'/**/*.jsonl', recursive=True):
    try:
        if datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime('%Y-%m-%d')<START: continue
    except: continue
    proj=path[len(ROOT)+1:].split('/')[0]
    sid=os.path.basename(path)[:-6]
    is_sub='/subagents/' in path or '/agents/' in path
    with open(path,errors='ignore') as f:
        for line in f:
            try: d=json.loads(line)
            except: continue
            ts=d.get('timestamp','')[:10]
            if not (START<=ts<END): continue
            t=d.get('type')
            m=d.get('message') or {}
            cwd=d.get('cwd')
            if cwd and sid not in sess_meta: sess_meta[sid]=(proj,cwd,ts)
            if t=='assistant':
                mid=m.get('id'); 
                u=m.get('usage') or {}
                if not u: continue
                key=(mid,u.get('output_tokens'))
                if mid and key in seen_msgs: continue
                seen_msgs.add(key)
                model=m.get('model','?')
                ctx=u.get('input_tokens',0)+u.get('cache_creation_input_tokens',0)+u.get('cache_read_input_tokens',0)
                rec={'calls':1,'in':u.get('input_tokens',0),'cw':u.get('cache_creation_input_tokens',0),'cr':u.get('cache_read_input_tokens',0),'out':u.get('output_tokens',0),'think':(u.get('output_tokens_details') or {}).get('thinking_tokens',0),'w':wt(u),'ctxsum':ctx}
                lane='sub' if (is_sub or d.get('isSidechain')) else 'main'
                for k,v in rec.items():
                    by_proj[proj][k]+=v; by_model[model][k]+=v; by_day[ts][k]+=v; by_sess[sid][k]+=v; by_lane[lane][k]+=v
                by_sess[sid]['model_'+model]+=1
                b='<50k' if ctx<50000 else '50-100k' if ctx<100000 else '100-200k' if ctx<200000 else '200k+'
                ctx_buckets[b]+=1; ctx_by_proj[proj].append(ctx)
                for c in m.get('content') or []:
                    if isinstance(c,dict) and c.get('type')=='tool_use':
                        tool_calls[c.get('name')]+=1; by_sess[sid]['tools']+=1
            elif t=='user':
                for c in (m.get('content') or []) if isinstance(m.get('content'),list) else []:
                    if isinstance(c,dict) and c.get('type')=='tool_result':
                        cont=c.get('content'); s=len(json.dumps(cont)) if cont else 0
                        name=(d.get('toolUseResult') or {}).get('tool') if isinstance(d.get('toolUseResult'),dict) else None
                        tool_result_bytes[proj]+=s; tool_result_n[proj]+=1
                        if s>40000: big_results.append((s,proj,sid,ts,str(cont)[:120].replace('\n',' ')))
out={'by_proj':by_proj,'by_model':by_model,'by_day':by_day,'by_lane':by_lane,'tool_calls':tool_calls,'ctx_buckets':ctx_buckets,
     'tool_result_bytes':tool_result_bytes,'tool_result_n':tool_result_n,
     'by_sess':{k:dict(v) for k,v in by_sess.items()},'sess_meta':sess_meta,
     'ctx_avg_by_proj':{p:(sum(v)/len(v),max(v),len(v)) for p,v in ctx_by_proj.items()},
     'big_results':sorted(big_results,reverse=True)[:40]}
json.dump(out,open(_A.out,'w'),default=dict,indent=0)
def show(name,dd,key='w'):
    print('\n##',name)
    for k,v in sorted(dd.items(),key=lambda kv:-kv[1][key])[:25]:
        print(f"{k[:60]:60s} calls={v['calls']:6d} in={v['in']/1e6:7.1f}M cw={v['cw']/1e6:7.1f}M cr={v['cr']/1e6:8.1f}M out={v['out']/1e6:6.2f}M think={v['think']/1e6:5.2f}M W={v['w']/1e6:8.1f}M avgctx={v['ctxsum']/max(v['calls'],1)/1e3:6.0f}k")
show('by project',by_proj); show('by model',by_model); show('by day',by_day); show('by lane',by_lane)
print('\n## ctx buckets',dict(ctx_buckets))
print('\n## tool calls'); [print(f'{k:45s}{v}') for k,v in tool_calls.most_common(40)]
