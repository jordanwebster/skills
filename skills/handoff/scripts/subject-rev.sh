#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "usage: subject-rev.sh [<commit>]" >&2
}

if [ "$#" -gt 1 ]; then
    usage
    exit 2
fi

if ! git rev-parse --git-dir >/dev/null 2>&1; then
    echo "subject-rev.sh: not inside a git repository" >&2
    exit 2
fi

ref=${1:-HEAD}
if ! commit_oid=$(git rev-parse --verify "${ref}^{commit}" 2>/dev/null); then
    echo "subject-rev.sh: not a commit: $ref" >&2
    exit 2
fi

without_handoffs() {
    tab=$(printf '\t')
    while IFS= read -r entry; do
        case $entry in
            *"${tab}handoffs") ;;
            *) printf '%s\n' "$entry" ;;
        esac
    done
}

# Digest the filtered listing instead of building a tree object: the
# subject is only ever compared for equality, and hash-object without -w
# writes nothing, so this works in sandboxes that forbid touching .git.
if ! subject_oid=$(git ls-tree "${commit_oid}^{tree}" | without_handoffs | git hash-object --stdin); then
    echo "subject-rev.sh: could not construct subject revision for $ref" >&2
    exit 1
fi

printf '%s\n' "$subject_oid"
