"""Run tools/sim.py matches in parallel and print the same report as one sequential run.

    python tools/simpar.py --jobs 8 --matches 16 --seed 1 [any other sim.py flags] -- python -u bot.py

Each match has its own seed (seed*1000 + n), so splitting the match range across processes gives exactly the
same per-match results as a sequential run; this script only shards (--first/--matches) and merges in seed order.
The SCORE and TIMELINE lines are recomputed from the merged match lines.
"""
import os, re, subprocess, sys, time


def main():
    argv = sys.argv[1:]
    if "--" not in argv:
        sys.exit(__doc__)
    cut = argv.index("--")
    opts, bot = argv[:cut], argv[cut:]

    def take(flag, default):
        if flag in opts:
            i = opts.index(flag)
            v = opts[i + 1]
            del opts[i:i + 2]
            return int(v)
        return default

    jobs, matches, first = take("--jobs", 8), take("--matches", 8), take("--first", 0)
    jobs = max(1, min(jobs, matches))
    sim = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sim.py")
    chunks, start = [], first
    for j in range(jobs):
        n = matches // jobs + (1 if j < matches % jobs else 0)
        if n:
            chunks.append((start, n))
            start += n
    t0 = time.time()
    procs = [subprocess.Popen([sys.executable, sim, "--first", str(a), "--matches", str(n), *opts, *bot],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True)
             for a, n in chunks]
    lines, timelines = [], []
    for p in procs:
        out, _ = p.communicate()
        for ln in out.splitlines():
            if ln.startswith("match"):
                lines.append(ln)
            elif ln.startswith("TIMELINE"):
                timelines.append(ln)
            elif not ln.startswith("SCORE"):
                print(ln)
    seed_of = lambda ln: int(re.search(r"seed (\d+)", ln).group(1))
    lines.sort(key=seed_of)
    pts = []
    for i, ln in enumerate(lines):
        print(re.sub(r"^match\s+\d+", f"match {first + i + 1:2}", ln))
        pts.append(int(re.search(r"\(\s*(\d+) pts\)", ln).group(1)))
    # TIMELINE: weighted merge of the per-chunk lines (each covers its own matches)
    if timelines and len(timelines) == len(chunks):
        tot = {"k150": 0.0, "k300": 0.0, "kall": 0.0, "a150": 0, "a300": 0, "n": 0}
        for (a, n), tl in zip(chunks, timelines):
            f = [float(x) for x in re.findall(r"[\d.]+", tl)]
            tot["k150"] += f[1] * n; tot["k300"] += f[3] * n; tot["kall"] += f[4] * n
            tot["a150"] += int(f[6]); tot["a300"] += int(f[9]); tot["n"] += n
        n = max(1, tot["n"])
        print(f"TIMELINE kills by 150s {tot['k150'] / n:.2f}  by 300s {tot['k300'] / n:.2f}  total {tot['kall'] / n:.2f}  "
              f"alive at 150s {tot['a150']}/{n}  at 300s {tot['a300']}/{n}")
    if pts:
        mean = sum(pts) / len(pts)
        sd = (sum((p - mean) ** 2 for p in pts) / max(1, len(pts) - 1)) ** 0.5
        print(f"SCORE {mean:.2f}  (+-{sd / max(1, len(pts)) ** 0.5:.2f} s.e., {len(pts)} matches, {time.time() - t0:.0f} s, {len(chunks)} jobs)")


if __name__ == "__main__":
    main()
