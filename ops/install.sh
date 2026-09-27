#!/bin/bash
# Installs the tracker's two pieces of machinery on this Mac (safe to run again):
#   1. the launchd job that re-pushes anything a failed push left behind (every 15 minutes)
#   2. the prompt hook that reminds the developer agent to record his approvals
# The hook is registered in ~/.claude/settings.json separately (see README).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
LABEL=com.tastybebe.partyratz-tracker
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs" "$HOME/.claude/hooks"
sed "s#__HOME__#$HOME#g" "$HERE/$LABEL.plist" > "$PLIST"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
cp "$HERE/progress_tracker_hook.py" "$HOME/.claude/hooks/progress_tracker_hook.py"
chmod +x "$HOME/.claude/hooks/progress_tracker_hook.py"
echo "installed: $PLIST and ~/.claude/hooks/progress_tracker_hook.py"
