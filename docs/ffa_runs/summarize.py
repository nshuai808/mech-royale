"""Summarize sim.py --ffa outputs: python docs/ffa_runs/summarize.py docs/ffa_runs/*.txt"""
import re
import statistics as st
import sys
from collections import defaultdict

PAT = re.compile(r"place\s+(\d+).*?died (\S+).*?at\s+([\d.]+)s\s+kills (\d+)\s+drops (\d+)")
rows = defaultdict(list)
for path in sys.argv[1:]:
    name = re.search(r"(\w+)_s(\d)\.txt", path.replace("\\", "/"))
    var, seed = name.group(1), name.group(2)
    for line in open(path):
        m = PAT.search(line)
        if m:
            place, cause, t, k, d = int(m.group(1)), m.group(2), float(m.group(3)), int(m.group(4)), int(m.group(5))
            rows[(var, seed)].append((16 - place, cause, t, k, d))
            rows[(var, "all")].append((16 - place, cause, t, k, d))


def fmt(r):
    pts = [x[0] for x in r]
    n = len(r)
    se = st.stdev(pts) / n ** 0.5 if n > 1 else 0
    return (f"n={n:2} score {st.mean(pts):5.2f} +-{se:.2f}  kills {st.mean(x[3] for x in r):.2f}  "
            f"median t {st.median(x[2] for x in r):5.1f}s  mean t {st.mean(x[2] for x in r):5.1f}s  "
            f"<30s {sum(x[2] < 30 and x[1] != 'survived' for x in r) / n:4.0%}  zone deaths {sum(x[1] == 'zone' for x in r)}  "
            f"survived {sum(x[1] == 'survived' for x in r)}  drops {sum(x[4] for x in r)}  top4 {sum(x[0] >= 12 for x in r)}")


for key in sorted(rows):
    print(f"{key[0]:4} s{key[1]:3} {fmt(rows[key])}")
