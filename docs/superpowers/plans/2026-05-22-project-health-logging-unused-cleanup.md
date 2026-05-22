# Project Health Phase 2: logging and unused frontend symbols

Date: 2026-05-22
Branch: codex/project-health-logging-unused
Base: beta at b0ea0d9

## Scope

This phase addresses two current-HEAD project health issues:

1. Production-path diagnostic logging should not depend on ad-hoc debug files.
2. Frontend unused-symbol debt should be reduced where `vue-tsc --noUnusedLocals --noUnusedParameters` gives concrete evidence.

This phase does not rewrite git history, push changes, or begin large-file decomposition.

## Current evidence

- `backend/app/tools/call_api.py` no longer writes `.cursor/debug.log`.
- `backend/app/mcp/stdio/volces_icon.py` still contains `_agent_log`, but it is opt-in via `VOLCES_ICON_DEBUG_LOG`.
- Backend baseline:
  - `conda run -n st49 bash -lc 'cd backend && python -m pytest tests/test_call_api_tool.py tests/test_volces_icon_debug_logging.py -q'`
  - Result: 8 passed.
- Frontend baseline:
  - `cd frontend && ./node_modules/.bin/vue-tsc --noEmit --noUnusedLocals --noUnusedParameters`
  - Result: 35 unused-symbol errors.

## Planned changes

### Backend logging

- Replace the Volces MCP server's JSON-file `_agent_log` helper with standard Python `logging`.
- Keep diagnostics opt-in and non-secret:
  - Never log the raw API key.
  - Continue logging only masked/metadata fields.
- Update the existing Volces logging test so it asserts the old hardcoded/local debug-file pattern is absent and no direct file append logging remains.

### Frontend unused symbols

- Remove unused imports, functions, refs, computed values, and destructured context entries reported by `vue-tsc`.
- For `GroupChatComposer.vue`, remove only context fields not referenced by its template/script.
- For `WorkspaceContent.vue`, remove local helpers/state proven unused by the stricter type-check.
- For isolated unused functions in `LoginView.vue`, `MCPDetailView.vue`, and `MainView.vue`, remove the dead functions only if no template or code path references them.
- For `frontend/src/api/files.ts`, remove the unused `apiUrl` import.

## Verification

Run:

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest tests/test_call_api_tool.py tests/test_volces_icon_debug_logging.py -q'
/Users/ggd/.local/bin/rtk sh -lc 'cd frontend && ./node_modules/.bin/vue-tsc --noEmit --noUnusedLocals --noUnusedParameters'
/Users/ggd/.local/bin/rtk npm --prefix frontend run build
```

After backend tests, clean generated caches:

```bash
/Users/ggd/.local/bin/rtk sh -lc 'find backend -type d -name __pycache__ -prune -exec rm -rf {} +; find backend -type f -name "*.pyc" -delete'
```

## Rollback

- Revert the second-phase commit to restore prior logging helper and unused symbols.
- If frontend validation exposes behavior tied to a removed symbol, restore only that symbol and add a direct usage or test for the behavior.
