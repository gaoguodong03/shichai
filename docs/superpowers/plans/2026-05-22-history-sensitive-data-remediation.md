# Historical Sensitive Data Remediation Plan

Date: 2026-05-22
Branch: codex/project-health-next-plans
Scope: planning only; do not rewrite history without explicit confirmation

## Current status

Current `beta` HEAD is clean for the first-priority tracked-runtime-data issue:

- `git ls-files -ci --exclude-standard` returns 0 tracked ignored paths.
- `git ls-files backend/data/users` returns 0 paths.
- `backend/config/auth_users.txt`, `backend/config/users.json`, and `backend/data/users/` remain local ignored runtime data.

History still contains sensitive/runtime paths. This plan covers remediation; it does not execute history rewriting.

## Historical risk inventory

### P0: secrets, credentials, authentication state, real user data

Historical paths include:

- `backend/.env`
- `.1panel-backup-src/1panel-compose-backup/compose_files/.env`
- `backend/config/auth_users.sqlite`
- `backend/config/auth_users.txt`
- `backend/config/users.json`
- `backend/data/users/**`
- `backend/data/users/**/config/api_secrets.json`
- `backend/data/users/**/sessions/**`
- `backend/data/users/**/skills/**`

Required response:

- Treat all keys, auth secrets, provider tokens, and password material from these paths as compromised.
- Rotate API keys and service tokens before or immediately after history rewrite.
- Reset local auth credentials and remove any production-derived account state from working clones.

### P1: runtime outputs, logs, backups, generated artifacts

Historical paths include:

- `.cursor/debug.log`
- `backend/.cursor/debug.log`
- `1panel-compose-backup.tar.gz`
- `1panel-compose-backup-fixed.tar.gz`
- `backend/data/agent-outputs/**`
- `backend/data/users/**/agent-outputs/**`

Required response:

- Remove from public/shared Git history.
- Preserve any needed local copies outside the repository before rewriting history.

### P2: templates and examples to review

Historical/current paths include:

- `backend/.env.1panel.example`
- `backend/.env.example`

Required response:

- Keep only placeholder values.
- Confirm examples do not include real domains, credentials, internal registry tokens, or user identifiers.

## Recommended approach

Use `git filter-repo` for a coordinated history rewrite after all collaborators are warned.

Do not use this on `beta` until the user explicitly approves the rewrite window.

### Preparation

1. Freeze pushes to the repository.
2. Notify collaborators that they must reclone or hard-reset after force-push.
3. Confirm current working trees are clean.
4. Create an offline bundle backup:

```bash
/Users/ggd/.local/bin/rtk git bundle create /private/tmp/shichai-pre-history-clean.bundle --all
```

5. Export a redacted path inventory for review:

```bash
/Users/ggd/.local/bin/rtk sh -lc 'git log --all --name-only --pretty=format: | sort -u | rg "(^|/)(\\.env($|\\.)|.*\\.sqlite$|.*\\.db$|.*\\.tar\\.gz$|debug\\.log$|agent-outputs/|backend/data/users/|api_secrets\\.json$|auth_users(\\.txt|\\.sqlite)?$|users\\.json$)" > /private/tmp/shichai-sensitive-history-paths.txt'
```

### Rewrite candidate

Run only after approval:

```bash
/Users/ggd/.local/bin/rtk git filter-repo --force \
  --path backend/.env --invert-paths \
  --path .1panel-backup-src/1panel-compose-backup/compose_files/.env --invert-paths \
  --path backend/config/auth_users.sqlite --invert-paths \
  --path backend/config/auth_users.txt --invert-paths \
  --path backend/config/users.json --invert-paths \
  --path-glob 'backend/data/users/**' --invert-paths \
  --path-glob 'backend/data/agent-outputs/**' --invert-paths \
  --path .cursor/debug.log --invert-paths \
  --path backend/.cursor/debug.log --invert-paths \
  --path 1panel-compose-backup.tar.gz --invert-paths \
  --path 1panel-compose-backup-fixed.tar.gz --invert-paths
```

If `git filter-repo` is unavailable, install it in an approved environment or use a disposable clone where the tool is already available. Do not improvise with manual `git reset`/`git checkout` history edits.

### Secret and account rotation checklist

- Rotate all LLM provider keys that may have been in `backend/.env` or `api_secrets.json`.
- Rotate OpenSandbox, deployment, registry, and service integration tokens from historical `.env` files.
- Reset authentication material in `backend/config/auth_users.sqlite` and any plaintext auth file.
- Invalidate old application auth secrets/JWT/session secrets if present.
- Replace local runtime credentials with freshly generated values after the rewrite.

### Post-rewrite verification

Run in the rewritten clone before force-push:

```bash
/Users/ggd/.local/bin/rtk sh -lc 'git log --all --name-only --pretty=format: | rg "(backend/\\.env|auth_users|backend/data/users|api_secrets\\.json|agent-outputs|debug\\.log|1panel-compose-backup)" && exit 1 || true'
/Users/ggd/.local/bin/rtk sh -lc 'git ls-files -ci --exclude-standard | wc -l'
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest tests/test_auth_sqlite.py tests/test_call_api_tool.py tests/test_volces_icon_debug_logging.py -q'
/Users/ggd/.local/bin/rtk npm --prefix frontend run build
```

Expected:

- No sensitive historical paths appear.
- Current tracked ignored paths remain 0.
- Backend tests pass.
- Frontend build succeeds with only known warnings.

### Force-push and recovery

After explicit approval and verification:

```bash
/Users/ggd/.local/bin/rtk git push --force-with-lease origin beta
```

Recovery if something goes wrong:

```bash
/Users/ggd/.local/bin/rtk git clone /private/tmp/shichai-pre-history-clean.bundle /private/tmp/shichai-restore-check
```

Do not delete the bundle until every deployment and collaborator clone is confirmed healthy.
