from __future__ import annotations

import re
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
    main = read("frontend/src/views/MainView.vue")
    navigation = read("frontend/src/features/shell/mainNavigation.ts")
    lifecycle = read("frontend/src/features/shell/useMainModuleLifecycle.ts")
    assert "useMainRouteState(route)" in main
    assert "const currentModule = computed<ModuleId>" in navigation
    assert "router.push(resourceRoutePath(id))" in lifecycle
    assert "router.push(settingsRoutePath(" in main
    assert "type ResourceSubModule = 'scenario' | 'agent' | 'skill' | 'mcp' | 'llm' | 'files'" in navigation


def test_settings_view_uses_route_section_for_active_panel():
    main = read("frontend/src/views/MainView.vue")
    navigation = read("frontend/src/features/shell/mainNavigation.ts")
    lifecycle = read("frontend/src/features/shell/useMainModuleLifecycle.ts")
    settings_list = read("frontend/src/features/shell/MainSettingsList.vue")
    assert "const settingsSection = computed<SettingsCategoryId>" in navigation
    assert "void router.push('/settings/app')" in lifecycle
    assert "<AppSettingsView v-if=\"settingsSection === 'app'\"" in main
    assert "settingsSection === category.id" in settings_list
    assert "selectedId === 'app'" not in main


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


def test_frontend_runtime_and_e2e_do_not_use_legacy_session_or_end_fields():
    files = [
        "frontend/src/features/workspace/composables/useGroupOrchestrationState.ts",
        "frontend/src/features/workspace/composables/useGroupStreamEvents.ts",
        "frontend/e2e/fixtures/mockApi.ts",
        "frontend/e2e/workspace.spec.ts",
        "frontend/e2e/resources-scenario-expert.spec.ts",
        "frontend/e2e/settings.spec.ts",
    ]
    combined = "\n".join(read(path) for path in files)
    for legacy in [
        "leader_agent" + "_name",
        "host_" + "config",
        "orchestration" + "_profile",
        "resume_target_agent_name",
        "required_user_fields",
        "interrupt_reason",
        "interrupted",
    ]:
        assert legacy not in combined


def test_frontend_chat_stream_api_does_not_expose_legacy_start_event():
    src = read("frontend/src/api/chat.ts")
    assert "onStart" not in src
    assert "eventType === 'start'" not in src


def test_frontend_member_identity_uses_expert_name_without_agent_id_aliases():
    files = [
        "frontend/src/features/workspace/composables/useGroupOrchestrationState.ts",
        "frontend/src/features/workspace/composables/useGroupMembers.ts",
        "frontend/src/features/workspace/composables/useShortcutPresets.ts",
        "frontend/src/features/workspace/composables/useWorkspaceContentProviders.ts",
        "frontend/src/features/shell/SessionMemberAvatars.vue",
    ]
    combined = "\n".join(read(path) for path in files)

    for legacy_identity_fallback in [
        "toAgentStyleName",
        "buildExpertAliasMap",
        "item.agent_name || item.name",
        "d.agent_name || d.name",
        "x.agent_name || x.name",
        "x?.agent_name || x?.name",
        "(item.agent_name || item.name)",
        "agent-[0-9a-f]",
        "agent-scene-host",
    ]:
        assert legacy_identity_fallback not in combined


def test_frontend_resource_imports_do_not_send_legacy_conflict_controls():
    combined = "\n".join(
        read(path)
        for path in [
            "frontend/src/features/resources/useBundleImports.ts",
            "frontend/src/features/resources/useZipResourceImports.ts",
            "frontend/e2e/fixtures/mockApi.ts",
            "frontend/e2e/resources-scenario-expert.spec.ts",
            "frontend/e2e/resources-skill-mcp-llm.spec.ts",
        ]
    )
    for legacy_control in [
        "fd.append('name_conflict'",
        "fd.append('overwrite_experts'",
        "fd.append('overwrite_skills'",
        "fd.append('mcp_skip_existing'",
    ]:
        assert legacy_control not in combined


def test_frontend_skill_reference_identity_uses_directory_name_not_display_name():
    agent_view = read("frontend/src/features/resources/AgentView.vue")
    scenario_editor = read("frontend/src/features/resources/useScenarioEditor.ts")

    for forbidden in [
        "seen.has(name)",
        "seen.add(name)",
        "if (!directoryName || !name || seen.has(directoryName)) continue",
        "x.directory_name === directoryName || x.name === name",
        "x.directory_name !== directoryName && x.name !== name",
        "s.directory_name === ref.directory_name || s.name === ref.name",
    ]:
        assert forbidden not in agent_view

    for forbidden in [
        "s.directory_name === skill.directory_name || s.name === skill.name",
        "s.directory_name === directoryName || s.name === name",
    ]:
        assert forbidden not in scenario_editor

    assert "{{ s.name || s.directory_name }}" in agent_view


def test_frontend_resource_imports_do_not_model_legacy_skip_summaries():
    combined = "\n".join(
        read(path)
        for path in [
            "frontend/src/features/resources/useBundleImports.ts",
            "frontend/src/features/resources/useZipResourceImports.ts",
            "frontend/e2e/fixtures/mockApi.ts",
            "frontend/e2e/resources-scenario-expert.spec.ts",
            "frontend/e2e/resources-skill-mcp-llm.spec.ts",
        ]
    )

    for legacy_field in [
        "would_skip_skills",
        "skipped_by_name",
        "skills_skipped",
        "mcp_failed",
        "tools_failed",
        "mcp_skipped",
        "skills_kept",
        "kept_agent_names",
        "kept_existing_names",
    ]:
        assert legacy_field not in combined


def test_e2e_stream_mocks_use_current_sse_event_payloads():
    files = [
        "frontend/e2e/fixtures/mockApi.ts",
        "frontend/e2e/workspace.spec.ts",
        "frontend/e2e/resources-scenario-expert.spec.ts",
        "frontend/e2e/settings.spec.ts",
    ]
    combined = "\n".join(read(path) for path in files)

    assert "['keepalive', { ok: true }]" not in combined
    assert "event: route\\ndata: ${JSON.stringify({ agent_name:" not in combined
    assert "event: end\\ndata: ${JSON.stringify({ waiting_for_user:" not in combined
    for payload in re.findall(r"event: route\\ndata: \$\{JSON\.stringify\(([\s\S]*?)\)\}\\n\\n", combined):
        assert "type: 'route'" in payload
        assert "run_id:" in payload
    for payload in re.findall(r"event: end\\ndata: \$\{JSON\.stringify\(([\s\S]*?)\)\}\\n\\n", combined):
        assert "type: 'end'" in payload
        assert "run_id:" in payload
        assert "phase:" in payload
    for payload in re.findall(r"event: message\\ndata: \$\{JSON\.stringify\(([\s\S]*?)\)\}\\n\\n", combined):
        assert "created_at" in payload
        assert "attachments: []" not in payload
    mock_api = read("frontend/e2e/fixtures/mockApi.ts")
    assert "message: { content: '历史回复：这里可以继续追问。' }" in mock_api
    assert "message: { content: answer }" in mock_api
    assert "created_at?: string" not in mock_api
    assert "created_at: string" in mock_api
    assert "skill_result?: Record<string, unknown>" not in mock_api
    assert "type SkillResult = {" in mock_api
    assert "skill_result?: SkillResult" in mock_api


def test_e2e_message_fixtures_use_storage_timestamp_format():
    files = [
        "frontend/e2e/fixtures/mockApi.ts",
        "frontend/e2e/workspace.spec.ts",
        "frontend/e2e/resources-scenario-expert.spec.ts",
        "frontend/e2e/resources-skill-mcp-llm.spec.ts",
        "frontend/e2e/settings.spec.ts",
    ]
    combined = "\n".join(read(path) for path in files)

    assert not re.search(r"created_at:\s*['\"]\d{4}-\d{2}-\d{2}T", combined)
    assert not re.search(r'"created_at"\s*:\s*"\d{4}-\d{2}-\d{2}T', combined)


def test_e2e_chat_stream_mock_requires_frontend_client_message_id_without_fallback():
    mock_api = read("frontend/e2e/fixtures/mockApi.ts")
    chat_handler = re.search(
        r"if \(chatStreamMatch && method === 'POST'\) \{([\s\S]*?)\n    \}",
        mock_api,
    )
    assert chat_handler is not None
    request_type = re.search(r"const body = readBody<\{([\s\S]*?)\}>\(route\)", chat_handler.group(1))
    assert request_type is not None
    assert "client_message_id: string" in request_type.group(1)
    assert "client_message_id?: string" not in request_type.group(1)
    assert "const clientMessageId = String(body.client_message_id || '').trim()" in chat_handler.group(1)
    assert "if (!clientMessageId) return json(route, { detail: 'client_message_id is required' }, 422)" in chat_handler.group(1)

    persisted_user_message = re.search(
        r"session\.messages\.push\(\{[\s\S]*?speaker: \{ type: 'user' \},[\s\S]*?created_at: now,[\s\S]*?\n\s*\}\)",
        chat_handler.group(1),
    )
    assert persisted_user_message is not None
    assert "client_message_id: clientMessageId," in persisted_user_message.group(0)
    assert "body.client_message_id ||" not in persisted_user_message.group(0)
    assert "client-${Date.now()}" not in persisted_user_message.group(0)
    assert "attachments: body.attachments || []" not in persisted_user_message.group(0)
    assert "target_agent_name: body.target_agent_name || null" not in persisted_user_message.group(0)
    assert "if (body.attachments?.length) messageBody.attachments = body.attachments" in chat_handler.group(1)
    assert "if (targetAgentName) messageBody.target_agent_name = targetAgentName" in chat_handler.group(1)


def test_e2e_host_profile_mock_uses_host_name_not_display_name():
    files = [
        "frontend/e2e/fixtures/mockApi.ts",
        "frontend/e2e/settings.spec.ts",
        "frontend/e2e/workspace.spec.ts",
    ]
    combined = "\n".join(read(path) for path in files)

    assert "hostProfile.display_name" not in combined
    assert "state.hostProfile.display_name" not in combined
    assert "display_name || state.hostProfile.name" not in combined


def test_frontend_chat_once_contract_does_not_read_interrupted_flag():
    files = [
        "frontend/src/api/chat.ts",
        "frontend/src/features/workspace/composables/useGroupChatStreamRunner.ts",
    ]
    combined = "\n".join(read(path) for path in files)

    assert "interrupted" not in combined


def test_frontend_stream_runner_does_not_auto_fallback_to_chat_once():
    runner = read("frontend/src/features/workspace/composables/useGroupChatStreamRunner.ts")

    assert "chatOnceRequest" not in runner
    assert "/chat once fallback" not in runner
    assert "非流式补偿" not in runner
    assert "SSE 请求失败，准备非流式补偿" not in runner
    assert "deps.setStreamingPhase('failed', sessionId)" in runner


def test_frontend_chat_api_omits_empty_optional_request_fields():
    src = read("frontend/src/api/chat.ts")

    assert "attachments: payload.attachments || []" not in src
    assert "target_agent_name: payload.target_agent_name || null" not in src
    assert "if (payload.attachments?.length) body.attachments = payload.attachments" in src
    assert "if (targetAgentName) body.target_agent_name = targetAgentName" in src


def test_frontend_local_session_messages_include_created_at():
    composer = read("frontend/src/features/workspace/composables/useGroupComposerActions.ts")
    time_format = read("frontend/src/features/workspace/messageTimeFormat.ts")
    assert "currentStorageTimestamp" in composer
    assert "getUTCFullYear" in time_format
    assert "getFullYear()" not in time_format
    optimistic_user = re.search(
        r"const userMsg: GroupMessage = \{[\s\S]*?client_message_id: clientMessageId,[\s\S]*?\n\s*\}",
        composer,
    )
    assert optimistic_user is not None
    assert "created_at:" in optimistic_user.group(0)
    assert "message: { content: msg, attachments, target_agent_name: targetAgentName }" not in composer
    assert "if (attachments.length) messageBody.attachments = attachments" in composer
    assert "if (targetAgentName) messageBody.target_agent_name = targetAgentName" in composer
    assert "speaker: { type: 'host', agent_name: '系统主持人' }" in composer
    assert "speaker: { type: 'host' }, message: { content }" not in composer


def test_frontend_does_not_parse_file_references_from_message_content():
    files = [
        "frontend/src/features/workspace/composables/useGroupMessageList.ts",
        "frontend/src/features/workspace/components/group-chat/GroupChatMessages.vue",
        "frontend/src/features/workspace/composables/useGroupOrchestrationState.ts",
        "frontend/src/features/workspace/composables/useGroupStreamEvents.ts",
        "frontend/src/features/workspace/composables/groupMessageDraft.ts",
    ]
    combined = "\n".join(read(path) for path in files)
    for forbidden in [
        "extractUserFileReferenceNames",
        "matchAll(/【文件引用",
        "【文件引用：[^】]+】",
        "fileRefMatches",
        "detectHostTakeoverIntent",
    ]:
        assert forbidden not in combined


def test_frontend_user_message_display_does_not_strip_legacy_discussion_goal_marker():
    src = read("frontend/src/features/workspace/composables/useGroupMessageList.ts")
    for forbidden in [
        "stripDiscussionGoalForDisplay",
        "formatUserBubbleForDisplay",
        "【讨论目标】",
        "raw.startsWith(prefix)",
    ]:
        assert forbidden not in src
    assert "return messageSpeakerType(msg) === 'user' ? content : agentBodyContent(content)" in src


def test_frontend_message_rendering_does_not_read_legacy_debug_tool_trace():
    files = [
        "frontend/src/features/workspace/composables/useGroupMessageList.ts",
        "frontend/src/features/workspace/components/group-chat/GroupChatMessages.vue",
        "frontend/src/features/workspace/components/group-chat/groupChatWorkspaceContext.ts",
        "frontend/src/features/workspace/composables/useWorkspaceContentProviders.ts",
    ]
    combined = "\n".join(read(path) for path in files)
    for forbidden in [
        "debug",
        "tool_trace",
        "member_joined",
        "member_left",
        "isMemberJoinedMessage",
    ]:
        assert forbidden not in combined


def test_frontend_group_detail_loader_only_accepts_status_ok_data_envelope():
    src = read("frontend/src/features/workspace/composables/useGroupDetailLoader.ts")
    assert "if (Array.isArray(body))" not in src
    assert "o.id != null" not in src
    assert "o.status === 'ok' && o.data != null && typeof o.data === 'object'" in src


def test_frontend_restored_runtime_phase_comes_only_from_backend_runtime():
    src = read("frontend/src/features/workspace/composables/useGroupDetailLoader.ts")
    assert "phase: phase || 'routing'" not in src
    assert "const phase = String(rt.phase || '').trim()" in src


def test_frontend_markdown_renderer_does_not_parse_tool_calls_from_message_content():
    src = "\n".join([
        read("frontend/src/features/workspace/workspaceMessageUtils.ts"),
        read("frontend/src/features/workspace/WorkspaceContent.css"),
    ])
    for forbidden in [
        "tool_call",
        "wrapToolCallPreBlocks",
        "data-tool=",
        "group-chat-tool-call",
    ]:
        assert forbidden not in src


def test_frontend_does_not_restore_invites_from_history_messages():
    files = [
        "frontend/src/features/workspace/composables/useGroupOrchestrationState.ts",
        "frontend/src/features/workspace/composables/useWorkspaceContentProviders.ts",
    ]
    combined = "\n".join(read(path) for path in files)
    for forbidden in [
        "handleLoadedMessages",
        "lastHost",
        "suggested_add_agent_names?: string[]",
        "extractSuggestedAddNames(lastMsg",
    ]:
        assert forbidden not in combined


def test_frontend_only_consumes_current_invite_field():
    src = read("frontend/src/features/workspace/composables/useGroupOrchestrationState.ts")
    assert "suggested_add_agent_names" in src
    assert "auto_invited_agent_names" not in src


def test_frontend_does_not_send_legacy_next_prompt_channel():
    files = [
        "frontend/src/features/workspace/components/group-chat/GroupChatComposer.vue",
        "frontend/src/features/workspace/components/group-chat/groupChatWorkspaceContext.ts",
        "frontend/src/features/workspace/composables/groupMessageDraft.ts",
        "frontend/src/features/workspace/composables/useGroupComposerActions.ts",
        "frontend/src/features/workspace/composables/useGroupAtMentions.ts",
        "frontend/src/features/workspace/composables/useGroupMessageList.ts",
        "frontend/src/features/workspace/composables/useGroupOrchestrationState.ts",
        "frontend/src/features/workspace/composables/useGroupStreamEvents.ts",
        "frontend/src/features/workspace/composables/useWorkspaceContentProviders.ts",
        "backend/app/agent/group_context.py",
    ]
    combined = "\n".join(read(path) for path in files)
    for forbidden in [
        "groupNextPrompt",
        "nextPrompt",
        "next_prompt",
        "【给下一 Agent 的提示】",
        "下一专家提示词",
    ]:
        assert forbidden not in combined


def test_frontend_sends_structured_target_agent_without_at_text_control():
    composer = read("frontend/src/features/workspace/components/group-chat/GroupChatComposer.vue")
    composer_actions = read("frontend/src/features/workspace/composables/useGroupComposerActions.ts")
    at_mentions = read("frontend/src/features/workspace/composables/useGroupAtMentions.ts")
    provider = read("frontend/src/features/workspace/composables/useWorkspaceContentProviders.ts")

    assert "输入 @ 可指定专家" not in composer
    assert "groupTargetAgentName" in provider
    assert "target_agent_name" in composer_actions
    assert "groupTargetAgentName.value = opt.id" in at_mentions
    assert "`@${" not in at_mentions
    assert "insertText = " not in at_mentions


def test_e2e_mock_rejects_legacy_runtime_request_fields():
    mock_api = read("frontend/e2e/fixtures/mockApi.ts")

    assert "function rejectUnexpectedKeys(" in mock_api
    assert "function validateChatAttachments(" in mock_api
    assert "attachment.type !== 'workspace_file'" in mock_api
    assert "path.startsWith('/') || path.split('/').includes('..')" in mock_api
    assert "Attachment does not exist" in mock_api
    assert "rejectUnexpectedKeys(route, body, ['title', 'agent_names', 'host'])" in mock_api
    assert "rejectUnexpectedKeys(route, body, ['title', 'agent_names', 'add_agent_names', 'remove_agent_names', 'host'])" in mock_api
    assert "rejectUnexpectedKeys(route, body, ['message', 'client_message_id', 'attachments', 'target_agent_name'])" in mock_api
    assert "if (validateChatAttachments(route, state, id, body.attachments || [])) return" in mock_api
    assert "const clientMessageId = String(body.client_message_id || '').trim()" in mock_api
    assert "client_message_id: clientMessageId" in mock_api
    assert "const targetAgentName = String(body.target_agent_name || '').trim()" in mock_api
    assert "const activeAgentNames = (session.agent_names || []).filter((name) => state.agents.some((agent) => agent.name === name))" in mock_api
    assert "if (targetAgentName && !activeAgentNames.includes(targetAgentName))" in mock_api
    assert "messageBody.target_agent_name = targetAgentName" in mock_api
    assert "if (!activeAgentNames.length)" in mock_api
    assert "suggested_add_agent_names: suggestedAddAgentNames" in mock_api
    assert "speaker: { type: 'host', agent_name: hostName }" in mock_api


def test_frontend_scenario_host_skill_restore_uses_directory_identity():
    """Scenario host Skill references must survive without display-name snapshots."""
    src = read("frontend/src/features/resources/useScenarioEditor.ts")

    assert "const directoryName = String((raw as any).skill_directory || '')" in src
    assert "if (!directoryName || !name) return null" not in src
    assert "if (!directoryName) return null" in src
    assert "return { name: name || current?.name || directoryName, directory_name: directoryName }" in src


def test_frontend_scenario_session_create_strips_display_only_host_skill_name():
    """Scenario resources keep host.skill_name, but session creation host snapshots do not."""
    src = read("frontend/src/features/workspace/composables/useShortcutPresets.ts")
    helper = re.search(r"function sessionHostFromScenarioPreset[\s\S]*?\n  \}", src)

    assert helper is not None
    assert "skill_directory" in helper.group(0)
    assert "skill_name" not in helper.group(0)
    assert "host: sessionHostFromScenarioPreset(p.host)" in src
    assert "host: p.host" not in src


def test_frontend_stores_backend_phase_values_in_stream_state():
    files = [
        "frontend/src/features/workspace/composables/useGroupComposerActions.ts",
        "frontend/src/features/workspace/composables/useGroupChatStreamRunner.ts",
        "frontend/src/features/workspace/composables/useGroupDetailLoader.ts",
        "frontend/src/features/workspace/composables/useGroupStreamRuntime.ts",
        "frontend/src/features/workspace/composables/useGroupStreamEvents.ts",
        "frontend/src/features/workspace/composables/useGroupOrchestrationState.ts",
    ]
    combined = "\n".join(read(path) for path in files)
    for forbidden in [
        "phase: '正在",
        "phase: '文件引用",
        "phase: '技能任务",
        "phase: '等待你",
        "phase: '已暂停",
        "phase: '已停止",
        "beginGroupStream(id, '正在",
        "beginGroupStream(detail.id, '正在",
        "setStreamingPhase('连接",
        "setStreamingPhase(errText",
        "phase: STREAMING_STATUS_DEFAULT",
        "phase === 'tool_running' ?",
    ]:
        assert forbidden not in combined


def test_frontend_does_not_auto_route_from_end_suggested_next_speaker():
    src = read("frontend/src/features/workspace/composables/useGroupStreamEvents.ts")
    end_handler = re.search(
        r"function handleStreamEndEvent\([\s\S]*?\n  \}",
        src,
    )

    assert end_handler is not None
    assert "groupSuggestedNextSpeaker.value =" in end_handler.group(0)
    assert "confirmGroupNext(" not in end_handler.group(0)
    assert "nextTick(() => confirmGroupNext" not in src


def test_frontend_waiting_state_follows_end_waiting_for_user():
    src = read("frontend/src/features/workspace/composables/useGroupStreamEvents.ts")
    end_handler = re.search(
        r"function handleStreamEndEvent\([\s\S]*?\n  \}",
        src,
    )

    assert end_handler is not None
    assert "if (endData.waiting_for_user)" in end_handler.group(0)
    assert "groupWaitingForUser.value = true" in end_handler.group(0)
    assert "groupWaitingForUser.value = !!endData.turns_limit_reached" not in end_handler.group(0)


def test_frontend_local_streaming_placeholders_use_canonical_message_body():
    src = read("frontend/src/features/workspace/composables/useGroupStreamEvents.ts")

    for payload in re.findall(r"message: \{ content: [^}]+ \}", src):
        assert "attachments: []" not in payload


def test_frontend_and_e2e_do_not_use_non_contract_turn_limit_end_field():
    files = [
        "frontend/src/features/workspace/composables/useGroupStreamEvents.ts",
        "frontend/src/features/workspace/components/group-chat/GroupChatStatusBars.vue",
        "frontend/src/features/workspace/components/group-chat/GroupChatComposer.vue",
        "frontend/e2e/workspace.spec.ts",
    ]
    combined = "\n".join(read(path) for path in files)
    assert "turns_limit_reached" not in combined
    assert "groupTurnLimitReached" not in combined
    assert "已达轮次上限" not in combined


def test_frontend_does_not_infer_runtime_phase_from_route_or_message_events():
    src = read("frontend/src/features/workspace/composables/useGroupStreamEvents.ts")
    route_handler = re.search(
        r"function showStreamingRoutePlaceholder\([\s\S]*?\n  \}",
        src,
    )
    message_handler = re.search(
        r"function handleStreamMessageEvent\([\s\S]*?\n  \}",
        src,
    )

    assert route_handler is not None
    assert message_handler is not None
    assert "phase:" not in route_handler.group(0)
    assert "patchGroupStreamState(activeSessionId(sessionId), { phase: 'assistant_generating' })" not in message_handler.group(0)


def test_frontend_progress_events_do_not_append_message_body_text():
    """Progress is runtime status only; final body text must arrive through message events."""
    runner = read("frontend/src/features/workspace/composables/useGroupChatStreamRunner.ts")
    stream_events = read("frontend/src/features/workspace/composables/useGroupStreamEvents.ts")
    composer = read("frontend/src/features/workspace/composables/useGroupComposerActions.ts")
    providers = read("frontend/src/features/workspace/composables/useWorkspaceContentProviders.ts")

    assert "appendStreamingContent" not in runner
    assert "appendStreamingContent" not in stream_events
    assert "appendStreamingContent" not in composer
    assert "appendStreamingContent" not in providers
    assert "data?.text != null" not in runner


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
    assert len(composable.splitlines()) <= 900
    assert "useWorkspaceContentProviders" in src
    assert "export function useWorkspaceContentProviders" in composable


def test_main_view_stays_as_shell_without_thin_helper_files():
    main = read("frontend/src/views/MainView.vue")
    navigation = read("frontend/src/features/shell/MainNavigationRail.vue")
    new_session = read("frontend/src/features/shell/MainNewSessionMenu.vue")
    component = read("frontend/src/features/shell/SessionMemberAvatars.vue")
    collections = read("frontend/src/features/resources/useResourceCollections.ts")

    assert len(main.splitlines()) <= 1500
    assert "MainNavigationRail" in main
    assert "MainNewSessionMenu" in main
    assert "MainSettingsList" in main
    assert "new-session-menu" in new_session
    assert "resourceChildren" in navigation
    assert "settingsRoutePath" not in navigation
    assert "SessionMemberAvatars" in main
    assert "useGroupSessions" in main
    assert "useResourceCollections" in main
    assert "useScenarioEditor" in main
    assert "useMainModuleLifecycle" in main
    assert "v-for=\"avatar in visibleAvatars\"" in component
    assert "dhaAvatarImgUrlForSession(" not in component.split("<script", 1)[0]
    assert "function syncSelectedResourceId" in collections
    assert not (ROOT / "frontend/src/features/resources/resourceSelection.ts").exists()
    assert not (ROOT / "frontend/src/features/shell/sessionAvatarDisplay.ts").exists()


def test_skill_detail_view_extracts_header_and_sidebar_shells():
    src = read("frontend/src/features/resources/SkillDetailView.vue")
    header = read("frontend/src/features/resources/SkillDetailHeader.vue")
    sidebar = read("frontend/src/features/resources/SkillPartSidebar.vue")

    assert len(src.splitlines()) <= 1250
    assert "SkillDetailHeader" in src
    assert "SkillPartSidebar" in src
    assert "add-part-file" in header
    assert "sidebarEntries" in sidebar


def test_llm_settings_view_extracts_advanced_params_panel():
    src = read("frontend/src/features/resources/LLMSettingsView.vue")
    panel = read("frontend/src/features/resources/LLMAdvancedParamsPanel.vue")

    assert len(src.splitlines()) <= 800
    assert "LLMAdvancedParamsPanel" in src
    assert "enable_thinking" in panel
    assert "gemini_thinking_level" in panel


def test_app_entry_has_no_local_debug_ingest_probe():
    src = read("frontend/src/App.vue")
    assert "127.0.0.1:7242" not in src
    assert "/ingest/" not in src
    assert "X-Debug-Session-Id" not in src
