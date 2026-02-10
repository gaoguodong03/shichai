"""执行 Skill 目录下 scripts/ 中的脚本，作为一等步骤能力。"""
import os
import subprocess
import json
from pathlib import Path

from langchain_core.tools import tool


def _get_skills_dir() -> Path:
    return Path(os.getenv("SKILLS_DIR", "./skills")).resolve()


def create_run_skill_script_tool(skill_id: str):
    """
    创建「执行当前技能下脚本」的工具，仅允许运行该 skill 的 scripts/ 目录内脚本。
    脚本可在 SKILL.md 或 scripts 中被描述，由 LLM 在需要时调用。
    """
    skills_dir = _get_skills_dir()
    script_root = (skills_dir / skill_id / "scripts").resolve()
    if not script_root.exists():
        script_root.mkdir(parents=True, exist_ok=True)

    @tool
    def run_skill_script(script_path: str, input_json: str = "") -> str:
        """执行当前技能 scripts 目录下的脚本。script_path 为相对 scripts 的路径（如 optimize-prompt.py）；input_json 为可选 JSON 字符串，会作为 stdin 传入脚本。仅支持 .py 与 .sh。"""
        # #region agent log: run_skill_script entry
        try:
            import time as _t, json as _json, os as _os
            log_path = "/Users/ggd/mycode/DHA/.cursor/debug.log"
            _os.makedirs(_os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as _f:
                _f.write(
                    _json.dumps(
                        {
                            "id": f"log_{int(_t.time()*1000)}_run_skill_script_enter",
                            "timestamp": int(_t.time() * 1000),
                            "location": "app/tools/run_skill_script.py:entry",
                            "message": "run_skill_script_enter",
                            "runId": "run_skill_script-debug-1",
                            "hypothesisId": "H-script",
                            "data": {"skill_id": skill_id, "script_path": script_path},
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        except Exception:
            pass
        # #endregion agent log: run_skill_script entry

        # 兼容 LLM 把整个 JSON 对象字符串塞进 script_path 的情况，例如：
        # script_path='{"script_path": "hello_dha.py", "input_json": ""}'
        raw_script_param = (script_path or "").strip()
        try:
            if raw_script_param.startswith("{") and raw_script_param.endswith("}"):
                maybe_obj = json.loads(raw_script_param)
                if isinstance(maybe_obj, dict) and "script_path" in maybe_obj:
                    script_path = str(maybe_obj.get("script_path", "")).strip()
                    if "input_json" in maybe_obj and not input_json:
                        ij = maybe_obj["input_json"]
                        input_json = ij if isinstance(ij, str) else json.dumps(ij, ensure_ascii=False)
                else:
                    script_path = raw_script_param
            else:
                script_path = raw_script_param
        except Exception:
            script_path = raw_script_param

        if not script_path or ".." in script_path or script_path.startswith("/"):
            return "错误：script_path 必须为相对路径且不包含 ..。"
        script_path = script_path.strip().lstrip("/")
        full = (script_root / script_path).resolve()
        if not str(full).startswith(str(script_root)) or not full.is_file():
            return f"错误：脚本不存在或不在允许目录内：{script_path}"
        suffix = full.suffix.lower()
        timeout_sec = int(os.getenv("SKILL_SCRIPT_TIMEOUT", "60"))
        cmd = []
        if suffix == ".py":
            cmd = ["python3", str(full)]
        elif suffix in (".sh", ".bash"):
            cmd = ["bash", str(full)]
        else:
            return f"错误：仅支持 .py 与 .sh 脚本，当前为 {suffix}。"
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(script_root),
                input=input_json if input_json else None,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                env={**os.environ},
            )
            out = (proc.stdout or "").strip()
            err = (proc.stderr or "").strip()

            # #region agent log: run_skill_script result
            try:
                import time as _t2, json as _json2, os as _os2
                log_path2 = "/Users/ggd/mycode/DHA/.cursor/debug.log"
                _os2.makedirs(_os2.path.dirname(log_path2), exist_ok=True)
                with open(log_path2, "a", encoding="utf-8") as _f2:
                    _f2.write(
                        _json2.dumps(
                            {
                                "id": f"log_{int(_t2.time()*1000)}_run_skill_script_result",
                                "timestamp": int(_t2.time() * 1000),
                                "location": "app/tools/run_skill_script.py:result",
                                "message": "run_skill_script_result",
                                "runId": "run_skill_script-debug-1",
                                "hypothesisId": "H-script",
                                "data": {
                                    "skill_id": skill_id,
                                    "script_path": script_path,
                                    "returncode": proc.returncode,
                                    "stdout_preview": out[:200],
                                    "stderr_preview": err[:200],
                                },
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
            except Exception:
                pass
            # #endregion agent log: run_skill_script result

            if proc.returncode != 0:
                return f"脚本退出码 {proc.returncode}\nstdout:\n{out}\nstderr:\n{err}"
            return out if out else "(无输出)"
        except subprocess.TimeoutExpired:
            return f"错误：脚本执行超时（{timeout_sec} 秒）。"
        except Exception as e:
            return f"错误：执行失败 - {e}"

    run_skill_script.name = "run_skill_script"
    run_skill_script.description = (
        "执行当前技能 scripts 目录下的脚本（如 optimize-prompt.py）。"
        "参数：script_path（相对 scripts 的文件名），input_json（可选，JSON 字符串作为 stdin）。"
        "技能说明或 scripts 中若要求「运行某脚本」时使用本工具。"
    )
    return run_skill_script
