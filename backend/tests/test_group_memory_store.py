"""群聊记忆文件存储与派发上下文测试。"""
from pathlib import Path

from app.agent.group_memory_store import append_turn_log, upsert_facts, build_dispatch_context


def test_append_turn_log_with_rotation(tmp_path: Path):
    session_id = "group-test"
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)

    for i in range(5):
        append_turn_log(
            session_id=session_id,
            workspace_root=ws,
            max_logs=3,
            turn_record={
                "dha_id": f"dha-{i}",
                "timestamp": f"2026-01-01T00:00:0{i}+00:00",
                "discussion_goal": "测试目标",
                "input_prompt_summary": f"input-{i}",
                "response_summary": f"output-{i}",
            },
        )

    logs_dir = ws / "memory" / "logs"
    logs = sorted(logs_dir.glob("*.md"))
    assert len(logs) == 3
    assert all("Turn Log" in p.read_text(encoding="utf-8") for p in logs)


def test_upsert_facts_dedup_and_cap(tmp_path: Path):
    session_id = "group-test"
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)

    upsert_facts(session_id, ["事实A", "事实B"], max_facts=3, workspace_root=ws)
    facts = upsert_facts(session_id, ["事实B", "事实C", "事实D"], max_facts=3, workspace_root=ws)

    assert facts == ["事实B", "事实C", "事实D"]
    facts_file = ws / "memory" / "facts.md"
    content = facts_file.read_text(encoding="utf-8")
    assert "- 事实A" not in content
    assert "- 事实D" in content


def test_build_dispatch_context_prefers_related_logs(tmp_path: Path):
    session_id = "group-test"
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)

    upsert_facts(session_id, ["用户希望输出周报", "需包含图表"], workspace_root=ws)
    append_turn_log(
        session_id=session_id,
        workspace_root=ws,
        turn_record={
            "dha_id": "dha-data",
            "timestamp": "2026-01-01T00:00:01+00:00",
            "discussion_goal": "生成数据周报",
            "response_summary": "已完成图表草稿并给出统计摘要",
        },
    )
    append_turn_log(
        session_id=session_id,
        workspace_root=ws,
        turn_record={
            "dha_id": "dha-design",
            "timestamp": "2026-01-01T00:00:02+00:00",
            "discussion_goal": "生成封面图",
            "response_summary": "提供了封面风格建议",
        },
    )

    ctx = build_dispatch_context(
        session_id=session_id,
        workspace_root=ws,
        target_dha_id="dha-data",
        goal="数据 周报",
        k=1,
    )
    assert ctx["has_memory"] is True
    assert "关键事实" in ctx["rendered"]
    assert len(ctx["logs"]) == 1
    assert "dha-data" in ctx["logs"][0]["excerpt"]
