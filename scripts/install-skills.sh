#!/usr/bin/env bash
# Install signal-brain skills into Claude Code and Codex runtimes via
# symbolic (not hard) links. Idempotent: re-running is safe.
#
# Source of truth lives in <repo>/skills/<name>/. Symlinks resolve back here
# so edits in the repo are picked up by both runtimes without re-installing.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
SKILLS_SRC="$REPO_ROOT/skills"

if [ ! -d "$SKILLS_SRC" ]; then
  echo "No $SKILLS_SRC directory found. Nothing to install." >&2
  exit 1
fi

RUNTIME_DIRS=(
  "$HOME/.claude/skills"   # Claude Code
  "$HOME/.codex/skills"    # OpenAI Codex
)

installed=0
skipped=0

for runtime_dir in "${RUNTIME_DIRS[@]}"; do
  mkdir -p "$runtime_dir"
  for skill_path in "$SKILLS_SRC"/*/; do
    name="$(basename "$skill_path")"
    target="$runtime_dir/$name"
    source_abs="${skill_path%/}"   # strip trailing slash for ln -s
    if [ -L "$target" ]; then
      # Existing symlink → replace so we always point at the current repo.
      rm "$target"
    elif [ -e "$target" ]; then
      echo "Skipping $target (exists and is not a symlink; resolve manually)" >&2
      skipped=$((skipped + 1))
      continue
    fi
    ln -s "$source_abs" "$target"
    echo "Linked $target -> $source_abs"
    installed=$((installed + 1))
  done
done

echo
echo "Done. Linked: $installed. Skipped: $skipped."
echo
echo "Codex note: enable subagent dispatch by adding to ~/.codex/config.toml:"
echo "  [features]"
echo "  multi_agent = true"
