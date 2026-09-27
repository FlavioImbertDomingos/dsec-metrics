#!/bin/sh
# Fail if any commit in BASE..HEAD lacks a Signed-off-by line (Developer Certificate
# of Origin). Usage: scripts/check-dco.sh BASE_SHA HEAD_SHA
set -eu
base="$1"
head="$2"
missing=0
for sha in $(git rev-list --no-merges "$base..$head"); do
  if ! git show -s --format=%B "$sha" | grep -q '^Signed-off-by: '; then
    echo "missing sign-off: $(git show -s --format='%h %s' "$sha")"
    missing=1
  fi
done
if [ "$missing" = 1 ]; then
  echo "Sign off with 'git commit -s' (amend with 'git commit --amend -s --no-edit')."
  exit 1
fi
echo "All commits are signed off."
