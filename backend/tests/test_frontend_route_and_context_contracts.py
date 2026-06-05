from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_router_exposes_canonical_business_routes():
    src = read("frontend/src/router/index.ts")
    assert "path: '/workspace'" in src
    assert "path: '/resources/:section?'" in src
    assert "path: '/settings/:section?'" in src
    assert "'agent'" in src
    assert "/resources/dha" not in src


def test_main_view_uses_route_as_navigation_source():
    src = read("frontend/src/views/MainView.vue")
    assert "const currentModule = computed<ModuleId>" in src
    assert "router.push(resourceRoutePath(id))" in src
    assert "router.push(settingsRoutePath(" in src
    assert "type ResourceSubModule = 'scenario' | 'agent' | 'skill' | 'mcp' | 'llm' | 'files'" in src


def test_settings_view_uses_route_section_for_active_panel():
    src = read("frontend/src/views/MainView.vue")
    assert "const settingsSection = computed<SettingsCategoryId>" in src
    assert "void router.push('/settings/app')" in src
    assert "<AppSettingsView v-if=\"settingsSection === 'app'\"" in src
    assert "settingsSection === c.id" in src
    assert "selectedId === 'app'" not in src


def test_group_chat_context_is_split_and_typed():
    src = read("frontend/src/features/workspace/components/group-chat/groupChatWorkspaceContext.ts")
    assert "Record<string, any>" not in src
    for name in [
        "GroupChatSessionContext",
        "GroupChatMessageContext",
        "GroupChatComposerContext",
        "GroupChatWorkspacePanelContext",
        "useGroupChatSessionContext",
        "useGroupChatMessageContext",
        "useGroupChatComposerContext",
        "useGroupChatWorkspacePanelContext",
    ]:
        assert name in src
    assert "useGroupChatWorkspaceContext" not in src


def test_group_chat_components_do_not_use_aggregate_context():
    files = [
        "frontend/src/features/workspace/WorkspaceContent.vue",
        "frontend/src/features/workspace/composables/useWorkspaceContentProviders.ts",
        "frontend/src/features/workspace/components/group-chat/GroupChatHeader.vue",
        "frontend/src/features/workspace/components/group-chat/GroupChatMessages.vue",
        "frontend/src/features/workspace/components/group-chat/GroupChatComposer.vue",
        "frontend/src/features/workspace/components/group-chat/GroupWorkspacePanel.vue",
    ]
    combined = "\n".join(read(path) for path in files)
    assert "provideGroupChatWorkspaceContext" not in combined
    assert "useGroupChatWorkspaceContext" not in combined
    assert "provideGroupChatSessionContext" in combined
    assert "provideGroupChatMessageContext" in combined
    assert "provideGroupChatComposerContext" in combined
    assert "provideGroupChatWorkspacePanelContext" in combined


def test_workspace_panel_logic_is_extracted_to_composable():
    src = read("frontend/src/features/workspace/WorkspaceContent.vue")
    provider = read("frontend/src/features/workspace/composables/useWorkspaceContentProviders.ts")
    composable = read("frontend/src/features/workspace/composables/useGroupWorkspacePanel.ts")
    assert "useWorkspaceContentProviders" in src
    assert "useGroupWorkspacePanel" in provider
    assert "export function useGroupWorkspacePanel" in composable
    for name in [
        "async function loadGroupWorkspace",
        "async function previewWorkspaceFile",
        "async function createGroupWorkspaceDir",
        "async function createGroupWorkspaceFile",
        "async function onGroupWorkspaceUpload",
        "function onGroupWorkspaceResizeMouseDown",
        "function toggleWorkspacePreview",
    ]:
        assert name not in src
        assert name in composable


def test_workspace_content_is_standard_size_shell():
    src = read("frontend/src/features/workspace/WorkspaceContent.vue")
    composable = read("frontend/src/features/workspace/composables/useWorkspaceContentProviders.ts")
    assert len(src.splitlines()) <= 1000
    assert "useWorkspaceContentProviders" in src
    assert "export function useWorkspaceContentProviders" in composable
    for name in [
        "async function sendGroupMessage",
        "async function loadGroupDetail",
        "function handleStreamMessageEvent",
        "function onAtInput",
        "async function loadShortcutPresets",
        "async function onInsertLocalFile",
    ]:
        assert name not in src
        assert name in composable
