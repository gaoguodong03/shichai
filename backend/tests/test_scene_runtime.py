"""Scene runtime entrypoint tests."""

from app.agent.group_orchestration_fsm import ORCHESTRATION_RECRUITMENT, ORCHESTRATION_SCENE
from app.agent.scene_runtime import SceneRuntime, pick_scene_host_skill_id
from app.core.scene_host import VIRTUAL_SCENE_HOST_ID


def test_pick_scene_host_skill_prefers_specialized_host_skill():
    assert pick_scene_host_skill_id(["group-host", "group-host-webnovel"]) == "group-host-webnovel"
    assert pick_scene_host_skill_id(["group-host"]) == "group-host"
    assert pick_scene_host_skill_id([]) == "group-host"


def test_scene_runtime_resolves_virtual_host_and_hides_recruitment_list():
    runtime = SceneRuntime.from_group_session(
        session_id="g1",
        meta_item={
            "leader_agent_id": VIRTUAL_SCENE_HOST_ID,
            "agent_ids": ["agent-a"],
            "host_config": {
                "display_name": "四九场景主持",
                "skill_ids": ["group-host", "group-host-webnovel"],
            },
            "orchestration_profile": "scene",
        },
        agent_ids=["agent-a"],
        dha_map={"agent-a": {"agent_id": "agent-a", "name": "写作"}},
        app_host_profile={"display_name": "四九", "skill_ids": ["group-host"]},
        available_to_add=[{"agent_id": "agent-b", "name": "外部专家"}],
    )

    assert runtime.orchestration_profile == ORCHESTRATION_SCENE
    assert runtime.is_scene is True
    assert runtime.available_to_add_for_scheduler == []
    assert runtime.host_profile["agent_id"] == VIRTUAL_SCENE_HOST_ID
    assert runtime.host_profile["name"] == "四九场景主持"
    assert runtime.host_profile["role"] == "群聊场景主持人"
    assert runtime.host_bubble_skill_id() == "group-host-webnovel"


def test_scene_runtime_keeps_recruitment_list_for_empty_room():
    available = [{"agent_id": "agent-b", "name": "外部专家"}]
    runtime = SceneRuntime.from_group_session(
        session_id="g1",
        meta_item={},
        agent_ids=[],
        dha_map={},
        app_host_profile={"display_name": "四九", "skill_ids": ["group-host"]},
        available_to_add=available,
    )

    assert runtime.orchestration_profile == ORCHESTRATION_RECRUITMENT
    assert runtime.available_to_add_for_scheduler == available

