#!/usr/bin/env python3
"""
为「按会话隔离的 workspace」验证场景创建会话并写入测试文件。
请先启动后端（uvicorn），再在项目根目录执行：
  cd backend && python scripts/seed_verify_workspace.py
  或在 DHA 根目录：python backend/scripts/seed_verify_workspace.py（需能 import app）
"""
import json
import os
import sys
from pathlib import Path

# 允许从项目根或 backend 运行
if Path("backend").is_dir():
    sys.path.insert(0, str(Path("backend").resolve()))
elif Path("app").is_dir():
    pass
else:
    os.chdir(Path(__file__).resolve().parent.parent)
    sys.path.insert(0, os.getcwd())

try:
    import httpx
except ImportError:
    print("请安装: pip install httpx")
    sys.exit(1)

BASE = os.getenv("DHA_API_BASE", "http://127.0.0.1:8000")
API = f"{BASE}/api"

# 使用一个在 dha_instances.json 中存在的 DHA（内容生成专家，有 filesystem）
DHA_ID = "dha-195b8c3a"

VERIFY_MD = """# 验证用说明（本地文件能力）

这是为验证「按会话隔离的 workspace」而生成的测试文件。

- 本文件位于当前会话的工作区内（workspaces/<会话ID>/验证用-说明.md）。
- 你可以在对话中通过【文件引用】让 DHA 读取此文件。
- 再让 DHA 把总结或新内容写入工作区（如 summary.md），验证写回能力。
- 导出会话时会保存到本会话工作区，不再使用全局目录。
"""


def main():
    print("1. 创建会话…")
    try:
        r = httpx.post(
            f"{API}/sessions",
            json={
                "title": "验证文件能力",
                "agent_ids": [DHA_ID],
            },
            timeout=10.0,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("status") != "ok":
            print("创建失败:", data)
            return 1
        gsid = data["data"]["id"]
        print(f"   会话已创建，ID: {gsid}")
    except httpx.ConnectError:
        print("   错误: 无法连接后端，请先启动 uvicorn（如 cd backend && uvicorn app.main:app --reload）")
        return 1
    except Exception as e:
        print("   错误:", e)
        return 1

    print("2. 在工作区写入测试文件…")
    try:
        # 与 backend 运行时一致：AGENT_OUTPUTS_DIR 默认相对于 backend 目录
        if Path("backend").is_dir():
            default_root = Path("backend/data/agent-outputs")
        else:
            default_root = Path("data/agent-outputs")
        root = Path(os.getenv("AGENT_OUTPUTS_DIR", str(default_root))).resolve()
        ws_path = root / "workspaces" / gsid
        ws_path.mkdir(parents=True, exist_ok=True)
        (ws_path / "验证用-说明.md").write_text(VERIFY_MD.strip(), encoding="utf-8")
        print(f"   已写入: {ws_path / '验证用-说明.md'}")
    except Exception as e:
        print("   错误:", e)
        return 1

    print("\n" + "=" * 60)
    print("验证步骤（请按顺序在浏览器中操作）")
    print("=" * 60)
    print(f"""
1. 打开前端 http://localhost:5173 ，在左侧「Chat」下应看到会话「验证文件能力」，点击进入。

2. 验证「读文件」：
   - 在输入框旁点击「引用文件」或「📎」，在列表里选择「验证用-说明.md」；
   - 或直接输入：请读取【文件引用：workspaces/{gsid}/验证用-说明.md】并总结要点。
   - 发送后，DHA 应能读取该文件并回答。

3. 验证「写文件」：
   - 输入：请把上面要点的总结写入工作区文件 summary.md
   - 发送后，DHA 应调用 write_workspace_file 写入。

4. 验证「Files 按会话隔离」：
   - 左侧切换到「Files」，确保当前选中的是「验证文件能力」会话；
   - 应能看到「验证用-说明.md」和（若步骤3成功）「summary.md」；
   - 点击可预览/下载，确认只能看到本会话工作区。

5. 验证「导出到工作区」：
   - 回到该会话的对话，发送：请导出当前对话为 markdown
   - 或使用导出相关技能；导出文件应落在本会话工作区，下载链接为 /api/workspaces/{gsid}/files/download?path=...

6. 验证「无全局 /api/files」（可选）：
   - 在浏览器控制台或 curl 请求 GET /api/files ，应得到 404。
""")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
