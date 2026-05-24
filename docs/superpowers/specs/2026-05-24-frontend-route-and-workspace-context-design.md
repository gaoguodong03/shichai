# Frontend Route Boundary and Workspace Context Design

Date: 2026-05-24
Scope: design only; implementation requires a separate approved plan

## Problem

The frontend currently has two related coupling risks.

First, the application is deployed and used as a single origin, for example `http://10.129.236.188:8100/`, and the top-level Vue router only exposes a few coarse routes: `/`, `/scenario/run`, `/share/run`, and `/login`. Inside `MainView.vue`, business pages are selected by local state such as `currentModule`, `resourceSubModule`, and `selectedId`. As a result, workspace, resource center, and settings behave like separate pages to users but are not represented as stable URL boundaries in the frontend architecture.

Second, `WorkspaceContent.vue` still calls `provideGroupChatWorkspaceContext()` with a large object containing workspace props, emitters, message rendering helpers, composer state, file modal state, member actions, and streaming controls. The provider type is `Record<string, any>`, so group-chat child components can depend on unrelated state without a visible contract. This makes later UI work fragile because a local component change can silently rely on or break state owned by another area.

## Decision

Use one frontend application for now, but introduce real route boundaries and smaller provider contracts.

This avoids the cost of splitting into multiple frontend apps or bundles while still giving deployment, navigation, and code ownership clear seams. Future domain routing can map hostnames to these paths, but correctness should not depend on the hostname split.

## Goals

- Add stable frontend URLs for the main business areas:
  - `/workspace`
  - `/resources/scenario`
  - `/resources/dha`
  - `/resources/skill`
  - `/resources/mcp`
  - `/resources/llm`
  - `/resources/files`
  - `/settings/app`
  - `/settings/theme`
  - `/settings/secrets`
  - `/settings/account-security`
  - `/settings/sandbox`
- Keep existing user workflows and API URLs unchanged.
- Preserve `/`, `/scenario/run`, and `/share/run` compatibility.
- Make navigation state derive from the route instead of being the source of truth.
- Replace the single group-chat provider with smaller typed contexts grouped by responsibility.
- Keep `WorkspaceContent.vue` mounted when switching away from workspace if that is required to avoid interrupting active chat state.

## Non-goals

- Do not split the frontend into multiple Vite applications.
- Do not change backend API paths.
- Do not change authentication semantics or localStorage login key behavior.
- Do not redesign the visual layout.
- Do not extract all of `MainView.vue` or all of `WorkspaceContent.vue` in this phase.

## Route Design

`frontend/src/router/index.ts` should route all business area paths to `MainView.vue`:

- `/` redirects or normalizes to `/workspace` for logged-in users.
- `/workspace` renders the existing workspace module.
- `/resources/:section` renders the resource center with `section` constrained to the existing resource submodules.
- `/settings/:section` renders settings with `section` constrained to the existing settings categories.
- `/scenario/run` and `/share/run` continue to render `MainView.vue` because they already drive share/import flows from query parameters.
- `/login` remains unchanged.

`MainView.vue` should compute the active module and submodule from `useRoute()` rather than mutating `currentModule` as the primary state. Navigation handlers should call `router.push()` to the canonical path. The component may keep local state for selected list item ids, search text, resize width, and modal state.

Invalid resource or settings sections should be normalized to the default section:

- `/resources` and `/resources/unknown` normalize to `/resources/scenario`.
- `/settings` and `/settings/unknown` normalize to `/settings/app`.

This gives future reverse proxy rules an exact target without requiring separate apps:

- `workspace.example.com` can rewrite to `/workspace`.
- `resources.example.com` can rewrite to `/resources/scenario`.
- `settings.example.com` can rewrite to `/settings/app`.

## MainView State Boundary

`MainView.vue` should keep shell responsibilities only:

- render the left navigation
- render the middle column for the active route
- render the right content area
- preserve shared data needed by multiple sections, such as expert, skill, MCP, LLM, and session lists

Route watchers should replace the current `watch(currentModule)` and route-independent `watch(resourceSubModule)` behavior. Fetch behavior stays equivalent:

- entering `/workspace` fetches sessions, experts, and skills
- entering `/resources/*` fetches data needed by that resource section
- entering `/settings/*` sets the selected settings category from the route

The existing `selectedId` can remain a local selection state in this phase, but it must be reset or initialized from the route transition rules rather than from arbitrary module mutation.

## Workspace Context Design

Replace the single `GroupChatWorkspaceContext = Record<string, any>` with focused typed contexts. The contexts should be provided by `WorkspaceContent.vue` initially, so this phase can reduce hidden coupling without first moving all implementation into composables.

Recommended contexts:

- `GroupChatSessionContext`
  - session props and events
  - group detail
  - loading and error state
  - session title and archive/toc actions
- `GroupChatMessageContext`
  - display messages
  - avatar/name formatting
  - markdown rendering
  - message delete/save actions
  - tool result popover state
- `GroupChatComposerContext`
  - discussion goal
  - next prompt
  - attached files
  - at-mention state
  - send/stop/confirm actions
  - shortcut and member invitation actions used by the composer
- `GroupChatWorkspacePanelContext`
  - workspace panel visibility
  - file listing
  - preview/edit state
  - upload/create/rename/delete/download actions

Each child component should consume the smallest context that matches its responsibility:

- `GroupChatHeader.vue` consumes session-level and display helpers only.
- `GroupChatMessages.vue` consumes message-level state and actions only.
- `GroupChatComposer.vue` consumes composer state and the small display helpers it actually needs.
- `GroupWorkspacePanel.vue` consumes workspace-panel state only.

The old `useGroupChatWorkspaceContext()` should be removed after all child components migrate. During migration, a temporary compatibility context may exist only inside one commit if it keeps the change reviewable, but the completed phase should not leave the any-typed aggregate as the public contract.

## Testing Strategy

Use TDD for implementation.

Route tests should lock the new navigation contract before production changes:

- logged-in `/` lands on `/workspace`
- `/resources/skill` selects resource center and skill section
- `/settings/sandbox` selects settings and sandbox section
- invalid resource/settings sections normalize to defaults
- unauthenticated protected routes still redirect to `/login?redirect=...`

Provider tests should lock the new type and dependency boundary:

- `groupChatWorkspaceContext.ts` no longer exports `Record<string, any>`
- each group-chat component imports only the context hook for its responsibility
- no group-chat component imports the removed aggregate hook after migration

Build validation should include:

- `npm --prefix frontend run build`
- focused static search that confirms no remaining `useGroupChatWorkspaceContext()` calls

Browser smoke validation should cover:

- open `/workspace` and confirm the workspace shell renders
- navigate to `/resources/skill` and confirm the resource center renders the skill section
- navigate to `/settings/sandbox` and confirm the settings shell renders sandbox settings
- return to `/workspace` and confirm workspace navigation still works

## Rollout

Implement in two small phases.

Phase 1: route boundary.

- Add route constants and route normalization.
- Make navigation handlers push canonical URLs.
- Replace local `currentModule` and `resourceSubModule` as source-of-truth state with computed route-derived state.
- Keep visual layout and backend API calls unchanged.

Phase 2: workspace context boundary.

- Define typed focused contexts.
- Update child components one by one to consume the smallest context.
- Remove the aggregate any context after migration.
- Run build and static checks.

## Acceptance Criteria

- `/workspace`, `/resources/:section`, and `/settings/:section` are directly openable URLs.
- Existing `/scenario/run`, `/share/run`, and `/login` behavior remains unchanged.
- Navigation buttons update the browser URL instead of only mutating local module state.
- `WorkspaceContent.vue` no longer exposes group-chat child dependencies through one `Record<string, any>` provider.
- Group-chat child components consume focused typed contexts.
- Frontend build passes.
- Static checks show no remaining aggregate group-chat context hook usage.
