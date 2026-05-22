# Project Health Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove clearly invalid Git-tracked artifacts, fix the group-chat Markdown CSS selector bug, remove temporary debug log writes, and delete verified unused frontend components with rollback-friendly commits.

**Architecture:** Keep changes split by concern. Git-index cleanup only changes tracking state; CSS changes stay in `WorkspaceContent.css`; Python debug cleanup keeps tool contracts unchanged; frontend dead-code deletion only removes files after reference scans and build checks.

**Tech Stack:** Git, Python pytest in conda env `st49`, Vue 3/Vite/TypeScript frontend build, shell verification via `/Users/ggd/.local/bin/rtk`.

---

## Files

- Modify Git index only: ignored tracked files returned by `git ls-files -ci --exclude-standard`, including `1panel-compose-backup.tar.gz`.
- Modify: `frontend/src/features/workspace/WorkspaceContent.css`
- Modify: `backend/app/tools/call_api.py`
- Modify: `backend/app/mcp/stdio/volces_icon.py`
- Modify: `backend/tests/test_call_api_tool.py`
- Create: `backend/tests/test_volces_icon_debug_logging.py`
- Delete if still unreferenced: `frontend/src/components/LLMConfig.vue`
- Delete if still unreferenced: `frontend/src/components/MCPConfig.vue`
- Delete if still unreferenced: `frontend/src/components/SkillsConfig.vue`

## Task 1: Untrack Ignored Runtime Artifacts

**Files:**
- Git index only: output of `git ls-files -ci --exclude-standard`

- [ ] **Step 1: Generate the tracked-ignored inventory**

Run:

```bash
/Users/ggd/.local/bin/rtk git ls-files -ci --exclude-standard > /tmp/shichai-phase1-tracked-ignored.txt
/Users/ggd/.local/bin/rtk wc -l /tmp/shichai-phase1-tracked-ignored.txt
/Users/ggd/.local/bin/rtk sed -n '1,80p' /tmp/shichai-phase1-tracked-ignored.txt
```

Expected: the list includes env/log/sqlite/runtime artifact paths and `1panel-compose-backup.tar.gz`.

- [ ] **Step 2: Remove only Git tracking**

Run:

```bash
/Users/ggd/.local/bin/rtk git rm --cached --pathspec-from-file=/tmp/shichai-phase1-tracked-ignored.txt
```

Expected: Git stages deletions for tracked ignored artifacts; files remain on disk because `--cached` is used.

- [ ] **Step 3: Verify no ignored tracked files remain**

Run:

```bash
/Users/ggd/.local/bin/rtk git ls-files -ci --exclude-standard
/Users/ggd/.local/bin/rtk test -f 1panel-compose-backup.tar.gz
```

Expected: `git ls-files -ci --exclude-standard` prints nothing; `test -f` exits 0.

- [ ] **Step 4: Commit Git-index cleanup**

Run:

```bash
/Users/ggd/.local/bin/rtk git status --short
/Users/ggd/.local/bin/rtk git commit -m "chore: 清理已忽略的运行产物索引"
```

Expected: commit contains only deleted tracked ignored artifacts. No local artifact is removed from disk.

## Task 2: Fix Group-Chat Markdown CSS Selectors

**Files:**
- Modify: `frontend/src/features/workspace/WorkspaceContent.css`

- [ ] **Step 1: Verify the selector bug is present**

Run:

```bash
/Users/ggd/.local/bin/rtk rg -n "\\.group-chat-markdown :deep" frontend/src/features/workspace/WorkspaceContent.css
```

Expected before fix: multiple matches under `.group-chat-markdown`.

- [ ] **Step 2: Convert external-CSS `:deep()` selectors**

Change only `.group-chat-markdown :deep(...)` selectors in `frontend/src/features/workspace/WorkspaceContent.css`.

Required replacements:

```css
.group-chat-markdown > * { ... }
.group-chat-markdown > *:last-child { ... }
.group-chat-markdown p { ... }
.group-chat-markdown p:last-child { ... }
.group-chat-markdown h1, .group-chat-markdown h2, .group-chat-markdown h3,
.group-chat-markdown h4, .group-chat-markdown h5, .group-chat-markdown h6 { ... }
.group-chat-markdown h1:first-child, .group-chat-markdown h2:first-child, .group-chat-markdown h3:first-child,
.group-chat-markdown h4:first-child, .group-chat-markdown h5:first-child, .group-chat-markdown h6:first-child { ... }
.group-chat-markdown pre code { ... }
.group-chat-markdown .group-chat-tool-call[open] .group-chat-tool-call-summary { ... }
```

Do not change `:deep()` in SFC files such as `SkillDetailView.vue` or `FileDetailView.vue`.

- [ ] **Step 3: Verify the bug is gone and frontend builds**

Run:

```bash
/Users/ggd/.local/bin/rtk rg -n "\\.group-chat-markdown :deep" frontend/src/features/workspace/WorkspaceContent.css
/Users/ggd/.local/bin/rtk npm --prefix frontend run build
```

Expected: `rg` exits 1 with no matches; `npm --prefix frontend run build` exits 0.

- [ ] **Step 4: Commit CSS fix**

Run:

```bash
/Users/ggd/.local/bin/rtk git add frontend/src/features/workspace/WorkspaceContent.css
/Users/ggd/.local/bin/rtk git commit -m "fix: 修复群聊 Markdown 样式选择器"
```

Expected: commit contains only `WorkspaceContent.css`.

## Task 3: Remove Temporary Debug Log Writes

**Files:**
- Modify: `backend/app/tools/call_api.py`
- Modify: `backend/app/mcp/stdio/volces_icon.py`
- Modify: `backend/tests/test_call_api_tool.py`
- Create: `backend/tests/test_volces_icon_debug_logging.py`

- [ ] **Step 1: Add failing regression test for `call_api` debug log writes**

Append to `backend/tests/test_call_api_tool.py`:

```python
from pathlib import Path


def test_call_api_does_not_write_cursor_debug_log(monkeypatch):
    from app.tools import call_api as mod

    debug_log = Path(mod.__file__).resolve().parents[2] / ".cursor" / "debug.log"
    if debug_log.exists():
        debug_log.unlink()

    class _Resp:
        status_code = 200
        headers = {"content-type": "application/json"}
        text = '{"ok":true}'

        @staticmethod
        def json():
            return {"ok": True}

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def request(self, method, url, content=None, headers=None):
            return _Resp()

    monkeypatch.setattr(mod.httpx, "Client", _Client)
    out = _run_call_api(mod, url="https://example.com/api")

    assert "状态码: 200" in out
    assert not debug_log.exists()
```

Add the `from pathlib import Path` import once at the top of `backend/tests/test_call_api_tool.py`. The failing test should fail because the current implementation creates `backend/.cursor/debug.log`, not because of an import error.

- [ ] **Step 2: Add failing static regression test for Volces local path leakage**

Create `backend/tests/test_volces_icon_debug_logging.py`:

```python
from __future__ import annotations

from pathlib import Path


def test_volces_icon_has_no_hardcoded_local_debug_path():
    source = Path("backend/app/mcp/stdio/volces_icon.py").read_text(encoding="utf-8")
    assert "/Users/ggd/" not in source
    assert "mycode/DHA/.cursor/debug.log" not in source
```

- [ ] **Step 3: Run tests and verify red**

Run:

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 python -m pytest backend/tests/test_call_api_tool.py::test_call_api_does_not_write_cursor_debug_log backend/tests/test_volces_icon_debug_logging.py -q
```

Expected before implementation: failure because `call_api` still creates `backend/.cursor/debug.log` and `volces_icon.py` still contains `/Users/ggd/mycode/DHA/.cursor/debug.log`.

- [ ] **Step 4: Remove `call_api` agent-log blocks**

In `backend/app/tools/call_api.py`:

- remove all `# #region agent log: call_api ...` / `# #endregion agent log: ...` blocks
- do not change URL parsing, SSRF guard, request execution, return text, or error messages

- [ ] **Step 5: Replace Volces local debug writer with disabled-by-default logger**

In `backend/app/mcp/stdio/volces_icon.py`, replace `_agent_log()` with:

```python
def _agent_log(message: str, data: dict | None = None, hypothesis_id: str | None = None) -> None:
    """Optional local diagnostics; disabled unless VOLCES_ICON_DEBUG_LOG is set."""
    log_path = os.environ.get("VOLCES_ICON_DEBUG_LOG", "").strip()
    if not log_path:
        return
    try:
        payload = {
            "id": f"log_volces_icon_{int(time.time() * 1000)}",
            "timestamp": int(time.time() * 1000),
            "location": "app/mcp/stdio/volces_icon.py",
            "message": message,
            "data": data or {},
            "runId": "volces-icon",
        }
        if hypothesis_id:
            payload["hypothesisId"] = hypothesis_id
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
```

- [ ] **Step 6: Verify green**

Run:

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 python -m pytest backend/tests/test_call_api_tool.py backend/tests/test_volces_icon_debug_logging.py -q
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit debug cleanup**

Run:

```bash
/Users/ggd/.local/bin/rtk git add backend/app/tools/call_api.py backend/app/mcp/stdio/volces_icon.py backend/tests/test_call_api_tool.py backend/tests/test_volces_icon_debug_logging.py
/Users/ggd/.local/bin/rtk git commit -m "chore: 移除临时调试日志写入"
```

Expected: commit contains only the two Python implementation files and two tests.

## Task 4: Delete Verified Dead Frontend Components

**Files:**
- Delete: `frontend/src/components/LLMConfig.vue`
- Delete: `frontend/src/components/MCPConfig.vue`
- Delete: `frontend/src/components/SkillsConfig.vue`

- [ ] **Step 1: Verify no references remain**

Run:

```bash
/Users/ggd/.local/bin/rtk rg -n "components/(LLMConfig|MCPConfig|SkillsConfig)|LLMConfig.vue|MCPConfig.vue|SkillsConfig.vue|<LLMConfig|<MCPConfig|<SkillsConfig" frontend -S
```

Expected before deletion: no matches.

- [ ] **Step 2: Delete the unreferenced component files**

Run:

```bash
/Users/ggd/.local/bin/rtk git rm frontend/src/components/LLMConfig.vue frontend/src/components/MCPConfig.vue frontend/src/components/SkillsConfig.vue
```

- [ ] **Step 3: Verify frontend build**

Run:

```bash
/Users/ggd/.local/bin/rtk npm --prefix frontend run build
```

Expected: build exits 0.

- [ ] **Step 4: Commit dead-code deletion**

Run:

```bash
/Users/ggd/.local/bin/rtk git commit -m "chore: 删除未引用的前端旧组件"
```

Expected: commit contains only the three deleted Vue component files.

## Task 5: Final Verification

**Files:**
- No new changes expected

- [ ] **Step 1: Run backend targeted regression**

Run:

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 python -m pytest backend/tests/test_call_api_tool.py backend/tests/test_volces_icon_debug_logging.py -q
```

Expected: all selected backend tests pass.

- [ ] **Step 2: Run frontend build**

Run:

```bash
/Users/ggd/.local/bin/rtk npm --prefix frontend run build
```

Expected: `vue-tsc && vite build` exits 0.

- [ ] **Step 3: Verify Git hygiene**

Run:

```bash
/Users/ggd/.local/bin/rtk git ls-files -ci --exclude-standard
/Users/ggd/.local/bin/rtk git status --short --branch
/Users/ggd/.local/bin/rtk git log --oneline --decorate -8
```

Expected: no tracked ignored files remain; branch is `codex/project-health-phase-1`; only expected commits are present; worktree is clean except ignored local artifacts.

## Self-Review

- Spec coverage: covered Git-index cleanup, CSS fix, debug-log cleanup, and verified dead component deletion.
- Placeholder scan: no `TBD`, no vague test step, no unbounded cleanup instruction.
- Type/path consistency: frontend commands use `npm --prefix frontend run build`; backend commands use `conda run -n st49`; Git commands use `/Users/ggd/.local/bin/rtk`.
