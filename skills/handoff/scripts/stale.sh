#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "usage: stale.sh <handoff-dir>" >&2
}

if [ "$#" -ne 1 ]; then
    usage
    exit 2
fi

handoff_dir=$1
if [ ! -d "$handoff_dir" ]; then
    echo "stale.sh: handoff directory does not exist: $handoff_dir" >&2
    exit 2
fi

if ! git rev-parse --git-dir >/dev/null 2>&1; then
    echo "stale.sh: not inside a git repository" >&2
    exit 2
fi

script_dir=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
current_subject=$("$script_dir/subject-rev.sh" HEAD)

record=$handoff_dir/freshness
if [ ! -f "$record" ]; then
    printf 'missing %s\n' "$record"
    exit 1
fi

first_line=
IFS= read -r first_line <"$record" || true
record_subject=
case $first_line in
    subject=*) record_subject=${first_line#subject=} ;;
esac

extras=$(sed -n '2,$p' "$record" | tr '\n' ' ' | sed 's/ $//')

if [ "$record_subject" = "$current_subject" ]; then
    freshness=fresh
    result=0
else
    freshness=stale
    result=1
fi

if [ -n "$extras" ]; then
    printf '%s %s %s\n' "$freshness" "$handoff_dir" "$extras"
else
    printf '%s %s\n' "$freshness" "$handoff_dir"
fi

exit "$result"
