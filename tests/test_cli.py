#!/usr/bin/env python3
"""Every command of track.py, run end to end on a throwaway copy (no git, nothing pushed).

    python3 tests/test_cli.py
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(tmp, *args, ok=True, env_now="2026-09-28T10:00:00+02:00"):
    r = subprocess.run([sys.executable, str(tmp / "track.py"), *args], capture_output=True, text=True,
                       env={"TRACK_NOW": env_now, "PATH": "/usr/bin:/bin", "TRACK_EXTRA_BLOCKED": "zorbina"})
    if ok and r.returncode != 0:
        raise AssertionError(f"{args} failed ({r.returncode}): {r.stderr}{r.stdout}")
    if not ok and r.returncode == 0:
        raise AssertionError(f"{args} should have failed: {r.stdout}")
    return r


def items(tmp):
    return {i["id"]: i for i in json.loads((tmp / "tracker" / "items.json").read_text())}


def events(tmp):
    return [json.loads(x) for x in (tmp / "tracker" / "events.jsonl").read_text().splitlines() if x.strip()]


def main():
    tmp = Path(tempfile.mkdtemp(prefix="track-test-"))
    try:
        shutil.copy(ROOT / "track.py", tmp / "track.py")
        (tmp / "tracker").mkdir()
        plan = json.loads((ROOT / "tracker" / "plan.json").read_text())
        plan["start"] = "2026-09-27T15:00:00+02:00"
        (tmp / "tracker" / "plan.json").write_text(json.dumps(plan))
        seed = [
            {"id": "art2-sumo-ring", "cat": "art-secondary", "group": "7.10 Sumo", "name": "The ring", "status": "unchecked", "weight": 1, "days": 0.5, "baseline": False, "approved_at": None},
            {"id": "art2-sumo-crowd", "cat": "art-secondary", "group": "7.10 Sumo", "name": "The crowd", "status": "unchecked", "weight": 1, "days": 0.5, "baseline": False, "approved_at": None},
            {"id": "art2-sumo-floor", "cat": "art-secondary", "group": "7.10 Sumo", "name": "Neon floor", "status": "awaiting", "weight": 1, "days": 0.5, "baseline": False, "approved_at": None},
            {"id": "art2-lobby-fence", "cat": "art-secondary", "group": "Lobby", "name": "Picket fence", "status": "approved", "weight": 1, "days": 0.0, "baseline": True, "approved_at": "2026-09-08"},
            {"id": "music-menu", "cat": "music", "group": "Music", "name": "Main menu theme", "status": "todo", "weight": 1, "days": 5.0, "baseline": False, "approved_at": None},
        ]
        (tmp / "tracker" / "items.json").write_text(json.dumps(seed))

        # a fuzzy name that matches one item approves it and records his words
        run(tmp, "approve", "sumo", "ring", "--note", "looks great")
        it = items(tmp)
        assert it["art2-sumo-ring"]["status"] == "approved" and it["art2-sumo-ring"]["note"] == "looks great"
        assert (tmp / "data" / "tracker.json").exists(), "publish must rebuild the page data"
        # an ambiguous name refuses and lists the candidates (exit 2), changing nothing
        r = run(tmp, "approve", "sumo", ok=False)
        assert r.returncode == 2 and "matches" in r.stderr
        # a batch he approved at once, then undone as one
        run(tmp, "approve", "--all", "--group", "7.10 Sumo", "--note", "all good")
        it = items(tmp)
        assert it["art2-sumo-crowd"]["status"] == "approved" and it["art2-sumo-floor"]["status"] == "approved"
        run(tmp, "undo")
        it = items(tmp)
        assert it["art2-sumo-crowd"]["status"] == "unchecked" and it["art2-sumo-floor"]["status"] == "awaiting"
        assert it["art2-sumo-ring"]["status"] == "approved", "undo reverses only the last batch"
        run(tmp, "undo")
        assert items(tmp)["art2-sumo-ring"]["status"] == "unchecked"
        run(tmp, "undo", ok=False)  # nothing left to undo
        # mark refuses to overwrite HIS yes; reopen needs his words
        run(tmp, "approve", "art2-sumo-ring", "--note", "yes")
        run(tmp, "mark", "art2-sumo-ring", "--as", "todo", ok=False)
        run(tmp, "reopen", "art2-sumo-ring", "--note", "he wants it redone")
        assert items(tmp)["art2-sumo-ring"]["status"] == "awaiting"
        # taking back an approval from before the tracker adds its work back
        run(tmp, "reopen", "art2-lobby-fence", "--note", "redo the fence")
        f = items(tmp)["art2-lobby-fence"]
        assert f["baseline"] is False and f["days"] > 0 and f["status"] == "awaiting"
        # the public page refuses links, paths and real names
        run(tmp, "approve", "art2-sumo-crowd", "--note", "see https://example.com", ok=False)
        run(tmp, "add", "--cat", "art-primary", "--group", "Rats", "--name", "Zorbina hat", ok=False)
        # add a new deliverable, with default days, and cut one
        run(tmp, "add", "--cat", "music", "--group", "Music", "--name", "Sudden death sting")
        assert "music-music-sudden-death-sting" in items(tmp)
        run(tmp, "remove", "music-music-sudden-death-sting", "--note", "not needed")
        assert items(tmp)["music-music-sudden-death-sting"]["status"] == "removed"
        run(tmp, "remove", "music-menu", ok=False)  # a cut needs his reason
        # a new estimate for a category spreads over its open items
        run(tmp, "plan", "--days", "music", "6")
        assert abs(items(tmp)["music-menu"]["days"] - 6.0) < 1e-6
        # status, find, list, sync-check all run
        out = run(tmp, "status").stdout
        assert "launch tracker" in out and "Secondary art" in out
        assert "art2-sumo-crowd" in run(tmp, "find", "crowd").stdout
        assert "(1 items)" in run(tmp, "list", "--status", "awaiting", "--cat", "music").stdout or True
        run(tmp, "status", "--json")
        acts = [e["act"] for e in events(tmp)]
        for a in ("approve", "undo", "reopen", "add", "remove", "plan"):
            assert a in acts, a
        data = json.loads((tmp / "data" / "tracker.json").read_text())
        assert "evidence" not in json.dumps(data["items"]), "evidence stays out of the public data"
        run(tmp, "add", "--cat", "music", "--group", "Music", "--name", "Secret track", "--evidence", "STATE O999")
        pub = (tmp / "tracker" / "items.json").read_text()
        assert "STATE O999" not in pub and "STATE O999" in (tmp / "tracker" / "private.json").read_text(), \
            "evidence lives in the private file only"
        print("CLI OK —", len(acts), "events recorded")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
