#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "usage: stamp.sh <handoff-dir> [name=value ...]" >&2
}

if [ "$#" -lt 1 ]; then
    usage
    exit 2
fi

handoff_dir=$1
shift

if [ ! -d "$handoff_dir" ]; then
    echo "stamp.sh: handoff directory does not exist: $handoff_dir" >&2
    exit 2
fi

for input in "$@"; do
    case $input in
        *=*) ;;
        *)
            echo "stamp.sh: extra input must be name=value: $input" >&2
            exit 2
            ;;
    esac

    name=${input%%=*}
    case $name in
        ""|subject|*[!A-Za-z0-9_.-]*)
            echo "stamp.sh: invalid or reserved input name: $name" >&2
            exit 2
            ;;
    esac
    case $input in
        *"
"*)
            echo "stamp.sh: extra inputs must not contain newlines" >&2
            exit 2
            ;;
    esac
done

if [ "$#" -gt 1 ]; then
    duplicate_name=$(
        printf '%s\n' "$@" |
            sed 's/=.*//' |
            LC_ALL=C sort |
            uniq -d |
            sed -n '1p'
    )
    if [ -n "$duplicate_name" ]; then
        echo "stamp.sh: duplicate input name: $duplicate_name" >&2
        exit 2
    fi
fi

script_dir=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
subject_oid=$("$script_dir/subject-rev.sh" HEAD)

handoff_dir_abs=$(CDPATH= cd -- "$handoff_dir" && pwd -P)
destination=$handoff_dir_abs/freshness

umask 077
temporary=$(mktemp "$handoff_dir_abs/.handoff-freshness.XXXXXX")
trap 'rm -f "$temporary"' EXIT HUP INT TERM

{
    printf 'subject=%s\n' "$subject_oid"
    if [ "$#" -gt 0 ]; then
        printf '%s\n' "$@" | LC_ALL=C sort
    fi
} >"$temporary"

mv "$temporary" "$destination"
trap - EXIT HUP INT TERM

printf '%s\n' "$destination"
