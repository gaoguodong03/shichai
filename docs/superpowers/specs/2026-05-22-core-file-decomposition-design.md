# Core File Decomposition Design

Date: 2026-05-22
Branch: codex/project-health-next-plans
Scope: design only; implementation requires a separate approved plan

## Problem

The remaining large files are not only large by line count; they hold multiple runtime boundaries in one file:

- `backend/app/api/group_chat.py`: 3714 lines
- `backend/app/api/settings.py`: 2009 lines
- `frontend/src/features/workspace/WorkspaceContent.vue`: 3183 lines
- `frontend/src/views/MainView.vue`: 3142 lines

This makes changes risky because request routing, persistence, runtime orchestration, UI state, streaming, and view composition are interleaved.

## Design goals

- Keep behavior unchanged in each extraction step.
- Move cohesive logic behind small modules with explicit interfaces.
- Add or preserve tests around each boundary before rewiring.
- Commit after each safe extraction.
- Prefer current project patterns over new frameworks.

## Recommended approach

Use a vertical, behavior-preserving decomposition instead of a broad rewrite.

### Phase A: backend settings split

Move the remaining `settings.py` responsibilities into focused modules:

- `backend/app/api/settings_presets.py`
  - Session preset CRUD
  - Scenario bundle export/import
  - Public scene share import
- `backend/app/api/settings_skills.py`
  - Skill list/create/update/delete
  - Skill zip import/export
  - Skill share link/publish
  - Skill part file management
- `backend/app/api/settings_requirements.py` only if requirement merge helpers still make `settings_skills.py` too large.

`backend/app/api/settings.py` should become a compatibility router or disappear after `routes.py` includes the new routers directly.

Validation focus:

- Existing settings import/share tests.
- Skill import/export tests.
- Sandbox requirements merge/prewarm tests.

### Phase B: group chat runtime boundary

Extract backend runtime helpers from `group_chat.py` in this order:

- `backend/app/api/group_chat_state.py`
  - group meta/history path loading and saving
  - runtime state registration/update/finish/cancel
  - session event publishing helpers
- `backend/app/agent/group_context.py`
  - message-to-context formatting
  - expert context formatting
  - discussion-goal normalization and title helpers
- `backend/app/agent/group_host_decision.py`
  - host decision parsing
  - forced mention / explicit agent extraction
  - recommendation heuristics
- `backend/app/agent/group_streaming.py`
  - stream orchestration helpers only after the previous extractions are tested

`group_chat.py` should remain the FastAPI route surface and call these modules.

Validation focus:

- `tests/test_sessions_api.py`
- group chat stream tests
- host-skill resolution tests
- stop/cancel stream tests

### Phase C: workspace frontend split

`WorkspaceContent.vue` is already partly split into group-chat components. Continue by extracting stateful composables:

- `frontend/src/features/workspace/composables/useGroupSessionState.ts`
  - load/save group detail
  - push refresh and restored-runtime polling
  - runtime status derivation
- `frontend/src/features/workspace/composables/useGroupComposerState.ts`
  - discussion goal
  - next prompt
  - attached files
  - at-mention state
- `frontend/src/features/workspace/composables/useGroupWorkspacePanel.ts`
  - workspace listing
  - preview/edit state
  - file operations

Keep `groupChatWorkspaceContext.ts` as the provider contract while moving implementation out of the `.vue` file.

Validation focus:

- `vue-tsc --noEmit --noUnusedLocals --noUnusedParameters`
- `npm --prefix frontend run build`
- Browser smoke test for group-chat composer, file modal, and workspace panel.

### Phase D: MainView shell split

Treat `MainView.vue` as a shell and move feature-specific state into composables:

- `frontend/src/views/composables/useSessionSidebar.ts`
  - session list
  - selected session
  - create/delete session
- `frontend/src/views/composables/useResourceNavigation.ts`
  - resource center navigation state
  - settings/resources selected item state
- `frontend/src/views/composables/useShareImportFlow.ts`
  - share import preview/confirm flow
  - upload/import bundle flow

Validation focus:

- `vue-tsc --noEmit --noUnusedLocals --noUnusedParameters`
- `npm --prefix frontend run build`
- Browser smoke test for login redirect, session selection, and resource/settings navigation.

## Alternatives considered

### Broad rewrite

Rejected. It would reduce line count faster but would blur behavior changes with extraction and make regression diagnosis difficult.

### Only delete dead code

Rejected as insufficient. The unused-symbol cleanup already reduced obvious dead code, but the remaining risk is boundary coupling, not just unused lines.

### Recommended vertical extraction

Chosen because it preserves current behavior, gives small reviewable commits, and lines up with the repo's existing direction: `features/*` on frontend and split settings modules on backend.

## Acceptance criteria

- Each extraction commit keeps tests/build passing.
- Route URLs and frontend workflows remain unchanged.
- `settings.py`, `group_chat.py`, `WorkspaceContent.vue`, and `MainView.vue` shrink through extracted responsibilities, not cosmetic movement.
- New modules have one clear responsibility and are directly testable.
- No runtime user data or secret files are reintroduced into Git.

## Open execution decision

Recommended first implementation target: Phase A, `settings_presets.py`, because the existing `AGENT.md` already identifies settings split as the next backend step and the route/test boundaries are clearer than the group stream runtime.
