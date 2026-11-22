Good result; 0.70 is committed and pushed by Claude (imported from your bundle).

Next: one tuning variant, `heal_gate.hp_frac` = 0.85, same four runs (practice s1, s2, `--ffa` s1, s2; 16 matches, `--record`,
fights.py, archive to `replays\t2_on_085\`). Don't change code beyond the param.

- If 0.85 beats 0.70 on practice score and kills (both seeds) and FFA is not worse on average: set 0.85 in params.json and
  deliver it as a new commit in a git bundle as before (`replays\t2-heal-gate-085.bundle`, based on `585b8e8`).
- Otherwise leave params at 0.70 and commit nothing.

Report under 15 lines: the four runs at 0.85 next to 0.70, and keep 0.70 or switch to 0.85.
