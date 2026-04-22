"""pytest 公共 fixture：避免 UserContext 缓存跨用例指向旧路径。

第一层 ``layer1_core`` 范围（与 scripts/test-layer1.sh 一致）：
编排与场景、群聊协议与记忆、沙箱服务、鉴权、工作区与文件、graph/工具/MCP 网关等。
不包含：全 HTTP 路由表、全部 tools、全部 MCP 子模块、纯运行时路径的系统性覆盖。

新加 ``test_*.py`` 若应纳入第一层，请把模块名（不含 .py）加入 ``LAYER1_CORE_MODULES``。
"""

from __future__ import annotations

from pathlib import Path

import pytest

# tests/<stem>.py  -> 纳入 ``pytest -m layer1_core`` / test-layer1.sh 后端步骤
LAYER1_CORE_MODULES: frozenset[str] = frozenset(
    {
        "test_auth_sqlite",
        "test_call_api_tool",
        "test_dha_api",
        "test_dha_import_validate",
        "test_expert_bundle",
        "test_expert_self_awareness_prompt",
        "test_file_ref_and_gateway",
        "test_graph_tool_resolution",
        "test_group_chat_group_memory",
        "test_group_chat_stream_protocol",
        "test_group_memory_store",
        "test_group_orchestration_fsm",
        "test_host_plan",
        "test_host_takeover",
        "test_llm_config",
        "test_orchestration_contracts",
        "test_orchestrator_audit",
        "test_public_scenario_api",
        "test_scene_scheduler",
        "test_scenario_bundle",
        "test_sessions_api",
        "test_session_preset_validate",
        "test_simple_agent_tool_intent",
        "test_sandbox_service",
        "test_workspace_files",
    }
)


def _item_test_module_stem(item: pytest.Item) -> str:
    path_part = item.nodeid.split("::", 1)[0]
    return Path(path_part).stem


def pytest_collection_modifyitems(config, items: list[pytest.Item]) -> None:
    for item in items:
        if _item_test_module_stem(item) in LAYER1_CORE_MODULES:
            item.add_marker(pytest.mark.layer1_core, append=False)


@pytest.fixture(autouse=True)
def _clear_user_context_cache():
    from app.core import user_context as uc

    uc._user_ctx_cache.clear()
    yield
    uc._user_ctx_cache.clear()
