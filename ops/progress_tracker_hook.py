#!/usr/bin/env python3
"""THE LAUNCH TRACKER'S REMINDER, INJECTED ON EVERY PROMPT (Albert, 2026-09-27).

His words: *"whenever I approve something with the agent developer, it should be marked as
completed ... make sure that whenever I truly approve something, it gets marked in the
tracker as approved."* A law in CLAUDE.md is read once, at session start; an approval
arrives in the middle of a session, mid-task, in a sentence about something else. So the
reminder rides on every prompt, like the 2d-games router does.

Fires only in a project whose CLAUDE.md names the tracker (walking up from the cwd), so no
other project pays for it. Prints nothing and exits 0 on any failure — a broken hook must
never block a prompt. Installed copy: ~/.claude/hooks/progress_tracker_hook.py; the source
lives in the tracker's repository (ops/).
"""
import json
import os
import re
import sys

MARK = "partyratz-tracker"
TOOL = "python3 ~/Gamesky/partyratz-tracker/track.py"
PAGE = "https://tastybebe.github.io/partyratz-tracker/"
# Words that often carry his verdict (English and Czech). Only used to make the reminder
# louder; it prints either way, because he approves in many other words too.
VERDICT = re.compile(
    r"\b(approv\w*|great|perfect|awesome|amazing|love (it|this|these|them)|looks? (good|great|fine|nice|amazing)|"
    r"(we|you) can use|go with|keep (it|this|that|them)|i (pick|picked|choose|chose|like)|number (one|two|three|four|five|\d+)|"
    r"that'?s (it|good|great|fine)|good job|well done|nice|super|paráda|parada|schvaluj\w*|dobr[ýy]|skvěl\w*|skvel\w*)\b",
    re.I)


def project_has_tracker(cwd):
    d = os.path.abspath(cwd or os.getcwd())
    for _ in range(7):
        p = os.path.join(d, "CLAUDE.md")
        try:
            if os.path.isfile(p):
                with open(p, encoding="utf-8", errors="ignore") as f:
                    if MARK in f.read():
                        return True
        except OSError:
            pass
        nd = os.path.dirname(d)
        if nd == d:
            break
        d = nd
    return False


def main():
    try:
        raw = sys.stdin.read() if not sys.stdin.isatty() else ""
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        data = {}
    cwd = data.get("cwd") or os.getcwd()
    if not project_has_tracker(cwd):
        return
    prompt = data.get("prompt") or ""
    loud = bool(VERDICT.search(prompt))
    lines = ["[progress tracker] Albert's launch tracker is live: " + PAGE]
    if loud:
        lines.append("  THIS MESSAGE MAY CARRY HIS VERDICT. If he approved anything in it, record it THIS turn:")
    else:
        lines.append("  If this message approves anything (his verdict, a pick, \"great\", \"we can use these\"), record it THIS turn:")
    lines.append(f"    {TOOL} approve \"<id or words from its name>\" --note \"<his words>\"   (a whole batch: approve --all --group \"7.10 Sumo\" --cat art-secondary)")
    lines.append(f"  Look up: {TOOL} find <words> · new deliverable: add · cut: remove · he changed an estimate: plan --days <cat> <n> · mistake: undo")
    lines.append("  Only HIS yes approves. Your own finished work waiting for his eye is `mark <id> --as awaiting`. Rats by colour only, no links or paths (the page is public).")
    print("\n".join(lines))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
