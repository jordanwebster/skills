#!/usr/bin/env bash
set -euo pipefail

test_dir=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(CDPATH= cd -- "$test_dir/.." && pwd)
# shellcheck source=tests/lib.sh
. "$test_dir/lib.sh"

scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT HUP INT TERM
test_home=$scratch/home
mkdir "$test_home"

skill_count=0
for skill_path in "$repo_root"/skills/*; do
    [ -d "$skill_path" ] || continue
    skill_count=$((skill_count + 1))
done
[ "$skill_count" -ge 3 ] || fail "installer test requires all three repository skills"
[ -d "$repo_root/skills/handoff" ] || fail "installer test requires the handoff skill"
[ -d "$repo_root/skills/scaffold" ] || fail "installer test requires the scaffold skill"
[ -d "$repo_root/skills/tasks" ] || fail "installer test requires the tasks skill"

run_installer() {
    claude_dir=$1
    agents_dir=$2
    shift 2
    HOME="$test_home" \
        HANDOFF_CLAUDE_SKILLS_DIR="$claude_dir" \
        HANDOFF_AGENTS_SKILLS_DIR="$agents_dir" \
        "$repo_root/install.sh" "$@"
}

assert_skill_link() {
    destination_root=$1
    skill_name=$2
    destination=$destination_root/$skill_name
    source_path=$repo_root/skills/$skill_name

    [ -L "$destination" ] || fail "$destination must be a symlink"
    [ "$destination" -ef "$source_path" ] || fail "$destination must resolve to its repository skill"
    if [ -d "$source_path/scripts" ]; then
        [ -d "$destination/scripts" ] || fail "$destination/scripts must resolve to a directory"
        [ ! -L "$destination/scripts" ] || fail "$destination/scripts must be bundled in the skill"
        for script_path in "$source_path"/scripts/*; do
            [ -f "$script_path" ] || continue
            [ -f "$destination/scripts/${script_path##*/}" ] || \
                fail "$destination/scripts/${script_path##*/} must resolve to a file"
        done
    fi
}

assert_all_links() {
    claude_dir=$1
    agents_dir=$2
    for skill_path in "$repo_root"/skills/*; do
        [ -d "$skill_path" ] || continue
        skill_name=${skill_path##*/}
        assert_skill_link "$claude_dir" "$skill_name"
        assert_skill_link "$agents_dir" "$skill_name"
    done
}

fresh_claude=$scratch/fresh/claude-skills
fresh_agents=$scratch/fresh/agents-skills
fresh_output=$(run_installer "$fresh_claude" "$fresh_agents" --skip-mcp)
assert_all_links "$fresh_claude" "$fresh_agents"
expected_link_total=$((skill_count * 2))
printf '%s\n' "$fresh_output" | grep -q "Links created: $expected_link_total" || \
    fail "fresh install summary must count every created link"
printf '%s\n' "$fresh_output" | grep -q 'MCP (Claude): skipped (--skip-mcp)' || \
    fail "fresh install summary must report skipped MCP setup"

second_output=$(run_installer "$fresh_claude" "$fresh_agents" --skip-mcp)
assert_all_links "$fresh_claude" "$fresh_agents"
printf '%s\n' "$second_output" | grep -q 'Links created: 0' || \
    fail "idempotent install must not recreate links"
printf '%s\n' "$second_output" | grep -q "Links already correct: $expected_link_total" || \
    fail "idempotent install must count every correct link"

selective_claude=$scratch/selective/claude-skills
selective_agents=$scratch/selective/agents-skills
selective_output=$(run_installer "$selective_claude" "$selective_agents" handoff)
assert_skill_link "$selective_claude" handoff
assert_skill_link "$selective_agents" handoff
for skill_path in "$repo_root"/skills/*; do
    [ -d "$skill_path" ] || continue
    skill_name=${skill_path##*/}
    [ "$skill_name" = handoff ] && continue
    [ ! -e "$selective_claude/$skill_name" ] && [ ! -L "$selective_claude/$skill_name" ] || \
        fail "selective install must not link $skill_name for Claude"
    [ ! -e "$selective_agents/$skill_name" ] && [ ! -L "$selective_agents/$skill_name" ] || \
        fail "selective install must not link $skill_name for Codex"
done
printf '%s\n' "$selective_output" | grep -q 'Skills: handoff' || \
    fail "selective install summary must name handoff"
printf '%s\n' "$selective_output" | grep -q 'Links created: 2' || \
    fail "selective install must create one link per harness"
printf '%s\n' "$selective_output" | grep -q 'MCP (Claude): not applicable (tasks not selected)' || \
    fail "installing handoff alone must not configure Linear MCP"

scaffold_claude=$scratch/scaffold/claude-skills
scaffold_agents=$scratch/scaffold/agents-skills
scaffold_install_output=$(run_installer "$scaffold_claude" "$scaffold_agents" scaffold)
assert_skill_link "$scaffold_claude" scaffold
assert_skill_link "$scaffold_agents" scaffold
printf '%s\n' "$scaffold_install_output" | grep -q 'Skills: scaffold' || \
    fail "selective install summary must name scaffold"
printf '%s\n' "$scaffold_install_output" | grep -q 'Links created: 2' || \
    fail "selective scaffold install must create one link per harness"
printf '%s\n' "$scaffold_install_output" | \
    grep -q 'MCP (Claude): not applicable (tasks not selected)' || \
    fail "installing scaffold alone must not configure Linear MCP"

scaffold_uninstall_output=$(
    run_installer "$scaffold_claude" "$scaffold_agents" --uninstall scaffold
)
printf '%s\n' "$scaffold_uninstall_output" | grep -q 'Skills: scaffold' || \
    fail "selective uninstall summary must name scaffold"
printf '%s\n' "$scaffold_uninstall_output" | grep -q 'Links removed: 2' || \
    fail "selective scaffold uninstall must remove one link per harness"
[ ! -e "$scaffold_claude/scaffold" ] && [ ! -L "$scaffold_claude/scaffold" ] || \
    fail "selective scaffold uninstall must remove the Claude link"
[ ! -e "$scaffold_agents/scaffold" ] && [ ! -L "$scaffold_agents/scaffold" ] || \
    fail "selective scaffold uninstall must remove the Codex link"

conflict_claude=$scratch/conflict/claude-skills
conflict_agents=$scratch/conflict/agents-skills
mkdir -p "$conflict_agents"
foreign_path=$conflict_agents/handoff
printf 'foreign content\n' >"$foreign_path"

set +e
conflict_output=$(run_installer "$conflict_claude" "$conflict_agents" --skip-mcp 2>&1)
conflict_status=$?
set -e
[ "$conflict_status" -ne 0 ] || fail "a foreign destination must make install exit non-zero"
assert_eq "foreign content" "$(cat "$foreign_path")" "a foreign destination must remain untouched"
printf '%s\n' "$conflict_output" | grep -q "REFUSED: $foreign_path exists and is not a symlink" || \
    fail "a foreign destination must be reported"
printf '%s\n' "$conflict_output" | grep -q 'Links refused: 1' || \
    fail "conflict summary must count the refusal"

for skill_path in "$repo_root"/skills/*; do
    [ -d "$skill_path" ] || continue
    skill_name=${skill_path##*/}
    assert_skill_link "$conflict_claude" "$skill_name"
    if [ "$skill_name" != handoff ]; then
        assert_skill_link "$conflict_agents" "$skill_name"
    fi
done

uninstall_claude=$scratch/uninstall/claude-skills
uninstall_agents=$scratch/uninstall/agents-skills
run_installer "$uninstall_claude" "$uninstall_agents" --skip-mcp >/dev/null
foreign_target=$scratch/foreign-tasks
mkdir "$foreign_target"
rm "$uninstall_agents/tasks"
ln -s "$foreign_target" "$uninstall_agents/tasks"

uninstall_output=$(run_installer "$uninstall_claude" "$uninstall_agents" --uninstall)
printf '%s\n' "$uninstall_output" | grep -q 'Links left untouched: 1' || \
    fail "uninstall summary must count the foreign link"
[ -L "$uninstall_agents/tasks" ] || fail "uninstall must leave the foreign tasks link"
[ "$uninstall_agents/tasks" -ef "$foreign_target" ] || \
    fail "uninstall must not retarget the foreign tasks link"

for skill_path in "$repo_root"/skills/*; do
    [ -d "$skill_path" ] || continue
    skill_name=${skill_path##*/}
    [ ! -e "$uninstall_claude/$skill_name" ] && [ ! -L "$uninstall_claude/$skill_name" ] || \
        fail "uninstall must remove $uninstall_claude/$skill_name"
    if [ "$skill_name" != tasks ]; then
        [ ! -e "$uninstall_agents/$skill_name" ] && [ ! -L "$uninstall_agents/$skill_name" ] || \
            fail "uninstall must remove $uninstall_agents/$skill_name"
    fi
done

assert_eq "foreign content" "$(cat "$foreign_path")" \
    "a refused foreign destination must remain untouched"

echo "ok - installer"
