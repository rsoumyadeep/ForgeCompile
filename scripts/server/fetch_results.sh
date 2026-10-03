#!/usr/bin/env bash
# Copy an experiment's curated results from the server clone into this checkout (laptop side).
#
#   scripts/server/fetch_results.sh <EXP-directory-name> [ssh-host]
#   e.g. scripts/server/fetch_results.sh EXP-009-ml-ablations
#
# Copies every file the server's experiment directory has but git does not track there yet
# (curated results, checkpoints), never the run script itself. Afterwards: review, commit,
# push; then on the server `git clean -f -- experiments/<EXP>` and `git pull` so both sides
# hold the committed copy (the server is never the source of truth, D-034).
# The ssh host defaults to the alias "forgeserver" (configure it in ~/.ssh/config).
set -euo pipefail
cd "$(dirname "$0")/../.."

if [ $# -lt 1 ]; then
    echo "usage: $0 <EXP-directory-name> [ssh-host]" >&2
    exit 2
fi
exp="$1"
host="${2:-forgeserver}"
remote_dir="ForgeCompile/experiments/$exp"

files=$(ssh -o BatchMode=yes "$host" \
    "cd $remote_dir && git ls-files --others --exclude-standard . | grep -v '^run.py$'" || true)
if [ -z "$files" ]; then
    echo "no new curated files in $remote_dir" >&2
    exit 1
fi
for f in $files; do
    mkdir -p "experiments/$exp/$(dirname "$f")"
    scp -q -o BatchMode=yes "$host:$remote_dir/$f" "experiments/$exp/$f"
    echo "fetched experiments/$exp/$f"
done
