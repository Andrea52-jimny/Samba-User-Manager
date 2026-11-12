#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# One-shot repository migration to the v1.0.0 public layout.
#
#   * flattens smb-user-manager/ into the repository root
#   * deletes the older duplicate copy of the application that lived at root
#   * removes the author-specific deployment scripts
#   * drops committed __pycache__ from the index
#   * moves github-templates/ into .github/
#
# Run it ONCE from the repository root. It is a dry run by default:
#
#     ./migrate-to-v1.sh            # show what would happen
#     ./migrate-to-v1.sh --apply    # actually do it
#
# Nothing is committed: review with `git status` and `git diff --staged`,
# then commit yourself. Delete this script afterwards.
# ---------------------------------------------------------------------------
set -euo pipefail

APPLY=false
[[ "${1:-}" == "--apply" ]] && APPLY=true

say()  { printf '%s\n' "$*"; }
step() { printf '\n==> %s\n' "$*"; }
run()  {
  if $APPLY; then
    "$@"
  else
    printf '    [dry-run] %s\n' "$*"
  fi
}

# --- Safety checks ----------------------------------------------------------
[[ -d .git ]] || { echo "ERROR: run this from the repository root." >&2; exit 1; }
[[ -d smb-user-manager ]] || { echo "ERROR: smb-user-manager/ not found. Already migrated?" >&2; exit 1; }

if $APPLY && [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "ERROR: you have uncommitted changes to tracked files." >&2
  echo "Commit or stash them first, so this migration is a reviewable diff." >&2
  exit 1
fi

$APPLY || say "DRY RUN - nothing will be modified. Re-run with --apply to proceed."

# --- 0. Install the GitHub templates ----------------------------------------
# They are shipped in github-templates/ because the .github/ directory cannot
# be written to by the tooling that generated them. This moves them into
# place; review them before committing, as they drive CI on every push.
if [[ -d github-templates ]]; then
  step "Installing GitHub templates into .github/"
  if [[ -e .github ]]; then
    say "    .github/ already exists - merging"
  fi
  run mkdir -p .github
  while IFS= read -r -d '' src; do
    rel="${src#github-templates/}"
    say "    github-templates/$rel -> .github/$rel"
    run mkdir -p ".github/$(dirname "$rel")"
    run mv -- "$src" ".github/$rel"
  done < <(find github-templates -type f -print0)
  run rm -rf -- github-templates
fi

# --- 1. Remove the legacy duplicate at the repository root ------------------
# These are the older copy of the application, superseded by smb-user-manager/.
LEGACY_ROOT=(
  app
  static
  templates
  init_db.py
  install.sh
  requirements.txt
  samba-manager.service
  smb.conf.dati.corretto.example
)

step "Removing the legacy copy at the repository root"
REMOVED=()
for item in "${LEGACY_ROOT[@]}"; do
  if [[ -e "$item" ]]; then
    say "    - $item"
    run rm -rf -- "$item"
    REMOVED+=("$item")
  fi
done

# Editor lock files that should never have been in the repository.
while IFS= read -r -d '' lock; do
  say "    - $lock"
  run rm -f -- "$lock"
done < <(find . -maxdepth 1 -name '.~lock.*#' -print0)

# --- 2. Drop the author-specific deployment scripts -------------------------
# Updating is now: git pull && docker compose up -d --build
step "Removing author-specific deployment scripts"
for item in update.sh cleanup.sh reset-repo-from-prod.sh; do
  if [[ -e "smb-user-manager/$item" ]]; then
    say "    - smb-user-manager/$item"
    run rm -f -- "smb-user-manager/$item"
  fi
done

# The nested README is superseded by the new root README.md / README.it.md.
if [[ -e smb-user-manager/README.md ]]; then
  say "    - smb-user-manager/README.md (superseded)"
  run rm -f -- smb-user-manager/README.md
fi

# --- 3. Move the application up to the repository root ----------------------
MOVE=(
  app
  docker
  static
  templates
  Dockerfile
  docker-compose.yml
  .dockerignore
  init_db.py
  install.sh
  requirements.txt
  smb-user-manager.service
)

step "Moving smb-user-manager/* to the repository root"
for item in "${MOVE[@]}"; do
  src="smb-user-manager/$item"
  if [[ ! -e "$src" ]]; then
    say "    ? $src not found, skipping"
    continue
  fi
  if [[ -e "$item" ]]; then
    # In a dry run step 1 did not actually delete anything, so an item it
    # listed is not a real collision.
    planned=false
    for gone in ${REMOVED[@]+"${REMOVED[@]}"}; do
      [[ "$gone" == "$item" ]] && planned=true && break
    done
    if $APPLY || ! $planned; then
      echo "ERROR: $item already exists at the repository root." >&2
      echo "Remove or rename it by hand, then re-run this script." >&2
      exit 1
    fi
  fi
  say "    $src -> $item"
  run mv -- "$src" "$item"
done

# --- 4. Clean up what is left of the old directory --------------------------
step "Cleaning up"
run find . -name '__pycache__' -type d -not -path './.git/*' -prune -exec rm -rf -- {} +
if $APPLY; then
  leftovers="$(find smb-user-manager -mindepth 1 2>/dev/null || true)"
  if [[ -n "$leftovers" ]]; then
    echo "WARNING: smb-user-manager/ is not empty, leaving it in place:" >&2
    printf '%s\n' "$leftovers" >&2
  else
    rmdir smb-user-manager
    say "    removed empty smb-user-manager/"
  fi
else
  say "    [dry-run] remove __pycache__ and the now-empty smb-user-manager/"
fi

# Byte-compiled files are now covered by .gitignore but may still be tracked.
step "Dropping byte-compiled files from the git index"
run git rm -r --cached --quiet --ignore-unmatch '*.pyc' '**/__pycache__'

# --- 5. Stage everything ----------------------------------------------------
step "Staging the result"
run git add -A

cat <<'EOS'

---------------------------------------------------------------------------
Done. Review before committing:

    git status
    git diff --staged --stat

Then, if it looks right:

    rm migrate-to-v1.sh
    git add -A
    git commit -m "Restructure repository for the first public release"
    git tag -a v1.0.0 -m "First public release"
    git push && git push --tags

Before publishing, also check:
  * cp .env.example .env on your server and set ADMIN_PASSWORD
  * your deployment still works: docker compose up -d --build
  * the web UI port changed from 80 to 8000 by default (set WEB_PORT=80
    in .env to keep your current setup)
---------------------------------------------------------------------------
EOS
