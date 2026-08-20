#!/usr/bin/env bash
set -euo pipefail

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

assert_eq() {
    expected=$1
    actual=$2
    message=$3
    if [ "$expected" != "$actual" ]; then
        echo "FAIL: $message" >&2
        echo "  expected: $expected" >&2
        echo "  actual:   $actual" >&2
        exit 1
    fi
}

assert_ne() {
    unexpected=$1
    actual=$2
    message=$3
    if [ "$unexpected" = "$actual" ]; then
        echo "FAIL: $message" >&2
        echo "  unexpected: $unexpected" >&2
        exit 1
    fi
}

new_fixture_repo() {
    fixture_path=$1
    git init -q -b main "$fixture_path"
    git -C "$fixture_path" config user.name "Handoff Tests"
    git -C "$fixture_path" config user.email "handoff@example.invalid"
    printf 'base\n' >"$fixture_path/app.txt"
    git -C "$fixture_path" add app.txt
    git -C "$fixture_path" commit -q -m "base subject"
}
