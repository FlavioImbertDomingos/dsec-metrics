#!/bin/sh
# Print every scanner suppression in the repository, so reviewers see them in one place.
# Suppressions are allowed only with a reason; see docs/adr/0005-security-gate-policy.md.
set -eu
echo "Active suppressions:"
found=0
if git grep -n -E '#\s*nosec|nosemgrep|gitleaks:allow|noqa: S[0-9]' -- ':!scripts/list-suppressions.sh' ':!docs/**' 2>/dev/null; then
  found=1
fi
for f in .trivyignore.yaml osv-scanner.toml; do
  if [ -f "$f" ] && grep -q -E '^\s*-?\s*id\s*[:=]' "$f"; then
    echo "$f:"
    grep -E 'id|statement|reason|expired_at|ignoreUntil' "$f" | sed 's/^/  /'
    found=1
  fi
done
[ "$found" = 0 ] && echo "  none"
exit 0
