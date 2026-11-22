Delivered [t15-damage.bundle](C:/Users/natha/Downloads/mech-royale-t5/replays/t15-damage.bundle) with **both flags on**. Commit `f9b7048c94694ed8602ad4484ab2b056dcc8b962`.

- `dmg_build` uses the bot’s existing held-weapon priority as a proxy for damage contribution. It prefers that weapon’s listed damage upgrades, then plating, armor, capacitor, and nanites.
- `lt_close` allows closing above 35% HP and 35 energy, with up to two exposed enemies if the target is below half HP. Boosting stops 25 m outside the current lightning range.

All tests passed, including five synthetic checks in `test_damage.py`. Protocol check passed at **9.8 ms local p99**. Fuzz found **zero exceptions** in 1,200 decisions.

All 16 default FFA smoke matches completed without late answers or bot errors. The gun-only sim checks movement compatibility. Real practice will judge the build.