#!/usr/bin/env bash
# Launch a long-running ForgeCompile job on the server, safely.
#
#   scripts/server/launch.sh <session-name> <command...>
#
# 1. Refuses to start if a tmux session with that name already runs (no duplicates).
# 2. Runs the resource check (scripts/resources.py); refuses if memory is short.
# 3. Records the git commit; refuses on a dirty tree (results must map to a commit).
# 4. Starts the command in a detached tmux session, so it survives SSH disconnects,
#    logging continuously to ~/forge_logs/<session>.log and appending EXIT=<status>.
set -euo pipefail
cd "$(dirname "$0")/../.."

if [ $# -lt 2 ]; then
    echo "usage: $0 <session-name> <command...>" >&2
    exit 2
fi
session="$1"; shift
log_dir="$HOME/forge_logs"
log="$log_dir/$session.log"
mkdir -p "$log_dir"

if tmux has-session -t "$session" 2>/dev/null; then
    echo "tmux session '$session' already exists; not starting a duplicate" >&2
    exit 1
fi
if [ -n "$(git status --porcelain)" ]; then
    echo "working tree is dirty; commit or stash first so results map to a commit" >&2
    exit 1
fi
uv run --locked python scripts/resources.py

{
    echo "=== $session started $(date -u +%Y-%m-%dT%H:%M:%SZ) commit $(git rev-parse HEAD)"
    echo "=== command: $*"
} > "$log"
quoted=$(printf '%q ' "$@")
tmux new-session -d -s "$session" "cd '$PWD' && $quoted >> '$log' 2>&1; echo EXIT=\$? >> '$log'"
echo "started tmux session '$session'; log: $log"
