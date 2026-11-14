#!/usr/bin/env bash
# scripts/init-worktree.sh — Zero-Token Android Worktree Initializer
#
# Creates an isolated git worktree for parallel agent sessions (.worktrees/<TICKET>),
# symlinks vital Android/Agent gitignored files (local.properties, keystore.properties,
# google-services.json, .agents/, .claude/), and sets org.gradle.workers.max=2
# to prevent Mac RAM exhaustion.
#
# Usage:
#   ./scripts/init-worktree.sh <TICKET> [--branch <name>] [--from <ref>] [--workers <N>]
#

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "$REPO_ROOT" ]]; then
  echo "❌ Error: Must be executed inside a git repository."
  exit 1
fi

# If inside an existing worktree, resolve canonical main repository root
COMMON_DIR="$(git rev-parse --git-common-dir 2>/dev/null || true)"
if [[ -n "$COMMON_DIR" && "$COMMON_DIR" != ".git" ]]; then
  REPO_ROOT="$(cd "$COMMON_DIR/.." && pwd)"
fi

TICKET=""
BRANCH=""
BASE_REF="HEAD"
WORKERS=2
CUSTOM_DIR=""

usage() {
  local code="${1:-0}"
  cat <<EOF
Zero-Token Android Worktree Initializer for Parallel Agent Sessions

Usage:
  ./scripts/init-worktree.sh <TICKET> [options]

Arguments:
  <TICKET>               Ticket/feature identifier (e.g. PAY-101, PROJ-123, BUG-404)

Options:
  -b, --branch <name>    Custom branch name (default: feature/<TICKET> or fix/<TICKET>)
  --from <ref>           Base branch or commit reference (default: HEAD)
  --workers <N>          Limit Gradle max-workers to avoid RAM exhaustion (default: 2)
  --dir <path>           Custom worktree destination directory
  -h, --help             Show this help message
EOF
  exit "$code"
}

if [[ $# -eq 0 ]]; then
  usage 1
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage 0
      ;;
    -b|--branch)
      BRANCH="${2:-}"
      shift 2
      ;;
    --from)
      BASE_REF="${2:-HEAD}"
      shift 2
      ;;
    --workers)
      WORKERS="${2:-2}"
      shift 2
      ;;
    --dir)
      CUSTOM_DIR="${2:-}"
      shift 2
      ;;
    -*)
      echo "Unknown option: $1"
      usage
      ;;
    *)
      if [[ -z "$TICKET" ]]; then
        TICKET="$1"
        shift
      else
        echo "Unexpected argument: $1"
        usage
      fi
      ;;
  esac
done

if [[ -z "$TICKET" ]]; then
  echo "❌ Error: Missing ticket identifier."
  usage
fi

# Normalize branch name if not explicitly provided
if [[ -z "$BRANCH" ]]; then
  TICKET_UPPER="$(echo "$TICKET" | tr '[:lower:]' '[:upper:]')"
  if [[ "$TICKET_UPPER" =~ ^(BUG|FIX) ]]; then
    BRANCH="fix/$TICKET"
  else
    BRANCH="feature/$TICKET"
  fi
fi

WORKTREE_DIR="${CUSTOM_DIR:-$REPO_ROOT/.worktrees/$TICKET}"

echo "======================================================================"
echo "🚀 Initializing Android Worktree for [$TICKET]..."
echo "======================================================================"

# 1. Ensure .worktrees/ is in .gitignore
GITIGNORE="$REPO_ROOT/.gitignore"
if [[ -f "$GITIGNORE" ]]; then
  if ! grep -q "^\.worktrees" "$GITIGNORE"; then
    echo -e "\n# Git worktrees for parallel agent sessions\n.worktrees/" >> "$GITIGNORE"
    echo "📝 Added .worktrees/ to .gitignore"
  fi
else
  echo -e "# Git worktrees for parallel agent sessions\n.worktrees/" > "$GITIGNORE"
  echo "📝 Created .gitignore with .worktrees/"
fi

# 2. Create git worktree
if [[ -d "$WORKTREE_DIR" ]]; then
  echo "ℹ️  Worktree folder already exists at: $WORKTREE_DIR"
else
  mkdir -p "$(dirname "$WORKTREE_DIR")"
  if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
    echo "🌿 Checking out existing local branch '$BRANCH'..."
    git worktree add "$WORKTREE_DIR" "$BRANCH"
  elif git show-ref --verify --quiet "refs/remotes/origin/$BRANCH"; then
    echo "🌿 Checking out remote branch 'origin/$BRANCH'..."
    git worktree add "$WORKTREE_DIR" -b "$BRANCH" "origin/$BRANCH"
  else
    echo "🌿 Creating new branch '$BRANCH' from '$BASE_REF'..."
    git worktree add "$WORKTREE_DIR" -b "$BRANCH" "$BASE_REF"
  fi
fi

# 3. Symlink essential Android & Agent configs
link_item() {
  local src="$1"
  local dst="$2"
  if [[ -e "$src" || -L "$src" ]]; then
    mkdir -p "$(dirname "$dst")"
    rm -rf "$dst"
    ln -s "$src" "$dst"
    local rel_dst="${dst#$REPO_ROOT/}"
    echo "   🔗 Symlinked: $(basename "$src") -> $rel_dst"
  fi
}

echo ""
echo "🔗 Symlinking vital Android and Agent configs..."
# Android vital configuration
link_item "$REPO_ROOT/local.properties" "$WORKTREE_DIR/local.properties"
link_item "$REPO_ROOT/keystore.properties" "$WORKTREE_DIR/keystore.properties"
link_item "$REPO_ROOT/secrets.properties" "$WORKTREE_DIR/secrets.properties"
link_item "$REPO_ROOT/local.defaults.properties" "$WORKTREE_DIR/local.defaults.properties"

# Google Services JSON configs (root and any module-level)
link_item "$REPO_ROOT/google-services.json" "$WORKTREE_DIR/google-services.json"
while IFS= read -r -d '' gs_file; do
  rel_path="${gs_file#$REPO_ROOT/}"
  if [[ "$rel_path" != .worktrees/* && "$rel_path" != */build/* && "$rel_path" != "google-services.json" ]]; then
    link_item "$gs_file" "$WORKTREE_DIR/$rel_path"
  fi
done < <(find "$REPO_ROOT" -name "google-services.json" -not -path "*/.worktrees/*" -not -path "*/build/*" -print0 2>/dev/null)

# Agent SDLC skills, rules & pre-tool guard hooks
link_item "$REPO_ROOT/.agents" "$WORKTREE_DIR/.agents"
link_item "$REPO_ROOT/.claude" "$WORKTREE_DIR/.claude"

# 4. Limit Gradle max-workers in worktree gradle.properties to prevent Mac RAM exhaustion
echo ""
echo "⚡ Limiting Gradle workers to $WORKERS (Mac RAM protection)..."
GRADLE_PROPS="$WORKTREE_DIR/gradle.properties"
if [[ -f "$GRADLE_PROPS" ]]; then
  if grep -q "org\.gradle\.workers\.max" "$GRADLE_PROPS"; then
    sed -i '' -e "s/^org\.gradle\.workers\.max=.*/org.gradle.workers.max=$WORKERS/" "$GRADLE_PROPS" 2>/dev/null || \
    sed -i -e "s/^org\.gradle\.workers\.max=.*/org.gradle.workers.max=$WORKERS/" "$GRADLE_PROPS"
  else
    echo -e "\n# Android Agentic SDLC: RAM protection for parallel agents\norg.gradle.workers.max=$WORKERS" >> "$GRADLE_PROPS"
  fi
else
  cat <<EOF > "$GRADLE_PROPS"
# Android Agentic SDLC: RAM protection for parallel agents
org.gradle.workers.max=$WORKERS
org.gradle.jvmargs=-Xmx2048m -XX:MaxMetaspaceSize=512m
EOF
fi
echo "   🛡️ Set org.gradle.workers.max=$WORKERS in gradle.properties"

echo ""
echo "======================================================================"
echo "✅ ANDROID WORKTREE READY: $WORKTREE_DIR"
echo "   • Ticket:         $TICKET"
echo "   • Branch:         $BRANCH"
echo "   • Gradle Workers: $WORKERS"
echo "   • Zero-Token init completed in <0.2s"
echo "======================================================================"
echo "👉 To begin work in this isolated workspace:"
echo "   cd \"$WORKTREE_DIR\""
echo "======================================================================"
