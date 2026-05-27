#!/usr/bin/env bash
# sync.sh — cherry-pick one or more commits from dev to all other branches.
#
# Usage:
#   ./sync.sh              # sync the latest commit on dev
#   ./sync.sh abc1234      # sync a specific commit
#   ./sync.sh abc1 abc2    # sync multiple commits (applied in order)

set -euo pipefail

BRANCHES=(main osr prsnl)
ORIGIN_BRANCH=$(git rev-parse --abbrev-ref HEAD)

# Default to HEAD of dev if no commits given
if [ $# -eq 0 ]; then
  COMMITS=($(git rev-parse HEAD))
else
  COMMITS=("$@")
fi

echo "Syncing ${#COMMITS[@]} commit(s) to: ${BRANCHES[*]}"
echo ""

for branch in "${BRANCHES[@]}"; do
  echo "──────────────────────────────────────────"
  echo "→ $branch"
  git checkout "$branch"

  for commit in "${COMMITS[@]}"; do
    msg=$(git log --oneline -1 "$commit")
    echo "  cherry-pick $msg"

    if ! git cherry-pick "$commit"; then
      echo ""
      echo "⚠  Conflict on '$branch' for commit $commit"
      echo "   Resolve the conflicts, then run:"
      echo "     git cherry-pick --continue"
      echo "     git push origin $branch"
      echo "   Then re-run ./sync.sh for any remaining branches."
      exit 1
    fi
  done

  git push origin "$branch"
  echo "  ✓ pushed"
done

echo ""
echo "──────────────────────────────────────────"
echo "✓ All branches synced. Returning to $ORIGIN_BRANCH."
git checkout "$ORIGIN_BRANCH"
