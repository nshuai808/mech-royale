"""Scripted check over the protocol: a laser charge held through a 0.2 s loss of the target. Usage: python3 tools/laser_hold_check.py BOT_BINARY"""
import json, gzip, subprocess, sys, math, copy
bot = sys.argv[1]
L = gzip.open('kit/check/stream.jsonl.gz', 'rt').read().splitlines()
hello = json.loads(L[0]); first = next(json.loads(l) for l in L[1:] if json.loads(l).get('type') == 'obs')
W = hello['config']['weapons']
p = subprocess.Popen([bot], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
p.stdin.write(json.dumps(hello) + "\n"); p.stdin.flush(); p.stdout.readline()
me = first['self']; x, y, z = me['pos']
gun = {"kind": "gun", "cooldown": 0, "ammo": 12, "reload": 0, "stats": W['gun']}
def obs(t, charge, visible, aim_yaw):
    o = copy.deepcopy(first); o['t'] = t; o['tick'] = int(t * 20); o['events'] = []; o['alive'] = 16
    o['pickups'] = []; o['crates'] = []; o['cubes'] = []; o['drops'] = []; o['sounds'] = []; o['beams'] = []; o['projectiles'] = []
    s = o['self']; s['in_zone'] = True; s['hp'] = s['max_hp']; s['energy'] = 100; s['aim'] = [aim_yaw, 0]
    s['weapons'] = [gun, {"kind": "laser", "cooldown": 0, "charge": charge, "stats": W['laser']}]
    o['zone'] = {"center": [x, y], "radius": 500, "next_center": [x, y], "next_radius": 400, "shrink_start": 400, "shrink_end": 450, "dps": 20}
    o['mechs'] = [{"id": 7, "kind": "mech", "pos": [x + 100, y, z], "vel": [0, 3, 0], "aim": [math.pi, 0], "hp": 1400, "max_hp": 1400,
                   "cubes": 0, "weapons": ["gun"], "charging": False}] if visible else []
    return o
out = []
seq = [(30.0, 0, True), (30.1, 0.1, True), (30.2, 0.25, True), (30.3, 0.4, False), (30.4, 0.5, False), (30.5, 0.6, True)]
for t, ch, vis in seq:
    p.stdin.write(json.dumps(obs(t, ch, vis, 0.0)) + "\n"); p.stdin.flush()
    a = json.loads(p.stdout.readline()); out.append((t, ch, vis, a.get('fire'), [round(v, 3) for v in a['aim']]))
p.stdin.write(json.dumps({"type": "end", "place": 1, "kills": 0}) + "\n"); p.stdin.flush()
for r in out: print("t=%.1f charge=%.2f target_visible=%-5s fire=%s aim=%s" % r)
