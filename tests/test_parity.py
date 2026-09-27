#!/usr/bin/env python3
"""The page and the tool must agree to the hundredth of a day.

track.py compute() and assets/stats.js computeStats() are two independent implementations
of the same model (the skill's method: write the runtime twice and diff it). This runs both
on one synthetic tracker at several moments — before the start, inside the first day, weeks
in, across the October clock change, past the deadline — and on the REAL data when it exists.

    python3 tests/test_parity.py
"""
import datetime as dt
import json
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import track  # noqa: E402

FIELDS = ["total_work_days", "earned_days", "planned_days", "variance_days", "left_days",
          "days_to_deadline", "spare_days", "launch_pct", "approved_7d"]
CAT_FIELDS = ["pct", "work_days", "done_days", "left_days", "items", "approved", "plan_start", "plan_end"]


def synthetic():
    plan = json.loads((ROOT / "tracker" / "plan.json").read_text()) if (ROOT / "tracker" / "plan.json").exists() else None
    if plan is None:
        raise SystemExit("tracker/plan.json is needed")
    plan = json.loads(json.dumps(plan))
    plan["start"] = "2026-09-27T15:00:00+02:00"
    rnd = random.Random(7)
    items = []
    start = track.parse_time(plan["start"])
    for c in plan["categories"]:
        n = rnd.randint(4, 14)
        for k in range(n):
            st = rnd.choice(["approved", "approved", "awaiting", "unchecked", "pixel", "in-progress", "todo", "removed"])
            baseline = st == "approved" and rnd.random() < 0.4
            it = {"id": f"{c['id']}-{k}", "cat": c["id"], "group": f"G{k % 3}", "name": f"item {k}",
                  "status": st, "weight": rnd.choice([1, 1, 2, 0.5]), "baseline": baseline,
                  "days": 0.0 if baseline else round(c["days"] / n * rnd.uniform(0.5, 1.5), 4),
                  "approved_at": None}
            if st == "approved":
                it["approved_at"] = ("2026-09-20" if baseline else
                                     track.iso(start + dt.timedelta(days=rnd.uniform(0, 40))))
            items.append(it)
    return plan, items


def js_compute(plan, items, now_ms):
    src = (ROOT / "assets" / "stats.js").read_text()
    prog = src + "\nconst S = module.exports;\nconst d = JSON.parse(require('fs').readFileSync(0,'utf8'));\n" \
                 "process.stdout.write(JSON.stringify(S.computeStats(d.plan, d.items, d.now)));\n"
    r = subprocess.run(["node", "-e", "const module={exports:{}};" + prog], input=json.dumps(
        {"plan": plan, "items": items, "now": now_ms}), capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("node failed: " + r.stderr)
    return json.loads(r.stdout)


def compare(plan, items, now, label):
    py = track.compute(plan, items, now)
    js = js_compute(plan, items, int(now.timestamp() * 1000))
    bad = []
    for f in FIELDS:
        a, b = py[f], js[f]
        if abs(float(a) - float(b)) > 0.01:
            bad.append(f"{f}: py {a} js {b}")
    if (py["pace_7d"] is None) != (js["pace_7d"] is None) or (
            py["pace_7d"] is not None and abs(py["pace_7d"] - js["pace_7d"]) > 0.01):
        bad.append(f"pace_7d: py {py['pace_7d']} js {js['pace_7d']}")
    if py["current_phase"] != js["current_phase"]:
        bad.append(f"current_phase: py {py['current_phase']} js {js['current_phase']}")
    for pc, jc in zip(py["categories"], js["categories"]):
        for f in CAT_FIELDS:
            if abs(float(pc[f]) - float(jc[f])) > 0.01:
                bad.append(f"{pc['id']}.{f}: py {pc[f]} js {jc[f]}")
    status = "ok " if not bad else "FAIL"
    print(f"{status} {label:<34} variance {py['variance_days']:+.3f}  spare {py['spare_days']:.3f}  "
          f"launch {py['launch_pct']:.2f}%  phase {py['current_phase']}")
    for b in bad:
        print("     " + b)
    return not bad


def main():
    ok = True
    plan, items = synthetic()
    start = track.parse_time(plan["start"])
    moments = [("before the start", start - dt.timedelta(days=1)),
               ("inside the first day", start + dt.timedelta(hours=7)),
               ("day 5.7", start + dt.timedelta(days=5.7)),
               ("across the Oct 25 clock change", track.parse_time("2026-10-25T02:30:00+01:00")),
               ("day 30", start + dt.timedelta(days=30)),
               ("the deadline's last hour", track.parse_time("2026-11-23T23:30:00+01:00")),
               ("two days past the deadline", track.parse_time("2026-11-26T09:00:00+01:00"))]
    for label, now in moments:
        ok &= compare(plan, items, now, "synthetic · " + label)
    real_items = ROOT / "tracker" / "items.json"
    if real_items.exists():
        rp = json.loads((ROOT / "tracker" / "plan.json").read_text())
        ri = json.loads(real_items.read_text())
        for label, now in [("now", track.now_local()), ("in 10 days", track.now_local() + dt.timedelta(days=10))]:
            ok &= compare(rp, ri, now, "REAL · " + label)
    # the deadline itself: end of 23 Nov in Prague is 23:00 UTC (winter time)
    end = track.deadline_end({"deadline": "2026-11-23"})
    js_end = subprocess.run(["node", "-e", "const module={exports:{}};" + (ROOT / "assets" / "stats.js").read_text() +
                             "\nprocess.stdout.write(String(module.exports.deadlineEnd('2026-11-23')))"],
                            capture_output=True, text=True).stdout
    same = int(end.timestamp() * 1000) == int(js_end)
    print(("ok " if same else "FAIL") + f" deadline end   py {end.isoformat()}  js {dt.datetime.fromtimestamp(int(js_end)/1000, dt.timezone.utc).isoformat()}")
    ok &= same
    print("PARITY OK" if ok else "PARITY FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
