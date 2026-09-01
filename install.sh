#!/usr/bin/env bash
set -euo pipefail

repo_root=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
skills_root=$repo_root/skills

action=install
requested_count=0
selected_count=0
requested_skills=()
selected_paths=()

usage() {
    echo "usage: ./install.sh [--uninstall] [skill ...]"
}

while [ "$#" -gt 0 ]; do
    case $1 in
        --uninstall)
            action=uninstall
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --)
            shift
            while [ "$#" -gt 0 ]; do
                requested_skills[$requested_count]=$1
                requested_count=$((requested_count + 1))
                shift
            done
            break
            ;;
        -*)
            echo "unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
        *)
            requested_skills[$requested_count]=$1
            requested_count=$((requested_count + 1))
            ;;
    esac
    shift
done

add_selected_skill() {
    candidate=$1

    selected_index=0
    while [ "$selected_index" -lt "$selected_count" ]; do
        if [ "${selected_paths[$selected_index]}" = "$candidate" ]; then
            return
        fi
        selected_index=$((selected_index + 1))
    done

    selected_paths[$selected_count]=$candidate
    selected_count=$((selected_count + 1))
}

if [ "$requested_count" -eq 0 ]; then
    for skill_path in "$skills_root"/*; do
        [ -d "$skill_path" ] || continue
        add_selected_skill "$skill_path"
    done
else
    requested_index=0
    while [ "$requested_index" -lt "$requested_count" ]; do
        skill_name=${requested_skills[$requested_index]}
        case $skill_name in
            ""|.|..|*/*)
                echo "unknown skill: $skill_name" >&2
                usage >&2
                exit 2
                ;;
        esac
        skill_path=$skills_root/$skill_name
        if [ ! -d "$skill_path" ]; then
            echo "unknown skill: $skill_name" >&2
            usage >&2
            exit 2
        fi
        add_selected_skill "$skill_path"
        requested_index=$((requested_index + 1))
    done
fi

if [ "$selected_count" -eq 0 ]; then
    echo "no skills found under $skills_root" >&2
    exit 1
fi

claude_skills_dir=${HANDOFF_CLAUDE_SKILLS_DIR:-"${HOME:?HOME is required when HANDOFF_CLAUDE_SKILLS_DIR is unset}/.claude/skills"}
agents_skills_dir=${HANDOFF_AGENTS_SKILLS_DIR:-"${HOME:?HOME is required when HANDOFF_AGENTS_SKILLS_DIR is unset}/.agents/skills"}
# A skill that ships a command named after itself (skills/<name>/scripts/<name>)
# also gets that command linked onto the operator's PATH, so the commands the
# skills print — `autopilot status`, `tasks list` — work in a plain shell.
bin_dir=${SKILLS_BIN_DIR:-"${HOME:?HOME is required when SKILLS_BIN_DIR is unset}/.local/bin"}

links_created=0
links_correct=0
links_refused=0
links_removed=0
links_absent=0
links_untouched=0

install_link() {
    source_path=$1
    destination_root=$2
    skill_name=${source_path##*/}
    destination=$destination_root/$skill_name

    if [ -L "$destination" ]; then
        if [ "$destination" -ef "$source_path" ]; then
            echo "ALREADY CORRECT: $destination"
            links_correct=$((links_correct + 1))
        else
            echo "REFUSED: $destination is a symlink to another target" >&2
            links_refused=$((links_refused + 1))
        fi
        return
    fi

    if [ -e "$destination" ]; then
        echo "REFUSED: $destination exists and is not a symlink" >&2
        links_refused=$((links_refused + 1))
        return
    fi

    if ! mkdir -p "$destination_root"; then
        echo "REFUSED: could not create parent directory $destination_root" >&2
        links_refused=$((links_refused + 1))
        return
    fi

    if ln -s "$source_path" "$destination"; then
        echo "CREATED: $destination -> $source_path"
        links_created=$((links_created + 1))
    else
        echo "REFUSED: could not create $destination" >&2
        links_refused=$((links_refused + 1))
    fi
}

uninstall_link() {
    source_path=$1
    destination_root=$2
    skill_name=${source_path##*/}
    destination=$destination_root/$skill_name

    if [ -L "$destination" ] && [ "$destination" -ef "$source_path" ]; then
        if rm "$destination"; then
            echo "REMOVED: $destination"
            links_removed=$((links_removed + 1))
        else
            echo "LEFT UNTOUCHED: could not remove $destination" >&2
            links_untouched=$((links_untouched + 1))
        fi
    elif [ -e "$destination" ] || [ -L "$destination" ]; then
        echo "LEFT UNTOUCHED: $destination is not a link owned by this checkout"
        links_untouched=$((links_untouched + 1))
    else
        echo "ALREADY ABSENT: $destination"
        links_absent=$((links_absent + 1))
    fi
}

selected_index=0
while [ "$selected_index" -lt "$selected_count" ]; do
    skill_path=${selected_paths[$selected_index]}
    command_path=$skill_path/scripts/${skill_path##*/}
    if [ "$action" = install ]; then
        install_link "$skill_path" "$claude_skills_dir"
        install_link "$skill_path" "$agents_skills_dir"
        [ -x "$command_path" ] && install_link "$command_path" "$bin_dir"
    else
        uninstall_link "$skill_path" "$claude_skills_dir"
        uninstall_link "$skill_path" "$agents_skills_dir"
        [ -x "$command_path" ] && uninstall_link "$command_path" "$bin_dir"
    fi
    selected_index=$((selected_index + 1))
done

echo
echo "Summary"
printf '  Skills:'
selected_index=0
while [ "$selected_index" -lt "$selected_count" ]; do
    printf ' %s' "${selected_paths[$selected_index]##*/}"
    selected_index=$((selected_index + 1))
done
printf '\n'
if [ "$action" = install ]; then
    echo "  Links created: $links_created"
    echo "  Links already correct: $links_correct"
    echo "  Links refused: $links_refused"
else
    echo "  Links removed: $links_removed"
    echo "  Links already absent: $links_absent"
    echo "  Links left untouched: $links_untouched"
fi
echo "  Commands: $bin_dir"
case ":${PATH:-}:" in
    *":$bin_dir:"*) ;;
    *) [ "$action" = install ] && echo "  NOTE: $bin_dir is not on your PATH; add it so the commands work in a shell" ;;
esac
echo "  Consumer repo setup: $repo_root/docs/INSTALL.md"

if [ "$action" = install ] && [ "$links_refused" -gt 0 ]; then
    exit 1
fi
