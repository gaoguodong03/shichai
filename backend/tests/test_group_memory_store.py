"""群聊记忆文件存储与派发上下文测试。"""
from pathlib import Path

from app.agent.group_memory_store import (
    upsert_facts,
    build_dispatch_context,
    upsert_index_entries,
)


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


def test_build_dispatch_context_uses_only_facts(tmp_path: Path):
    session_id = "group-test"
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)

    upsert_facts(session_id, ["用户希望输出周报", "需包含图表"], workspace_root=ws)
    old_logs = ws / "memory" / "logs"
    old_logs.mkdir(parents=True, exist_ok=True)
    (old_logs / "old.md").write_text("这条旧日志不应进入下一轮提示词", encoding="utf-8")
    old_messages = ws / "memory" / "messages"
    old_messages.mkdir(parents=True, exist_ok=True)
    (old_messages / "old.md").write_text("旧完整发言也不应被引用", encoding="utf-8")

    ctx = build_dispatch_context(
        session_id=session_id,
        workspace_root=ws,
        target_agent_name="数据专家",
        goal="数据 周报",
        k=1,
    )

    assert ctx["has_memory"] is True
    assert ctx["facts"] == ["用户希望输出周报", "需包含图表"]
    assert ctx["logs"] == []
    assert ctx["refs"] == []
    assert "关键事实" in ctx["rendered"]
    assert "相关历史摘录" not in ctx["rendered"]
    assert "旧日志不应进入下一轮提示词" not in ctx["rendered"]
    assert "旧完整发言也不应被引用" not in ctx["rendered"]


def test_upsert_index_entries_dedup_and_dispatch_render(tmp_path: Path):
    session_id = "group-test"
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)

    entries = upsert_index_entries(
        session_id,
        [
            {
                "agent_name": "写作专家",
                "skill": "weekly-report",
                "summary": "生成周报草稿",
                "files": ["reports/weekly.md", "reports/weekly.md"],
            }
        ],
        workspace_root=ws,
    )
    entries = upsert_index_entries(
        session_id,
        [
            {
                "agent_name": "图表专家",
                "skill": "charting",
                "summary": "生成趋势图",
                "files": ["charts/trend.png"],
            }
        ],
        max_entries=2,
        workspace_root=ws,
    )

    assert entries == [
        {
            "agent_name": "写作专家",
            "skill": "weekly-report",
            "summary": "生成周报草稿",
            "files": ["reports/weekly.md"],
        },
        {
            "agent_name": "图表专家",
            "skill": "charting",
            "summary": "生成趋势图",
            "files": ["charts/trend.png"],
        },
    ]
    index = (ws / "memory" / "index.md").read_text(encoding="utf-8")
    assert "summary: 生成周报草稿" in index
    assert "- reports/weekly.md" in index
    assert "- charts/trend.png" in index

    ctx = build_dispatch_context(
        session_id=session_id,
        workspace_root=ws,
        target_agent_name="接力专家",
        goal="继续写报告",
    )

    assert ctx["has_memory"] is True
    assert "工作区索引" in ctx["rendered"]
    assert "写作专家 / weekly-report: 生成周报草稿" in ctx["rendered"]
    assert "- reports/weekly.md" in ctx["rendered"]
    assert "读取上述文件时使用工作区相对路径" in ctx["rendered"]


def test_build_dispatch_context_without_facts_has_no_memory(tmp_path: Path):
    session_id = "group-test"
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)

    ctx = build_dispatch_context(
        session_id=session_id,
        workspace_root=ws,
        target_agent_name="数据专家",
        goal="数据 周报",
        k=1,
    )

    assert ctx == {"facts": [], "index": [], "logs": [], "refs": [], "rendered": "", "has_memory": False}
