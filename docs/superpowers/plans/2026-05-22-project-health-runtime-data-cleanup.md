# Project Health Runtime Data Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove current-HEAD Git tracking for runtime data and sensitive local configuration without deleting local files, then add safe examples and docs so the same files stay local-only.

**Architecture:** Treat runtime state as local data, not source. Current HEAD cleanup uses `git rm --cached` only, broadens `.gitignore` for generated user/auth state, and adds explicit examples for bootstrap files. Historical exposure is documented for a separate rotation/history-rewrite plan; this plan does not rewrite history.

**Tech Stack:** Git index cleanup, `.gitignore`, FastAPI backend docs, conda env `st49` for backend verification, `/Users/ggd/.local/bin/rtk` for every shell command.

---

## Audit Summary

### Current HEAD Findings

**P0 - tracked sensitive/user data**

- `backend/config/auth_users.txt`: plaintext legacy seed credentials. Keep local file, remove from Git, add `backend/config/auth_users.txt.example`.
- `backend/config/users.json`: real account identifiers and profile timestamps. Keep local file, remove from Git, add `backend/config/users.json.example`.
- `backend/data/users/`: 376 tracked files under real user identifiers, including email/phone account directories, per-user configs, `api_secrets.json`, MCP server configs, session presets, user Skills, and Skill assets. Keep local files, remove from Git, ignore the whole runtime tree.

**P1 - tracked runtime output/cache/build-like data inside user tree**

- `backend/data/users/*/skills/**/.scrapling_dependencies_installed`: dependency/cache marker inside a user Skill copy. Covered by removing and ignoring `backend/data/users/`.
- `backend/data/users/*/skills/**/assets/*.xls`: user Skill assets copied into runtime user directories. Covered by removing and ignoring `backend/data/users/`.
- Historical-only P1 paths include `backend/data/agent-outputs/`, `backend/logs/llm_trace.log`, `.cursor/debug*.log`, `backend/.cursor/debug.log`, `1panel-compose-backup*.tar.gz`, and `.artifacts/*.tar`. These are not tracked in current HEAD after phase 1 and remain history-only unless reintroduced.

**P2 - template/docs hygiene**

- `README.md` has a real-looking account creation example. Replace it with placeholders.
- `backend/README.md` says `.env` is optional but has no local `backend/.env.example`. Add `backend/.env.example` with placeholders.
- `backend/app/core/users_store.py` still says passwords are managed by `auth_users.txt`; update the comment to SQLite auth DB and clarify `users.json` is runtime profile data.

### History Findings

History contains sensitive/runtime paths such as `backend/.env`, `backend/config/auth_users.sqlite`, `backend/config/auth_users.txt`, `backend/data/users/`, `backend/data/agent-outputs/`, and `1panel-compose-backup.tar.gz`. This plan records that exposure but intentionally does not run `git filter-repo`, BFG, force-push, or any other history rewrite. Follow-up should include key/token rotation and a coordinated history-cleaning plan if the repository leaves trusted storage.

---

## Files

- Modify: `.gitignore`
- Modify: `README.md`
- Modify: `backend/README.md`
- Modify: `backend/app/core/users_store.py`
- Modify: `backend/tests/test_volces_icon_debug_logging.py`
- Create: `backend/.env.example`
- Create: `backend/config/auth_users.txt.example`
- Create: `backend/config/users.json.example`
- Git index only: `backend/config/auth_users.txt`
- Git index only: `backend/config/users.json`
- Git index only: all currently tracked files under `backend/data/users/`

## Task 1: Ignore Runtime User And Auth State

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Check current status**

Run:

```bash
/Users/ggd/.local/bin/rtk git status --short --branch
```

Expected: branch is `codex/project-health-runtime-data`; no unexpected user edits.

- [ ] **Step 2: Add ignore rules**

Add these rules to `.gitignore` near the existing runtime/config rules:

```gitignore
backend/config/auth_users.txt
backend/config/users.json
backend/data/users/
```

Keep existing `backend/config/*.sqlite` and `backend/data/agent-outputs/` rules.

- [ ] **Step 3: Verify ignore behavior before untracking**

Run:

```bash
/Users/ggd/.local/bin/rtk git check-ignore --no-index backend/config/auth_users.txt backend/config/users.json backend/data/users/2987371922@qq.com/config/api_secrets.json
```

Expected: all three paths are printed.

## Task 2: Add Safe Examples And Docs

**Files:**
- Create: `backend/.env.example`
- Create: `backend/config/auth_users.txt.example`
- Create: `backend/config/users.json.example`
- Modify: `README.md`
- Modify: `backend/README.md`
- Modify: `backend/app/core/users_store.py`

- [ ] **Step 1: Add local env example**

Create `backend/.env.example`:

```dotenv
# Copy to backend/.env for local development. Do not commit backend/.env.

QWEN_API_KEY=your_qwen_api_key
AUTH_SECRET=change_me_to_a_long_random_secret
CORS_ORIGINS=http://127.0.0.1:5173,http://127.0.0.1:8100

# Optional: override runtime data root. Default is backend/data/users.
# SHUTONG_USER_DATA_ROOT=backend/data/users

# Optional sandbox settings for local OpenSandbox.
# OPENSANDBOX_DOMAIN=127.0.0.1:8091
# OPENSANDBOX_PROTOCOL=http
# OPENSANDBOX_USE_SERVER_PROXY=0
# SANDBOX_ALLOW_NETWORK=0
```

- [ ] **Step 2: Add legacy auth seed example**

Create `backend/config/auth_users.txt.example`:

```text
# Optional legacy seed file.
# Copy to backend/config/auth_users.txt only for a local bootstrap migration.
# Prefer: python manage_accounts.py add --username demo@example.com --password 'change-me'
#
# Format:
# demo@example.com:change-me
```

- [ ] **Step 3: Add users profile example**

Create `backend/config/users.json.example`:

```json
{}
```

- [ ] **Step 4: Update docs/comments**

Update:

- `README.md`: replace real-looking `manage_accounts.py add` account/password with placeholders and note that `backend/config/auth_users.txt`, `backend/config/users.json`, and `backend/data/users/` are local runtime state.
- `backend/README.md`: point quick start at `backend/.env.example`, `manage_accounts.py`, and ignored runtime files.
- `backend/app/core/users_store.py`: change the module comment so password storage is described as SQLite auth DB, not `auth_users.txt`.
- `backend/tests/test_volces_icon_debug_logging.py`: resolve `volces_icon.py` from `__file__` so the backend test passes when run from `backend/` as required by AGENT.md.

## Task 3: Untrack Current HEAD Runtime Data

**Files:**
- Git index only: `backend/config/auth_users.txt`
- Git index only: `backend/config/users.json`
- Git index only: `backend/data/users/`

- [ ] **Step 1: Capture inventory**

Run:

```bash
/Users/ggd/.local/bin/rtk sh -c 'git ls-files backend/config/auth_users.txt backend/config/users.json backend/data/users > /tmp/shichai-runtime-data-current-head.txt'
/Users/ggd/.local/bin/rtk sh -c 'wc -l /tmp/shichai-runtime-data-current-head.txt'
/Users/ggd/.local/bin/rtk sh -c 'sed -n "1,80p" /tmp/shichai-runtime-data-current-head.txt'
```

Expected: 378 paths: 2 config files plus 376 user-data paths.

- [ ] **Step 2: Remove only Git tracking**

Run:

```bash
/Users/ggd/.local/bin/rtk git rm --cached --pathspec-from-file=/tmp/shichai-runtime-data-current-head.txt
```

Expected: staged deletions only; local files remain on disk in this worktree.

- [ ] **Step 3: Verify local files still exist**

Run:

```bash
/Users/ggd/.local/bin/rtk sh -c 'test -f backend/config/auth_users.txt'
/Users/ggd/.local/bin/rtk sh -c 'test -f backend/config/users.json'
/Users/ggd/.local/bin/rtk sh -c 'test -d backend/data/users'
```

Expected: all commands exit 0.

## Task 4: Verify Cleanup

**Files:**
- No new edits unless verification exposes a gap.

- [ ] **Step 1: Verify current HEAD tracked risk paths are gone from the index**

Run:

```bash
/Users/ggd/.local/bin/rtk sh -c 'git ls-files | rg "^(backend/config/(auth_users\\.txt|users\\.json)|backend/data/users/)"'
```

Expected: no matches; `rg` exits 1.

- [ ] **Step 2: Verify ignore coverage**

Run:

```bash
/Users/ggd/.local/bin/rtk git check-ignore --no-index backend/config/auth_users.txt backend/config/users.json backend/data/users/2987371922@qq.com/config/api_secrets.json
```

Expected: all three paths are printed.

- [ ] **Step 3: Run backend regression tests**

Run:

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 python -m pytest backend/tests/test_auth_sqlite.py backend/tests/test_call_api_tool.py backend/tests/test_volces_icon_debug_logging.py -q
```

Expected: tests pass. If `conda run -n st49 python -m pytest ...` fails because it is not run from `backend`, use:

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest tests/test_auth_sqlite.py tests/test_call_api_tool.py tests/test_volces_icon_debug_logging.py -q'
```

- [ ] **Step 4: Clean generated Python caches**

Run:

```bash
/Users/ggd/.local/bin/rtk sh -lc 'find backend -type d -name __pycache__ -prune -exec rm -rf {} +; find backend -type f -name "*.pyc" -delete'
```

Expected: no tracked changes from cache files.

- [ ] **Step 5: Review diff**

Run:

```bash
/Users/ggd/.local/bin/rtk git status --short
/Users/ggd/.local/bin/rtk git diff --stat
/Users/ggd/.local/bin/rtk git diff -- .gitignore README.md backend/README.md backend/app/core/users_store.py backend/.env.example backend/config/auth_users.txt.example backend/config/users.json.example
```

Expected: staged/untracked changes match only this plan.

## Task 5: Commit

**Files:**
- All files from Tasks 1-3.

- [ ] **Step 1: Stage intended files**

Run:

```bash
/Users/ggd/.local/bin/rtk git add .gitignore README.md backend/README.md backend/app/core/users_store.py backend/.env.example backend/config/auth_users.txt.example backend/config/users.json.example docs/superpowers/plans/2026-05-22-project-health-runtime-data-cleanup.md
/Users/ggd/.local/bin/rtk git status --short
```

Expected: docs/templates/docs are staged; Git-index deletions from `git rm --cached` are staged.

- [ ] **Step 2: Commit**

Run:

```bash
/Users/ggd/.local/bin/rtk git commit -m "chore: 清理运行时用户数据跟踪"
```

Expected: one commit on `codex/project-health-runtime-data`; no push.

## Rollback

- Undo the branch commit: `git revert <commit>` from a clean branch.
- Restore tracking of a specific file if needed: `git add -f <path>` then commit, but do not do this for P0 data.
- Local data rollback is normally unnecessary because cleanup uses `git rm --cached`; if a local file is missing in this worktree, recover it from `stash@{0}: preserve 1panel backup before phase1 merge`, another local worktree, or Git history only after confirming it is safe to re-materialize sensitive data.
