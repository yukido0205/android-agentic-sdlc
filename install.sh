#!/usr/bin/env bash
# install.sh — 1-click installer for android-agentic-sdlc (Antigravity, Gemini CLI, Claude Code)
#
# Usage:
#   ./install.sh --project /path/to/android-app [--target agy|claude|all] [--copy]
#   ./install.sh --global [--target agy|claude|all] [--copy]

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="all"
MODE="symlink"
SCOPE=""
PROJECT_DIR=""

usage() {
  cat <<EOF
Usage:
  ./install.sh --project <path-to-android-repo> [--target agy|claude|all] [--copy]
  ./install.sh --global [--target agy|claude|all] [--copy]

Options:
  --project <dir>   Install into a specific Android project workspace (.agents/ and/or .claude/)
  --global          Install globally (~/.gemini/config/ and/or ~/.claude/)
  --target <name>   Platform: 'agy' (Antigravity & Gemini CLI), 'claude' (Claude Code), or 'all' (default: all)
  --copy            Copy files instead of creating symlinks (default: symlink so 'git pull' auto-updates)
  -h, --help        Show this help message
EOF
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)
      SCOPE="project"
      PROJECT_DIR="${2:-}"
      shift 2
      ;;
    --global)
      SCOPE="global"
      shift
      ;;
    --target)
      TARGET="${2:-all}"
      shift 2
      ;;
    --copy)
      MODE="copy"
      shift
      ;;
    -h|--help)
      usage
      ;;
    *)
      echo "Unknown option: $1"
      usage
      ;;
  esac
done

if [[ -z "$SCOPE" ]]; then
  usage
fi

link_or_copy() {
  local src="$1"
  local dst="$2"
  rm -rf "$dst"
  if [[ "$MODE" == "copy" ]]; then
    cp -R "$src" "$dst"
  else
    ln -s "$src" "$dst"
  fi
}

install_into_dir() {
  local base_dir="$1"
  local include_hooks_json="$2"

  mkdir -p "$base_dir/skills" "$base_dir/rules" "$base_dir/hooks/scripts" "$base_dir/scripts"

  for skill_path in "$REPO_DIR"/skills/*; do
    [[ -d "$skill_path" ]] || continue
    skill_name="$(basename "$skill_path")"
    link_or_copy "$skill_path" "$base_dir/skills/$skill_name"
  done

  link_or_copy "$REPO_DIR/rules/code-hygiene.md" "$base_dir/rules/code-hygiene.md"
  link_or_copy "$REPO_DIR/hooks/scripts/pre-tool-guard.py" "$base_dir/hooks/scripts/pre-tool-guard.py"

  if [[ -f "$REPO_DIR/scripts/init-worktree.sh" ]]; then
    link_or_copy "$REPO_DIR/scripts/init-worktree.sh" "$base_dir/scripts/init-worktree.sh"
    link_or_copy "$REPO_DIR/scripts/init_worktree.py" "$base_dir/scripts/init_worktree.py"
  fi

  if [[ "$include_hooks_json" == "true" ]]; then
    link_or_copy "$REPO_DIR/hooks/hooks.json" "$base_dir/hooks.json"
  fi
}

if [[ "$SCOPE" == "project" ]]; then
  if [[ -z "$PROJECT_DIR" || ! -d "$PROJECT_DIR" ]]; then
    echo "Error: Project directory '$PROJECT_DIR' does not exist."
    exit 1
  fi
  PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"

  if [[ "$TARGET" == "agy" || "$TARGET" == "all" ]]; then
    install_into_dir "$PROJECT_DIR/.agents" "true"
    echo "✅ Installed for Antigravity & Gemini CLI -> $PROJECT_DIR/.agents/ ($MODE)"
  fi

  if [[ "$TARGET" == "claude" || "$TARGET" == "all" ]]; then
    install_into_dir "$PROJECT_DIR/.claude" "false"
    echo "✅ Installed for Claude Code              -> $PROJECT_DIR/.claude/ ($MODE)"
  fi

  mkdir -p "$PROJECT_DIR/scripts"
  link_or_copy "$REPO_DIR/scripts/init-worktree.sh" "$PROJECT_DIR/scripts/init-worktree.sh"
  link_or_copy "$REPO_DIR/scripts/init_worktree.py" "$PROJECT_DIR/scripts/init_worktree.py"
  echo "✅ Installed Worktree Initializer         -> $PROJECT_DIR/scripts/init-worktree.sh ($MODE)"
elif [[ "$SCOPE" == "global" ]]; then
  if [[ "$TARGET" == "agy" || "$TARGET" == "all" ]]; then
    install_into_dir "$HOME/.gemini/config" "true"
    echo "✅ Installed globally for Antigravity & Gemini CLI -> $HOME/.gemini/config/ ($MODE)"
  fi

  if [[ "$TARGET" == "claude" || "$TARGET" == "all" ]]; then
    install_into_dir "$HOME/.claude" "false"
    echo "✅ Installed globally for Claude Code              -> $HOME/.claude/ ($MODE)"
  fi
fi
