#!/usr/bin/env bash
set -euo pipefail

repo_root=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
skills_root=$repo_root/skills
linear_url=https://mcp.linear.app/mcp

action=install
skip_mcp=false
agent_config=false
requested_count=0
selected_count=0
requested_skills=()
selected_paths=()

usage() {
    echo "usage: ./install.sh [--uninstall] [--skip-mcp] [--agent-config] [skill ...]"
    echo "  --agent-config  install config/global-agents.md as the global"
    echo "                  ~/.claude/CLAUDE.md and ~/.codex/AGENTS.md (symlinks);"
    echo "                  with no skill arguments, installs only the config"
}

while [ "$#" -gt 0 ]; do
    case $1 in
        --uninstall)
            action=uninstall
            ;;
        --skip-mcp)
            skip_mcp=true
            ;;
        --agent-config)
            agent_config=true
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

config_source=$repo_root/config/global-agents.md

agent_config_file() {
    destination=$1

    if [ "$action" = uninstall ]; then
        if [ -L "$destination" ] && [ "$destination" -ef "$config_source" ]; then
            if rm "$destination"; then
                echo "REMOVED: $destination"
            else
                echo "LEFT UNTOUCHED: could not remove $destination" >&2
            fi
        elif [ -e "$destination" ] || [ -L "$destination" ]; then
            echo "LEFT UNTOUCHED: $destination is not a link owned by this checkout"
        else
            echo "ALREADY ABSENT: $destination"
        fi
        return
    fi

    if [ -L "$destination" ]; then
        if [ "$destination" -ef "$config_source" ]; then
            echo "ALREADY CORRECT: $destination"
        else
            echo "REFUSED: $destination is a symlink to another target" >&2
        fi
        return
    fi

    if [ -e "$destination" ]; then
        echo "REFUSED: $destination exists and is not a symlink (move it aside first)" >&2
        return
    fi

    destination_root=${destination%/*}
    if ! mkdir -p "$destination_root"; then
        echo "REFUSED: could not create parent directory $destination_root" >&2
        return
    fi

    if ln -s "$config_source" "$destination"; then
        echo "CREATED: $destination -> $config_source"
    else
        echo "REFUSED: could not create $destination" >&2
    fi
}

if $agent_config; then
    if [ ! -f "$config_source" ]; then
        echo "missing $config_source" >&2
        exit 1
    fi
    agent_config_file "${HOME:?HOME is required for --agent-config}/.claude/CLAUDE.md"
    agent_config_file "$HOME/.codex/AGENTS.md"
    if [ "$requested_count" -eq 0 ]; then
        exit 0
    fi
fi

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

tasks_selected=false
selected_index=0
while [ "$selected_index" -lt "$selected_count" ]; do
    if [ "${selected_paths[$selected_index]##*/}" = tasks ]; then
        tasks_selected=true
    fi
    selected_index=$((selected_index + 1))
done

claude_skills_dir=${HANDOFF_CLAUDE_SKILLS_DIR:-"${HOME:?HOME is required when HANDOFF_CLAUDE_SKILLS_DIR is unset}/.claude/skills"}
agents_skills_dir=${HANDOFF_AGENTS_SKILLS_DIR:-"${HOME:?HOME is required when HANDOFF_AGENTS_SKILLS_DIR is unset}/.agents/skills"}

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
    if [ "$action" = install ]; then
        install_link "$skill_path" "$claude_skills_dir"
        install_link "$skill_path" "$agents_skills_dir"
    else
        uninstall_link "$skill_path" "$claude_skills_dir"
        uninstall_link "$skill_path" "$agents_skills_dir"
    fi
    selected_index=$((selected_index + 1))
done

claude_mcp_status="not changed during uninstall"
codex_mcp_status="not changed during uninstall"

configure_claude_mcp() {
    if ! command -v claude >/dev/null 2>&1; then
        claude_mcp_status="skipped (claude CLI not found)"
        echo "NOTICE: claude CLI not found; skipping Linear MCP setup"
    elif claude mcp get linear-server >/dev/null 2>&1; then
        claude_mcp_status="already configured"
        echo "MCP ALREADY CONFIGURED: Claude linear-server"
    elif claude mcp add --scope user --transport http linear-server "$linear_url"; then
        claude_mcp_status="configured"
        echo "MCP CONFIGURED: Claude linear-server"
    else
        claude_mcp_status="not configured (command failed)"
        echo "NOTICE: Claude Linear MCP setup failed; task integration will be unavailable" >&2
    fi
}

configure_codex_mcp() {
    if ! command -v codex >/dev/null 2>&1; then
        codex_mcp_status="skipped (codex CLI not found)"
        echo "NOTICE: codex CLI not found; skipping Linear MCP setup"
    elif codex mcp get linear >/dev/null 2>&1; then
        codex_mcp_status="already configured"
        echo "MCP ALREADY CONFIGURED: Codex linear"
    elif codex mcp add linear --url "$linear_url"; then
        codex_mcp_status="configured"
        echo "MCP CONFIGURED: Codex linear"
    else
        codex_mcp_status="not configured (command failed)"
        echo "NOTICE: Codex Linear MCP setup failed; task integration will be unavailable" >&2
    fi
}

if [ "$action" = install ]; then
    if [ "$tasks_selected" = false ]; then
        claude_mcp_status="not applicable (tasks not selected)"
        codex_mcp_status="not applicable (tasks not selected)"
    elif [ "$skip_mcp" = true ]; then
        claude_mcp_status="skipped (--skip-mcp)"
        codex_mcp_status="skipped (--skip-mcp)"
        echo "NOTICE: Linear MCP setup skipped"
    else
        configure_claude_mcp
        configure_codex_mcp
    fi
fi

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
echo "  MCP (Claude): $claude_mcp_status"
echo "  MCP (Codex): $codex_mcp_status"
echo "  Consumer repo setup: $repo_root/docs/INSTALL.md"

if [ "$action" = install ] && [ "$links_refused" -gt 0 ]; then
    exit 1
fi
