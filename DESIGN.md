# Launch tracker — design (2026-09-27)

**This file is DESIGN.** What the tracker is, why it is built this way, and the decisions Albert made.

## The ask, in his words (2026-09-27)

*"Create like a tracker ... where I can track my progress ... set deadlines ... my deadline when the
game should be finished is twenty third of November ... whenever I approve something with the agent
developer, it should be marked as completed and the percentage of the completion should increase ...
how far behind or ahead I am of the schedule ... available on all devices ... truly live ... make sure
that the timeline on the tracker actually makes sense ... don't disrupt the other agent."*

## His decisions

| question | his answer |
|---|---|
| where it lives | a **public link** (GitHub Pages, like his other apps); it shows names, numbers and dates, no art |
| primary art | **1 day** (about 90% done) |
| secondary art | **20 days** (about 30% approved; 99% generated) |
| mechanics | **5 days** (99% done) |
| music | **5 days**, ~30 tracks, none done |
| sound effects | **3 days of their own**, after music |
| game feel | **5 days** |
| playtesting | **3 days** |
| marketing | **10 days, finished before 23 Nov** |
| order | art first (he is on sprites, animation, backgrounds now), then mechanics, music, sound effects, game feel, playtesting, marketing |

52 work-days against the 57-odd days from the start to the end of 23 November. He works every day of
the week (the game's commit history has work on all seven), so the plan is one work-day per calendar day.

## The model

- **An item** is one deliverable a person would review: a drawing, an animation clip, a track, a sound
  family, a bug, a store asset. It has an area (category), a group (a minigame, "Lobby", "UI: icons"),
  a status and a share of its area's days.
- **Statuses:** approved (his yes) · waiting for his verdict · made, not checked · still old pixel art ·
  in progress · to do · cut. Only *approved* completes.
- **Days:** his estimate for an area is spread over the area's open items by weight at the start.
  Items approved before the start are the *baseline*: they count toward the area's percentage but carry
  no days (they are not remaining work). Items added later carry their own days (the area's average
  unless stated), so scope growth pushes the finish out.
- **Percent per area:** approved weight ÷ all weight — except mechanics, whose items only cover what is
  left, so it starts at his 99% and climbs with the remaining days approved.
- **The plan:** one work-day per calendar day from the start. By any moment it expects
  `min(days elapsed, total work)` done. **Ahead/behind** = done − that. **Spare days** = days to the
  deadline − work left. The timeline lays the areas end to end in his order.
- **Baseline honesty:** at the start, things already in the game with nothing open and built to his
  picks were counted as done; things an agent picked or generated that he never judged were not.

## Architecture

```
dev session (game repo) --approve--> track.py --writes--> tracker/items.json, events.jsonl
                                         |--rebuilds--> data/tracker.json --git push--> GitHub Pages
phone / laptop: index.html --fetch every 60 s--> data/tracker.json --stats.js recomputes--> page
```

- **track.py** is the only writer; one file lock so two sessions (or both Claude accounts) never clash.
- **The page recomputes every number** (`assets/stats.js`) instead of trusting the file, so time moves
  on the page even when the data does not; `tests/test_parity.py` diffs the two implementations.
- **Live:** every change pushes at once; GitHub Pages redeploys in about a minute; the page polls every
  60 s and on focus. A launchd job re-pushes every 15 minutes if a push failed. It never commits noise:
  the data is rewritten only when something real changed.
- **The dev agent is told** by a line in the game's `CLAUDE.md` (the law) and a prompt hook that prints
  the one command on every message in that project, louder when the message sounds like a verdict.
- **Nothing touches the game repo** except that law line. The tracker reads nothing from it at runtime;
  `sync-check` reads its git log (no locks) to list commits that mention a verdict.

## Privacy (the page is public)

No art, no links, no file paths, no e-mail, no account names, and the rats only by their colour (his naming
ruling of 2026-09-20). `track.py` refuses any stored text that breaks this. Each item's evidence and
the audit's notes stay on this Mac (`tracker/private.json`, never committed); the repository and the page carry
names, statuses, days and dates only.

## Out of scope

Editing items from the page (it is a read-only viewer; changes go through the agent), art thumbnails
(he chose names and numbers only), per-hour time tracking.
