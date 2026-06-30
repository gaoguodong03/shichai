"""Scene runtime entrypoint tests."""

from app.agent.group_orchestration_fsm import ORCHESTRATION_RECRUITMENT, ORCHESTRATION_SCENE
from app.agent.scene_runtime import SceneRuntime, pick_scene_host_skill


def test_pick_scene_host_skill_prefers_specialized_host_skill():
    assert pick_scene_host_skill(["group-host", "group-host-webnovel"]) == "group-host-webnovel"
    assert pick_scene_host_skill(["group-host"]) == "group-host"
    assert pick_scene_host_skill([]) == ""


def test_scene_runtime_resolves_virtual_host_and_hides_recruitment_list():
    runtime = SceneRuntime.from_group_session(
        session_id="g1",
        meta_item={
            "leader_agent_name": "四九场景主持",
            "agent_names": ["写作"],
            "host_config": {
                "leader_agent_name": "四九场景主持",
                "skill_name": "网文主持",
                "skill_directory": "group-host-webnovel",
            },
            "orchestration_profile": "scene",
        },
        agent_names=["写作"],
        agent_map={"写作": {"name": "写作"}},
        app_host_profile={"leader_agent_name": "四九", "skill_name": "群聊主持", "skill_directory": "group-host"},
        available_to_add=[{"name": "外部专家"}],
    )

    assert runtime.orchestration_profile == ORCHESTRATION_SCENE
    assert runtime.is_scene is True
    assert runtime.available_to_add_for_scheduler == []
    assert runtime.host_profile["name"] == "四九场景主持"
    assert runtime.host_profile["role"] == "群聊场景主持人"
    assert runtime.host_bubble_skill() == "group-host-webnovel"


def test_scene_runtime_keeps_recruitment_list_for_empty_room():
    available = [{"name": "外部专家"}]
    runtime = SceneRuntime.from_group_session(
        session_id="g1",
        meta_item={},
        agent_names=[],
        agent_map={},
        app_host_profile={"leader_agent_name": "四九", "skill_name": "群聊主持", "skill_directory": "group-host"},
        available_to_add=available,
    )

    assert runtime.orchestration_profile == ORCHESTRATION_RECRUITMENT
    assert runtime.available_to_add_for_scheduler == available


def test_scene_runtime_hides_recruitment_list_when_room_has_members():
    available = [{"name": "外部专家"}]
    runtime = SceneRuntime.from_group_session(
        session_id="g1",
        meta_item={"orchestration_profile": "recruitment"},
        agent_names=["写作"],
        agent_map={"写作": {"name": "写作"}},
        app_host_profile={"leader_agent_name": "四九", "skill_name": "群聊主持", "skill_directory": "group-host"},
        available_to_add=available,
    )

    assert runtime.orchestration_profile == ORCHESTRATION_RECRUITMENT
    assert runtime.available_to_add_for_scheduler == []


def test_scene_runtime_preserves_empty_host_skills():
    runtime = SceneRuntime.from_group_session(
        session_id="g1",
        meta_item={
            "leader_agent_name": "四九",
            "agent_names": ["写作"],
            "host_config": {"leader_agent_name": "四九"},
            "orchestration_profile": "scene",
        },
        agent_names=["写作"],
        agent_map={"写作": {"name": "写作"}},
        app_host_profile={"leader_agent_name": "四九", "skill_name": "", "skill_directory": ""},
        available_to_add=[],
    )

    assert runtime.host_profile["skills"] == []
    assert runtime.host_bubble_skill() == ""
