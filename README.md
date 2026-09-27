# Party Ratz 4 Life — launch tracker

A live page that shows how far the game is from its **23 November 2026** launch: what Albert has
approved, what is left, and whether the schedule holds.

**Page:** https://tastybebe.github.io/partyratz-tracker/

## What it shows

- **Ahead or behind** — work-days earned by his approvals against the plan, in days.
- **Spare days** — days left to the deadline minus the work left.
- **Progress by area** — primary art, secondary art, mechanics, music, sound effects, game feel,
  playtesting, marketing; each area by game or group.
- **Timeline** — his estimates laid end to end, today and the deadline marked.
- **Work done vs. the plan** — the burn-up chart, with a table view.
- **Minigames** — every game's mechanics and how much of its art is approved.
- **Latest approvals** and **every item**, searchable.

## The rules

1. **Only Albert's own yes completes an item.** Something an agent made, fixed or finished is
   "waiting for your verdict" until he says so. Art an agent generated that he has not checked counts
   as not done.
2. **The days are his estimates** (27 Sep 2026): primary art 1, secondary art 20, mechanics 5,
   music 5, sound effects 3, game feel 5, playtesting 3, marketing 10 — 52 work-days. Each open item
   carries its share of its area's days and earns them the moment he approves it.
3. **The plan is one work-day per calendar day** from the start, in his order. Ahead/behind is work
   done minus days elapsed. New work added later carries its own days, so it pushes the finish out
   instead of hiding.
4. **The page is public.** Names, numbers and dates only — no art, no links, no file paths, and the
   rats by their colour. `track.py` refuses anything else.

## Recording an approval

Every change goes through one command, which records it, rebuilds `data/tracker.json` and pushes;
the page picks it up about a minute later.

```bash
python3 track.py approve "sumo ring" --note "looks great"
python3 track.py approve --all --group "7.10 Sumo" --cat art-secondary --note "all of these are good"
python3 track.py mark tail --as awaiting          # made, waiting for his eye
python3 track.py reopen <id> --note "redo it"     # he took it back
python3 track.py add --cat music --group Music --name "Sudden death sting"
python3 track.py remove <id> --note "cut"
python3 track.py plan --days music 6              # his new estimate
python3 track.py undo
python3 track.py status
```

The developer agent in the game project is reminded on every prompt (a hook), and the game's
`CLAUDE.md` carries the law. A launchd job re-pushes anything a failed push left behind.

## Layout

| path | what |
|---|---|
| `track.py` | the only writer of the data; also the numbers (`compute`) |
| `tracker/plan.json` | deadline, start, his estimates by area |
| `tracker/items.json` | every deliverable and its status |
| `tracker/events.jsonl` | append-only history of every change |
| `data/tracker.json` | what the page reads (rebuilt by `track.py`) |
| `index.html`, `assets/` | the page; `assets/stats.js` recomputes every number independently |
| `tests/` | `test_parity.py` (tool vs page agree), `test_cli.py` (every command) |
| `ops/` | the prompt hook and the launchd job, as installed |
