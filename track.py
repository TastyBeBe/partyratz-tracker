#!/usr/bin/env python3
"""THE PARTY RATZ 4 LIFE LAUNCH TRACKER — its one command.

Albert, 2026-09-27: *"whenever I approve something with the agent developer, it should be
marked as completed and the percentage of the completion should increase ... make sure that
whenever I truly approve something, it gets marked in the tracker as approved."*

This file is the ONLY writer of the tracker's data. Every change it makes is appended to
tracker/events.jsonl, rebuilt into data/tracker.json (what the page reads) and pushed, so
the page at https://tastybebe.github.io/partyratz-tracker/ shows it about a minute later.

    track.py status                                   # where the launch stands, in numbers
    track.py find sumo ring                           # look items up: id, status, name
    track.py list --cat art-secondary --status awaiting
    track.py approve <id|words> --note "his words"    # HIS yes: the only thing that completes an item
    track.py approve --all --group "7.10 Sumo" --cat art-secondary --note "..."   # a whole batch he approved
    track.py mark <id|words> --as awaiting            # progress short of his yes (awaiting|unchecked|pixel|in-progress|todo)
    track.py reopen <id> --note "why"                 # he took an approval back
    track.py add --cat music --group "Music" --name "Sudden death sting"          # a new deliverable
    track.py remove <id> --note "why"                 # cut from the game
    track.py plan --days music 6                      # his new estimate for a whole category
    track.py undo                                     # reverse the last change
    track.py publish                                  # rebuild + push (every change above already does it)
    track.py sync-check                               # game commits that mention a verdict since the last record

THE RULE THE WHOLE THING RESTS ON: only Albert's own yes makes an item "approved". An item an
agent made, fixed or finished is "awaiting" until he says so. Never approve on his behalf.

The page is PUBLIC (his choice, 2026-09-27): names, numbers and dates only. The tool refuses
links, file paths and e-mail addresses in any text it stores.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
PLAN = ROOT / "tracker" / "plan.json"
ITEMS = ROOT / "tracker" / "items.json"
PRIVATE = ROOT / "tracker" / "private.json"   # evidence and audit notes: gitignored, never published
EVENTS = ROOT / "tracker" / "events.jsonl"
SITE_DATA = ROOT / "data" / "tracker.json"
LOCK = ROOT / ".track.lock"
GAME_REPO = Path.home() / "Gamesky" / "krysy4life"
TZ = ZoneInfo("Europe/Prague")
PAGE_URL = "https://tastybebe.github.io/partyratz-tracker/"

STATUSES = ["approved", "awaiting", "unchecked", "pixel", "in-progress", "todo", "removed"]
OPEN_STATUSES = ["awaiting", "unchecked", "pixel", "in-progress", "todo"]
LABEL = {
    "approved": "approved",
    "awaiting": "waiting for his verdict",
    "unchecked": "made, not checked by him",
    "pixel": "still old pixel art",
    "in-progress": "in progress",
    "todo": "to do",
    "removed": "cut",
}
FORBIDDEN = [
    (re.compile(r"https?://|www\.", re.I), "a link"),
    (re.compile(r"(^|[\s(])(/Users/|~/|/private/|/tmp/)", re.I), "a file path"),
    (re.compile(r"chatgpt\.com|chat\.openai", re.I), "a ChatGPT link"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}"), "an e-mail address"),
]


# Words that must never reach the public page, kept as hashes so that publishing this file does
# not publish the words (the rats are called by their colour everywhere: his ruling of 2026-09-20).
# To add one: python3 -c "import hashlib; print(hashlib.sha256(b'word').hexdigest()[:16])"
BLOCKED_WORD_HASHES = {"7975b4132aaa77d7", "8499bdca52e69fc8", "a5212781515becd5", "b4b6e5deeec12539", "d7bfd22c56faa2f1", "eb4a3985ecc16965", "f05af0fa316d200e"}


def _blocked_word(text: str) -> bool:
    extra = {w.strip() for w in os.environ.get("TRACK_EXTRA_BLOCKED", "").lower().split(",") if w.strip()}
    ws = norm(text).split()
    for k, w in enumerate(ws):
        for cand in (w, w + ws[k + 1] if k + 1 < len(ws) else None):
            if cand and (hashlib.sha256(cand.encode()).hexdigest()[:16] in BLOCKED_WORD_HASHES or cand in extra):
                return True
    return False

# ----------------------------------------------------------------------------- basics

# EVERY instant is held in UTC and shown in Prague time. Python compares and subtracts two
# datetimes that share one tzinfo on their WALL clocks, ignoring the summer-time change —
# found by tests/test_parity.py as a one-hour gap against the page (2026-09-27).
UTC = dt.timezone.utc


def now_local() -> dt.datetime:
    forced = os.environ.get("TRACK_NOW")
    if forced:
        return parse_time(forced)
    return dt.datetime.now(UTC)


def parse_time(s: str) -> dt.datetime:
    """An ISO date or datetime, returned in UTC; a bare date means noon that day in Prague."""
    s = s.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        d = dt.date.fromisoformat(s)
        return dt.datetime(d.year, d.month, d.day, 12, 0, tzinfo=TZ).astimezone(UTC)
    t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    return (t if t.tzinfo else t.replace(tzinfo=TZ)).astimezone(UTC)


def deadline_end(plan: dict) -> dt.datetime:
    """The deadline is the whole of that day: it ends at the next midnight in Prague."""
    nxt = dt.date.fromisoformat(plan["deadline"]) + dt.timedelta(days=1)
    return dt.datetime(nxt.year, nxt.month, nxt.day, tzinfo=TZ).astimezone(UTC)


def iso(t: dt.datetime) -> str:
    return t.astimezone(TZ).isoformat(timespec="seconds")


def days_between(a: dt.datetime, b: dt.datetime) -> float:
    return (b.astimezone(UTC) - a.astimezone(UTC)).total_seconds() / 86400.0


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def slug(s: str) -> str:
    return norm(s).replace(" ", "-")[:60].strip("-")


def check_public(*texts: str) -> None:
    for t in texts:
        if not t:
            continue
        for rx, what in FORBIDDEN:
            if rx.search(t):
                die(f"refused: the tracker page is public and this text contains {what}: {t!r}. "
                    "Write the reference as a doc name and row id instead, e.g. 'STATE O142'.")
        if _blocked_word(t):
            die(f"refused: the tracker page is public and {t!r} contains a name it must never show. "
                "Call the rats by their colour: Red, Yellow, Blue or Green Rat.")


def die(msg: str, code: int = 1) -> None:
    print(f"track: {msg}", file=sys.stderr)
    sys.exit(code)


def load_json(p: Path, default):
    if not p.exists():
        return default
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def write_json_atomic(p: Path, data, indent=1) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=p.name, suffix=".tmp")
    os.chmod(tmp, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)
        f.write("\n")
    os.replace(tmp, p)


ITEM_KEYS = ["id", "cat", "group", "game", "name", "kind", "status", "weight", "days", "count", "baseline",
             "approved_at", "note", "added_at", "updated_at"]
PRIVATE_KEYS = ["evidence", "detail"]


def load_items() -> list:
    items = load_json(ITEMS, [])
    priv = load_json(PRIVATE, {})
    for i in items:
        i.update(priv.get(i["id"], {}))
    return items


def save_items(items: list) -> None:
    write_json_atomic(ITEMS, [{k: i[k] for k in ITEM_KEYS if k in i} for i in items])
    old = load_json(PRIVATE, {})
    for i in items:
        extra = {k: i[k] for k in PRIVATE_KEYS if i.get(k)}
        if extra:
            old[i["id"]] = extra
    write_json_atomic(PRIVATE, old)


def load_events() -> list:
    out = []
    if EVENTS.exists():
        for line in EVENTS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
    return out


def append_event(ev: dict) -> None:
    EVENTS.parent.mkdir(parents=True, exist_ok=True)
    with open(EVENTS, "a", encoding="utf-8") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")


@contextlib.contextmanager
def locked():
    """One writer at a time: two sessions (or both Claude accounts) may call this at once."""
    LOCK.touch(exist_ok=True)
    with open(LOCK, "w") as fh:
        deadline = time.time() + 60
        while True:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.time() > deadline:
                    die("another tracker command has held the lock for 60 s; try again")
                time.sleep(0.2)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


# ----------------------------------------------------------------------------- the numbers
# The page computes the same numbers in assets/app.js (computeStats). The two are written
# independently on purpose and tests/test_parity.py runs both on the same data and diffs them.

def compute(plan: dict, items: list, now: dt.datetime) -> dict:
    start = parse_time(plan["start"])
    end = deadline_end(plan)
    live = [i for i in items if i["status"] != "removed"]
    cats = []
    total_work = 0.0
    earned = 0.0
    earned7 = 0.0
    approved7 = 0
    week_ago = now - dt.timedelta(days=7)
    cursor = 0.0
    for c in plan["categories"]:
        its = [i for i in live if i["cat"] == c["id"]]
        work = sum(i["days"] for i in its if not i.get("baseline"))
        done = 0.0
        for i in its:
            if i["status"] == "approved" and not i.get("baseline") and i.get("approved_at"):
                t = parse_time(i["approved_at"])
                if t <= now:
                    done += i["days"]
                    if t > week_ago:
                        earned7 += i["days"]
                        approved7 += 1
        w_all = sum(i.get("weight", 1) for i in its)
        w_ok = sum(i.get("weight", 1) for i in its if i["status"] == "approved")
        if c.get("pct_mode") == "given":
            base = float(c.get("his_pct", 0))
            pct = base + (100.0 - base) * (done / work if work > 0 else 1.0)
        else:
            pct = 100.0 * w_ok / w_all if w_all > 0 else 0.0
        by_status = {s: 0 for s in STATUSES if s != "removed"}
        for i in its:
            by_status[i["status"]] += 1
        cats.append({
            "id": c["id"],
            "pct": round(pct, 2),
            "work_days": round(work, 3),
            "done_days": round(done, 3),
            "left_days": round(work - done, 3),
            "items": len(its),
            "approved": by_status["approved"],
            "by_status": by_status,
            "plan_start": round(cursor, 3),
            "plan_end": round(cursor + work, 3),
        })
        cursor += work
        total_work += work
        earned += done
    elapsed = max(0.0, days_between(start, now))
    planned = min(elapsed, total_work)
    left = total_work - earned
    to_deadline = days_between(now, end)
    pace7 = None
    if elapsed >= 1.0:
        pace7 = earned7 / min(7.0, elapsed)
    finish_plan = now + dt.timedelta(days=left)
    finish_pace = None
    if pace7 and pace7 > 0:
        finish_pace = now + dt.timedelta(days=left / pace7)
    current = None
    for c in cats:
        if c["plan_start"] <= planned < c["plan_end"]:
            current = c["id"]
            break
    if current is None and cats:
        current = cats[-1]["id"] if planned >= total_work else cats[0]["id"]
    return {
        "now": iso(now),
        "total_work_days": round(total_work, 3),
        "earned_days": round(earned, 3),
        "planned_days": round(planned, 3),
        "variance_days": round(earned - planned, 3),
        "left_days": round(left, 3),
        "days_to_deadline": round(to_deadline, 3),
        "spare_days": round(to_deadline - left, 3),
        "launch_pct": round(100.0 * earned / total_work, 2) if total_work > 0 else 100.0,
        "approved_7d": approved7,
        "pace_7d": round(pace7, 3) if pace7 is not None else None,
        "finish_at_plan_pace": iso(finish_plan),
        "finish_at_recent_pace": iso(finish_pace) if finish_pace else None,
        "current_phase": current,
        "categories": cats,
    }


# ----------------------------------------------------------------------------- look-ups

def resolve(items: list, target: str, want_open: bool | None = None) -> list:
    by_id = {i["id"]: i for i in items}
    if target in by_id:
        return [by_id[target]]
    words = norm(target).split()
    if not words:
        return []
    hits = []
    for i in items:
        hay = norm(" ".join([i["id"], i["cat"], i["group"], i["name"], i.get("kind", "")]))
        if all(w in hay for w in words):
            hits.append(i)
    if want_open is True:
        hits = [i for i in hits if i["status"] in OPEN_STATUSES]
    elif want_open is False:
        hits = [i for i in hits if i["status"] == "approved"]
    return hits


def filtered(items, cat=None, group=None, status=None, kind=None):
    out = items
    if cat:
        out = [i for i in out if i["cat"] == cat]
    if group:
        g = norm(group)
        out = [i for i in out if g in norm(i["group"])]
    if status:
        wanted = {"open": OPEN_STATUSES}.get(status, [status])
        out = [i for i in out if i["status"] in wanted]
    if kind:
        out = [i for i in out if i.get("kind") == kind]
    return out


def show(i: dict) -> str:
    extra = f"  ({i['note']})" if i.get("note") else (f"  [{i['detail']}]" if i.get("detail") else "")
    return f"{i['id']:<46} [{i['status']:<11}] {i['group']} — {i['name']}{extra}"


def cat_ids(plan):
    return [c["id"] for c in plan["categories"]]


# ----------------------------------------------------------------------------- publishing

def sanitized(items: list) -> list:
    keep = ["id", "cat", "group", "game", "name", "kind", "status", "weight", "days", "count",
            "baseline", "approved_at", "note", "added_at"]
    return [{k: i[k] for k in keep if k in i} for i in items]


def build_site_data(plan, items, events, now) -> dict:
    return {
        "schema": 1,
        "generated_at": iso(now),
        "page": PAGE_URL,
        "plan": plan,
        "items": sanitized(items),
        "events": events[-600:],
        "stats": compute(plan, items, now),
    }


def git(*args, timeout=60, check=False):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True,
                          timeout=timeout, env=env, check=check)


def _core(d):
    """The page data minus what changes with the clock alone."""
    return None if not d else {k: v for k, v in d.items() if k not in ("generated_at", "stats")}


def publish(message: str, quiet: bool = False, push: bool = True) -> bool:
    plan = load_json(PLAN, None)
    items = load_items()
    events = load_events()
    new = build_site_data(plan, items, events, now_local())
    try:
        old = load_json(SITE_DATA, None)
    except json.JSONDecodeError:
        old = None
    # Rewritten only when something real changed, so "last change" on the page means a change
    # and the 15-minute retry job never commits noise.
    if _core(old) != _core(new):
        write_json_atomic(SITE_DATA, new, indent=None)
    if not (ROOT / ".git").exists():
        if not quiet:
            print("track: data rebuilt (no git repository yet, nothing pushed)")
        return False
    git("add", "tracker", "data")
    if git("diff", "--cached", "--quiet", "--", "tracker", "data").returncode != 0:
        # only the tracker's own data, never anything else that happens to be staged
        r = git("commit", "-q", "-m", message, "--", "tracker", "data")
        if r.returncode != 0:
            print("track: commit failed: " + (r.stderr or r.stdout).strip(), file=sys.stderr)
            return False
    if not push:
        return True
    return push_if_needed(quiet)


def push_if_needed(quiet: bool = False) -> bool:
    if git("remote").stdout.strip() == "":
        if not quiet:
            print("track: no remote configured; committed locally only")
        return False
    ahead = git("rev-list", "--count", "@{u}..HEAD")
    if ahead.returncode == 0 and ahead.stdout.strip() == "0":
        if not quiet:
            print("track: published (nothing new to push)")
        return True
    try:
        r = git("push", "-q", timeout=45)
    except subprocess.TimeoutExpired:
        print("track: push timed out; the launchd job retries every 15 minutes", file=sys.stderr)
        return False
    if r.returncode != 0:
        print("track: push failed (retried every 15 minutes by launchd): " + r.stderr.strip(), file=sys.stderr)
        return False
    if not quiet:
        print(f"track: published — live on {PAGE_URL} in about a minute")
    return True


# ----------------------------------------------------------------------------- changes

def new_op(now) -> str:
    """One id per command run, so `undo` reverses a whole batch approval at once."""
    return f"{iso(now)}#{os.urandom(2).hex()}"


def change(items, item, new_status, now, act, note="", by="agent", approved_at=None, op=None):
    prev = {k: item.get(k) for k in ("status", "approved_at", "note", "days", "baseline")}
    item["status"] = new_status
    if new_status == "approved":
        item["approved_at"] = approved_at or iso(now)
    elif act in ("reopen", "mark"):
        item["approved_at"] = None
    if note:
        item["note"] = note
    item["updated_at"] = iso(now)
    append_event({"ts": iso(now), "op": op or new_op(now), "act": act, "id": item["id"],
                  "from": prev["status"], "to": new_status, "note": note, "by": by, "prev": prev})


def default_days(plan, items, cat):
    its = [i for i in items if i["cat"] == cat and not i.get("baseline") and i["status"] != "removed"]
    if its:
        return round(sum(i["days"] for i in its) / len(its), 4)
    c = next(c for c in plan["categories"] if c["id"] == cat)
    return round(float(c["days"]) / 10.0, 4)


def rebalance(plan, items, cat, total=None, left=None):
    """Spread a category's days over its open items by weight (approved days stay as earned)."""
    its = [i for i in items if i["cat"] == cat and not i.get("baseline") and i["status"] != "removed"]
    done = sum(i["days"] for i in its if i["status"] == "approved")
    open_its = [i for i in its if i["status"] != "approved"]
    target = left if left is not None else max(0.0, float(total) - done)
    w = sum(i.get("weight", 1) for i in open_its)
    for i in open_its:
        i["days"] = round(target * i.get("weight", 1) / w, 4) if w > 0 else 0.0
    return target, len(open_its)


# ----------------------------------------------------------------------------- commands

def cmd_status(a):
    plan, items = load_json(PLAN, None), load_items()
    now = parse_time(a.now) if a.now else now_local()
    s = compute(plan, items, now)
    now = now.astimezone(TZ)
    if a.json:
        print(json.dumps(s, ensure_ascii=False, indent=1))
        return
    names = {c["id"]: c["name"] for c in plan["categories"]}
    v = s["variance_days"]
    verdict = (f"{v:+.1f} days AHEAD of the plan" if v >= 0.05 else
               f"{-v:.1f} days BEHIND the plan" if v <= -0.05 else "exactly on the plan")
    print(f"{plan['game'].upper()} — launch tracker   ({now.strftime('%d %b %Y %H:%M')})")
    print(f"  deadline {plan['deadline']}: {s['days_to_deadline']:.1f} days left · work left "
          f"{s['left_days']:.1f} days · spare {s['spare_days']:.1f} days")
    print(f"  schedule: {verdict} (done {s['earned_days']:.1f} of {s['total_work_days']:.1f} "
          f"work-days, the plan expects {s['planned_days']:.1f} by now)")
    print(f"  launch plan {s['launch_pct']:.1f}% · approved in the last 7 days: {s['approved_7d']}")
    print(f"  the plan says you are in: {names.get(s['current_phase'], '?')}")
    for c in s["categories"]:
        bar = "#" * int(round(c["pct"] / 10)) + "." * (10 - int(round(c["pct"] / 10)))
        wait = c["by_status"]["awaiting"]
        print(f"   {names[c['id']]:<16} {c['pct']:5.1f}%  [{bar}]  {c['approved']}/{c['items']} approved"
              f" · {c['left_days']:.1f} d left" + (f" · {wait} waiting for his verdict" if wait else ""))
    print(f"  page: {PAGE_URL}")


def cmd_find(a):
    items = load_items()
    hits = resolve(items, " ".join(a.words))
    if a.open:
        hits = [i for i in hits if i["status"] in OPEN_STATUSES]
    if a.cat:
        hits = [i for i in hits if i["cat"] == a.cat]
    for i in hits[: a.limit]:
        print(show(i))
    if len(hits) > a.limit:
        print(f"... {len(hits) - a.limit} more (use --limit)")
    if not hits:
        print("no match — try fewer words, or `track.py list --cat <cat>`")


def cmd_list(a):
    items = load_items()
    hits = filtered(items, a.cat, a.group, a.status, a.kind)
    for i in hits:
        print(show(i))
    print(f"({len(hits)} items)")


def cmd_approve(a):
    note = a.note or ""
    check_public(note)
    with locked():
        plan, items = load_json(PLAN, None), load_items()
        now = now_local()
        when = iso(parse_time(a.on)) if a.on else None
        targets = []
        if a.all:
            targets = [i for i in filtered(items, a.cat, a.group, None, a.kind) if i["status"] in OPEN_STATUSES]
            if a.words:
                words = norm(" ".join(a.words)).split()
                targets = [i for i in targets if all(w in norm(i["group"] + " " + i["name"] + " " + i["id"]) for w in words)]
            if not targets:
                die("--all matched no open item")
        else:
            if not a.words:
                die("say what he approved: an id, or words from its name")
            for w in (a.words if a.each else [" ".join(a.words)]):
                hits = resolve(items, w)
                open_hits = [i for i in hits if i["status"] in OPEN_STATUSES]
                if len(hits) == 1:
                    targets.append(hits[0])
                elif len(open_hits) == 1:
                    targets.append(open_hits[0])
                elif not hits:
                    die(f"nothing matches {w!r}. `track.py find <words>` to look it up, or "
                        "`track.py add ...` if it is a new deliverable")
                else:
                    print(f"{w!r} matches {len(hits)} items — name one by its id:", file=sys.stderr)
                    for i in hits[:25]:
                        print("  " + show(i), file=sys.stderr)
                    sys.exit(2)
        changed = []
        op = new_op(now)
        for i in targets:
            if i["status"] == "approved":
                print(f"already approved: {show(i)}")
                continue
            if i["status"] == "removed":
                print(f"skipped (cut from the game): {show(i)}")
                continue
            if a.dry_run:
                print(f"would approve: {show(i)}")
                continue
            change(items, i, "approved", now, "approve", note, by=a.by, approved_at=when, op=op)
            changed.append(i)
        if a.dry_run or not changed:
            return
        save_items(items)
        for i in changed:
            print(f"APPROVED  {show(i)}")
        label = changed[0]["id"] if len(changed) == 1 else f"{len(changed)} items"
        if not a.no_publish:
            publish(f"approve {label}")
    status_line()


def cmd_mark(a):
    if a.as_ not in OPEN_STATUSES:
        die(f"--as must be one of {OPEN_STATUSES} (his yes is `approve`, a cut is `remove`)")
    note = a.note or ""
    check_public(note)
    with locked():
        items = load_items()
        now = now_local()
        hits = resolve(items, " ".join(a.words))
        if len(hits) != 1:
            if not hits:
                die("nothing matches; `track.py find <words>`")
            print("more than one match — name one by its id:", file=sys.stderr)
            for i in hits[:25]:
                print("  " + show(i), file=sys.stderr)
            sys.exit(2)
        i = hits[0]
        if i["status"] == "approved" and not a.force:
            die("it is APPROVED — only he can take that back; use `reopen` with his words")
        change(items, i, a.as_, now, "mark", note, by=a.by)
        save_items(items)
        print(f"marked    {show(i)}")
        if not a.no_publish:
            publish(f"mark {i['id']} {a.as_}")


def cmd_reopen(a):
    note = a.note or ""
    check_public(note)
    with locked():
        items = load_items()
        now = now_local()
        hits = [i for i in resolve(items, " ".join(a.words)) if i["status"] == "approved"]
        if len(hits) != 1:
            die("reopen needs exactly one APPROVED item — name it by its id")
        i = hits[0]
        plan = load_json(PLAN, None)
        was_baseline = bool(i.get("baseline"))
        change(items, i, a.as_ or "awaiting", now, "reopen", note, by=a.by)
        if was_baseline:
            # approved before the tracker began, so it carried no planned days; taken back, it is
            # new work again and adds to the plan like any other added scope
            i["baseline"] = False
            i["days"] = default_days(plan, items, i["cat"])
        save_items(items)
        print(f"reopened  {show(i)}" + (f"  (+{i['days']:.2f} work-days: approved before the tracker began)" if was_baseline else ""))
        if not a.no_publish:
            publish(f"reopen {i['id']}")


def cmd_add(a):
    check_public(a.name, a.group, a.note or "", a.evidence or "")
    with locked():
        plan, items = load_json(PLAN, None), load_items()
        if a.cat not in cat_ids(plan):
            die(f"--cat must be one of {cat_ids(plan)}")
        now = now_local()
        iid = a.id or slug(f"{a.cat}-{a.group}-{a.name}")
        check_public(iid)
        if any(i["id"] == iid for i in items):
            die(f"id {iid!r} exists already: {show(next(i for i in items if i['id'] == iid))}")
        days = a.days if a.days is not None else default_days(plan, items, a.cat)
        item = {"id": iid, "cat": a.cat, "group": a.group, "name": a.name, "kind": a.kind or "task",
                "status": a.status or "todo", "weight": a.weight, "days": round(days, 4),
                "count": a.count, "baseline": False, "approved_at": None, "note": a.note or "",
                "evidence": a.evidence or "", "added_at": iso(now), "updated_at": iso(now)}
        game = a.game or (a.group if re.match(r"^7\.\d+\s", a.group) else None)
        if game:
            item["game"] = game
        items.append(item)
        append_event({"ts": iso(now), "act": "add", "id": iid, "from": None, "to": item["status"],
                      "note": a.note or "", "by": a.by, "days": item["days"]})
        save_items(items)
        print(f"added     {show(item)}  (+{item['days']:.2f} work-days)")
        if not a.no_publish:
            publish(f"add {iid}")


def cmd_remove(a):
    if not a.note:
        die("say why it is cut (--note), in his words")
    check_public(a.note)
    with locked():
        items = load_items()
        now = now_local()
        hits = resolve(items, " ".join(a.words))
        if len(hits) != 1:
            die("remove needs exactly one match — name it by its id")
        i = hits[0]
        change(items, i, "removed", now, "remove", a.note, by=a.by)
        save_items(items)
        print(f"cut       {show(i)}")
        if not a.no_publish:
            publish(f"remove {i['id']}")


def cmd_plan(a):
    with locked():
        plan, items = load_json(PLAN, None), load_items()
        now = now_local()
        msg = []
        if a.deadline:
            dt.date.fromisoformat(a.deadline)
            append_event({"ts": iso(now), "act": "plan", "id": "deadline", "from": plan["deadline"],
                          "to": a.deadline, "note": a.note or "", "by": a.by})
            plan["deadline"] = a.deadline
            msg.append(f"deadline {a.deadline}")
        for spec, kind in ((a.days, "total"), (a.left, "left")):
            if not spec:
                continue
            cat, n = spec[0], float(spec[1])
            if cat not in cat_ids(plan):
                die(f"category must be one of {cat_ids(plan)}")
            c = next(c for c in plan["categories"] if c["id"] == cat)
            target, k = rebalance(plan, items, cat, total=n if kind == "total" else None,
                                  left=n if kind == "left" else None)
            append_event({"ts": iso(now), "act": "plan", "id": cat, "from": c["days"], "to": n,
                          "note": f"{kind} days; " + (a.note or ""), "by": a.by})
            if kind == "total":
                c["days"] = n
            msg.append(f"{cat}: {target:.2f} days over {k} open items")
        if not msg:
            print(json.dumps({c["id"]: c["days"] for c in plan["categories"]}, indent=1))
            print("deadline", plan["deadline"])
            return
        write_json_atomic(PLAN, plan)
        save_items(items)
        print("plan: " + "; ".join(msg))
        if not a.no_publish:
            publish("plan: " + "; ".join(msg))


def cmd_undo(a):
    with locked():
        items = load_items()
        events = load_events()
        undone = {e.get("undoes") for e in events if e["act"] == "undo"}
        undoable = [e for e in events if e["act"] in ("approve", "mark", "reopen", "remove")
                    and e.get("op") and e["op"] not in undone]
        if not undoable:
            die("nothing to undo")
        op = undoable[-1]["op"]
        batch = [e for e in undoable if e["op"] == op]
        now = now_local()
        by_id = {x["id"]: x for x in items}
        for e in reversed(batch):
            i = by_id.get(e["id"])
            if not i:
                continue
            for k, v in e.get("prev", {}).items():
                i[k] = v
            i["updated_at"] = iso(now)
        append_event({"ts": iso(now), "op": new_op(now), "act": "undo", "id": batch[0]["id"],
                      "from": batch[0]["to"], "to": batch[0]["from"], "note": f"undid {batch[0]['act']} of "
                      f"{len(batch)} item(s) from {batch[0]['ts']}", "by": a.by, "undoes": op})
        save_items(items)
        for e in batch:
            print(f"undone    {e['act']} {e['id']} -> {e['from']}")
        if not a.no_publish:
            publish(f"undo {batch[0]['act']} ({len(batch)})")


def cmd_publish(a):
    with locked():
        publish(a.message or ("refresh" if a.if_needed else "publish"), quiet=a.quiet)


def cmd_sync_check(a):
    events = load_events()
    since = a.since
    if not since:
        recs = [e["ts"] for e in events if e["act"] in ("approve", "reopen")]
        since = recs[-1] if recs else "2026-09-27T00:00:00+02:00"
    rx = re.compile(r"verdict|approv|his pick|picked|he picked|great|looks good|we can use", re.I)
    r = subprocess.run(["git", "-C", str(GAME_REPO), "--no-optional-locks", "log", f"--since={since}",
                        "--format=%ad  %s", "--date=format:%Y-%m-%d %H:%M"], capture_output=True, text=True)
    lines = [ln for ln in r.stdout.splitlines() if rx.search(ln)]
    print(f"game commits since {since} that mention a verdict: {len(lines)}")
    for ln in lines:
        print("  " + ln[:160])
    if lines:
        print("For each one: was it HIS yes? If so, `track.py approve <item>` with his words.")


def status_line():
    plan, items = load_json(PLAN, None), load_items()
    s = compute(plan, items, now_local())
    v = s["variance_days"]
    print(f"launch plan {s['launch_pct']:.1f}% · {'ahead' if v >= 0 else 'behind'} {abs(v):.1f} d · "
          f"spare {s['spare_days']:.1f} d before {plan['deadline']}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="track.py", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, publishes=True):
        sp.add_argument("--by", default="agent", help="who records it (agent, albert)")
        if publishes:
            sp.add_argument("--no-publish", action="store_true", help="record only; publish later")

    sp = sub.add_parser("status"); sp.add_argument("--json", action="store_true"); sp.add_argument("--now")
    sp.set_defaults(fn=cmd_status)
    sp = sub.add_parser("find"); sp.add_argument("words", nargs="+"); sp.add_argument("--open", action="store_true")
    sp.add_argument("--cat"); sp.add_argument("--limit", type=int, default=40); sp.set_defaults(fn=cmd_find)
    sp = sub.add_parser("list"); sp.add_argument("--cat"); sp.add_argument("--group"); sp.add_argument("--kind")
    sp.add_argument("--status", help="approved|awaiting|unchecked|pixel|in-progress|todo|removed|open")
    sp.set_defaults(fn=cmd_list)
    sp = sub.add_parser("approve", help="HIS yes"); sp.add_argument("words", nargs="*")
    sp.add_argument("--note", help="his words"); sp.add_argument("--on", help="date/time of his yes if not now")
    sp.add_argument("--all", action="store_true", help="every OPEN item matching --cat/--group/--kind (+words)")
    sp.add_argument("--each", action="store_true", help="treat every word as its own id")
    sp.add_argument("--cat"); sp.add_argument("--group"); sp.add_argument("--kind")
    sp.add_argument("--dry-run", action="store_true"); common(sp); sp.set_defaults(fn=cmd_approve)
    sp = sub.add_parser("mark"); sp.add_argument("words", nargs="+"); sp.add_argument("--as", dest="as_", required=True)
    sp.add_argument("--note"); sp.add_argument("--force", action="store_true"); common(sp); sp.set_defaults(fn=cmd_mark)
    sp = sub.add_parser("reopen"); sp.add_argument("words", nargs="+"); sp.add_argument("--note")
    sp.add_argument("--as", dest="as_"); common(sp); sp.set_defaults(fn=cmd_reopen)
    sp = sub.add_parser("add"); sp.add_argument("--cat", required=True); sp.add_argument("--group", required=True)
    sp.add_argument("--name", required=True); sp.add_argument("--kind"); sp.add_argument("--status", choices=OPEN_STATUSES)
    sp.add_argument("--days", type=float); sp.add_argument("--weight", type=float, default=1.0)
    sp.add_argument("--count", type=int); sp.add_argument("--note"); sp.add_argument("--evidence")
    sp.add_argument("--game", help='the minigame it belongs to, e.g. "7.10 Sumo"')
    sp.add_argument("--id"); common(sp); sp.set_defaults(fn=cmd_add)
    sp = sub.add_parser("remove"); sp.add_argument("words", nargs="+"); sp.add_argument("--note")
    common(sp); sp.set_defaults(fn=cmd_remove)
    sp = sub.add_parser("plan"); sp.add_argument("--days", nargs=2, metavar=("CAT", "N"))
    sp.add_argument("--left", nargs=2, metavar=("CAT", "N")); sp.add_argument("--deadline")
    sp.add_argument("--note"); common(sp); sp.set_defaults(fn=cmd_plan)
    sp = sub.add_parser("undo"); common(sp); sp.set_defaults(fn=cmd_undo)
    sp = sub.add_parser("publish"); sp.add_argument("--if-needed", action="store_true")
    sp.add_argument("--quiet", action="store_true"); sp.add_argument("--message"); sp.set_defaults(fn=cmd_publish)
    sp = sub.add_parser("sync-check"); sp.add_argument("--since"); sp.set_defaults(fn=cmd_sync_check)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
