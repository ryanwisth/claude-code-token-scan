"""Token use by model since a start time (for example a weekly usage reset), from Claude Code transcripts. Read-only.
usage: usage_by_model.py [ISO start, default 7 days ago] [--root DIR]
The transcript directory comes from --root, else $CLAUDE_PROJECTS_DIR, else ~/.claude/projects."""
import json, sys, os, glob, collections
from datetime import datetime, timezone
import argparse
from datetime import timedelta
_ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
_ap.add_argument('start', nargs='?', default=(datetime.now(timezone.utc) - timedelta(days=7)).strftime('%Y-%m-%dT%H:%M:%SZ'),
                 help='ISO start time, e.g. 2026-01-05T18:00:00Z (default: 7 days ago)')
_ap.add_argument('--root', default=os.environ.get('CLAUDE_PROJECTS_DIR', '~/.claude/projects'), help='transcript directory')
_A = _ap.parse_args()
start = _A.start
t0 = datetime.fromisoformat(start.replace('Z', '+00:00')).timestamp()
root = os.path.expanduser(_A.root).rstrip('/')
seen = set(); M = collections.defaultdict(lambda: collections.Counter()); P = collections.defaultdict(lambda: collections.Counter()); D = collections.defaultdict(lambda: collections.Counter())
extra = collections.Counter(); files = 0
def units(u):  # one model's own price shape: input 1, cache write 1.25, cache read 0.1, output 5
    return (u.get('input_tokens', 0) + 1.25 * u.get('cache_creation_input_tokens', 0)
            + 0.1 * u.get('cache_read_input_tokens', 0) + 5 * u.get('output_tokens', 0))
for f in glob.glob(root + '/**/*.jsonl', recursive=True):
    if os.path.getmtime(f) < t0: continue
    files += 1
    proj = os.path.relpath(f, root).split(os.sep)[0]
    with open(f, errors='ignore') as fh:
        for line in fh:
            if '"usage"' not in line: continue
            try: o = json.loads(line)
            except Exception: continue
            m = o.get('message') or {}; u = m.get('usage'); ts = o.get('timestamp')
            if not u or not ts or not m.get('model'): continue
            try: t = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            except Exception: continue
            if t.timestamp() < t0: continue
            key = (m.get('id'), o.get('requestId'))
            if key in seen: continue
            seen.add(key)
            for k in o:
                if 'cost' in k.lower(): extra[k] += 1
            model = m['model']; un = units(u)
            c = M[model]; c['calls'] += 1; c['in'] += u.get('input_tokens', 0); c['cw'] += u.get('cache_creation_input_tokens', 0)
            c['cr'] += u.get('cache_read_input_tokens', 0); c['out'] += u.get('output_tokens', 0); c['units'] += un
            P[proj][model] += un; D[t.astimezone().strftime('%a %d')][model] += un
tot = sum(c['units'] for c in M.values()) or 1
print(f'since {start}: {files} transcript files, {len(seen)} model calls')
print('model                      calls   input  cache-write  cache-read   output   units(M)  share')
for model, c in sorted(M.items(), key=lambda kv: -kv[1]['units']):
    print(f"{model:25s} {c['calls']:6d} {c['in']/1e6:6.1f}M {c['cw']/1e6:10.1f}M {c['cr']/1e6:10.1f}M {c['out']/1e6:7.1f}M {c['units']/1e6:9.1f} {100*c['units']/tot:5.1f}%")
models = [m for m, _ in sorted(M.items(), key=lambda kv: -kv[1]['units'])][:4]
print('\nby day (units, M):      ' + '  '.join(f'{m[:16]:>16s}' for m in models))
for d in sorted(D, key=lambda s: s.split()[1]): print(f'{d:22s}  ' + '  '.join(f'{D[d][m]/1e6:16.1f}' for m in models))
print('\nby project folder (units, M):')
for p, c in sorted(P.items(), key=lambda kv: -sum(kv[1].values()))[:8]:
    print(f'{p[:44]:44s} ' + '  '.join(f'{m[:12]}:{c[m]/1e6:.1f}' for m in models if c[m]))
print('cost fields seen:', dict(extra))
