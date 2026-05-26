"""Skill agent runtime built on the project-local SimpleAgent loop."""
import asyncio
import json
import logging
import os
import re
import time
from typing import TypedDict, Annotated, Sequence, List
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage
from app.agent.llm_client import QwenLLM, bind_tools_compat
from app.agent.read_path_utils import (
    looks_like_url_or_remote_path,
    prefer_more_specific_path,
    strip_llm_junk_from_read_path,
)
from app.agent.simple_agent import SimpleAgent
from app.agent.skill_tool_naming import build_skill_script_tool_name
from app.agent.tool_spec import ToolSpec

logger = logging.getLogger(__name__)

_EXT_RE = re.compile(
    r"([\w./\u4e00-\u9fff\-]+?(?:\.(?:md|txt|json|yaml|yml|csv|html|htm|xml|py|ts|js|vue|css)))\b",
    re.I,
)
_FILE_REF_TAG_RE = re.compile(r"【文件引用：([^】]+)】")
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".webm", ".amr"}
_AUDIO_EXT_RE = re.compile(
    r"([\w./\u4e00-\u9fff\-]+?(?:\.(?:mp3|wav|m4a|aac|flac|ogg|opus|webm|amr)))\b",
    re.I,
)

def _clean_user_path_candidate(s: str) -> str:
    return (s or "").strip().strip(" \t\r\n\"'""''「」『』")


def _looks_like_workspace_rel_path(s: str) -> bool:
    t = _clean_user_path_candidate(s)
    if not t or ".." in t:
        return False
    if "/" in t or "\\" in t:
        return True
    return bool(_EXT_RE.fullmatch(t) or re.search(r"\.(md|txt|json|yaml|yml|csv)$", t, re.I))


def _pick_best_workspace_path(candidates: list[str]) -> str:
    """同一消息中多条路径时，对同名文件优先选带子目录的路径（note/test.md 优于根目录 test.md）。"""
    cleaned: list[str] = []
    for c in candidates:
        t = _clean_user_path_candidate(c).replace("\\", "/")
        if not t or ".." in t:
            continue
        if not _looks_like_workspace_rel_path(t):
            continue
        cleaned.append(t)
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    from collections import defaultdict

    by_base: dict[str, list[str]] = defaultdict(list)
    for c in cleaned:
        by_base[c.split("/")[-1].lower()].append(c)
    winners: list[str] = []
    for group in by_base.values():
        group.sort(key=lambda x: (x.count("/"), len(x)), reverse=True)
        winners.append(group[0])
    if len(winners) == 1:
        return winners[0]
    winners.sort(key=lambda x: (x.count("/"), len(x)), reverse=True)
    return winners[0]


def _paths_from_file_ref_tags(text: str) -> list[str]:
    """解析用户消息中的【文件引用：显示名｜相对路径】，与前端发送格式一致。"""
    out: list[str] = []
    for body in _FILE_REF_TAG_RE.findall(text or ""):
        body = (body or "").strip()
        if not body:
            continue
        if "\uff5c" in body:
            p = body.split("\uff5c", 1)[1].strip()
        elif "|" in body:
            p = body.split("|", 1)[1].strip()
        else:
            p = body
        if p and not looks_like_url_or_remote_path(p):
            out.append(p)
    return out


def _collect_paths_from_user_text(text: str) -> list[str]:
    """从单条用户正文中收集工作区相对路径候选（支持反引号、中英文引号、中文文件名）。"""
    raw = text or ""
    seen: set[str] = set()
    out: list[str] = []

    def add(p: str) -> None:
        c = _clean_user_path_candidate(p)
        if not c or c in seen:
            return
        if not _looks_like_workspace_rel_path(c):
            return
        seen.add(c)
        out.append(c)

    for c in re.findall(r"`([^`]{1,800})`", raw):
        add(c)
    for pat in (
        r'[""]([^""]{1,800})[""]',
        r"[「『]([^」』]{1,800})[」』]",
    ):
        for g in re.findall(pat, raw):
            add(g)
    for m in _EXT_RE.finditer(raw):
        g = m.group(1)
        # 避免把「文件路径就是test.md」整句当作路径；能拆则只取其中的 test.md / dir/a.md
        if "就是" in g or "路径是" in g or "路径就是" in g:
            inner = strip_llm_junk_from_read_path(g)
            if inner and inner != g:
                add(inner)
            continue
        add(g)
    return out


def _extract_path_from_last_user_for_read(messages: Sequence[BaseMessage]) -> str:
    """从最近一条用户消息中提取 read_file 应用的路径（供补全或覆盖模型错误路径）。"""
    last_user = None
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            last_user = m
            break
    if last_user is None:
        return ""
    content = str(getattr(last_user, "content", "") or "").strip()
    if not content:
        return ""

    # 用户纠正「要 A 而不是 B」时，只从「而不是」之前的子串取路径，避免取到被否定的旧路径
    head = content
    if "而不是" in content or "而非" in content:
        head = re.split(r"而不是|而非", content, maxsplit=1)[0]

    ref_paths = _paths_from_file_ref_tags(head)
    if ref_paths:
        picked = _pick_best_workspace_path(ref_paths)
        if picked:
            return picked

    paths_head = _collect_paths_from_user_text(head)
    if paths_head:
        return _pick_best_workspace_path(paths_head)

    # 常见句式：新增了 xxx、读取的是 xxx
    m = re.search(
        r"(?:新增[了]?[ \t]*|要读取的是[ \t]*|读取的是[ \t]*)[「「""'' \t]*"
        r"([\w./\u4e00-\u9fff\-/]+\.(?:md|txt|json|yaml|yml|csv))",
        content,
    )
    if m:
        p = _clean_user_path_candidate(m.group(1))
        if _looks_like_workspace_rel_path(p):
            return p

    paths_all = _collect_paths_from_user_text(content)
    if paths_all:
        return _pick_best_workspace_path(paths_all)
    return ""


def _should_override_read_file_path_with_user(last_user_content: str, model_path: str, user_path: str) -> bool:
    """当模型沿用了会话中的旧路径，而用户最新消息已给出不同路径时，是否应以用户路径为准。"""
    u = (user_path or "").strip().replace("\\", "/")
    m = (model_path or "").strip().replace("\\", "/")
    if not u or u == m:
        return False
    # 仅在“用户路径更具体”时才允许覆盖（避免多轮对话里误把用户上一轮提到的文件强行覆盖到本轮工具调用）。
    return prefer_more_specific_path(u, m)


def _tool_is_workspace_plain_read_file(tool_name: str) -> bool:
    """与 tools_for_skill 中 file-reader MCP 的 read_file 名称一致。"""
    n = (tool_name or "").strip()
    return n == "read_file" or n == "file-reader_read_file"


def _apply_read_file_path_from_user_message(arguments: dict, messages: Sequence[BaseMessage]) -> None:
    """若最近用户消息中有可解析路径，则补全或覆盖 read_file / file-reader_read_file 的 path（原地修改 arguments）。"""
    raw_arg = (arguments.get("path") or arguments.get("__arg1") or "").strip()
    if raw_arg:
        fixed = strip_llm_junk_from_read_path(raw_arg)
        if fixed and fixed != raw_arg:
            logger.info("read_file: 清理模型 path 中的说明性文字: %s -> %s", raw_arg, fixed)
            arguments["path"] = fixed
            arguments.pop("__arg1", None)

    auto_path = _extract_path_from_last_user_for_read(messages)
    cur = (arguments.get("path") or arguments.get("__arg1") or "").strip()

    last_user = None
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            last_user = msg
            break
    last_content = str(getattr(last_user, "content", "") or "") if last_user else ""

    if cur and looks_like_url_or_remote_path(cur):
        if auto_path:
            logger.info(
                "read_file: 模型 path 为网页/远端路径，改用用户消息中的工作区路径: %s -> %s",
                cur,
                auto_path,
            )
            arguments["path"] = auto_path
            arguments.pop("__arg1", None)
        return

    if not auto_path:
        return

    if not cur:
        arguments["path"] = auto_path
        arguments.pop("__arg1", None)
        return
    if cur.replace("\\", "/").strip() == auto_path.replace("\\", "/").strip():
        return
    # 默认不随意覆盖模型传入的 path，避免“第二次读取”读回用户上一轮提到的文件。
    # 仅在以下情况才覆盖：
    # - 模型 path 非工作区相对路径（例如说明性文字/无效值）
    # - 用户给出了更具体的路径（note/a.md 覆盖 a.md）
    cur_norm = cur.replace("\\", "/").strip()
    auto_norm = auto_path.replace("\\", "/").strip()
    if (not _looks_like_workspace_rel_path(cur_norm)) and _looks_like_workspace_rel_path(auto_norm):
        logger.info("read_file: 模型 path 非工作区相对路径，改用用户路径: %s -> %s", cur, auto_path)
        arguments["path"] = auto_path
        arguments.pop("__arg1", None)
        return
    if prefer_more_specific_path(auto_norm, cur_norm):
        logger.info("read_file: 用户路径更具体，覆盖模型参数: %s -> %s", cur, auto_path)
        arguments["path"] = auto_path
        arguments.pop("__arg1", None)


def _looks_like_audio_workspace_rel_path(path: str) -> bool:
    p = _clean_user_path_candidate(path).replace("\\", "/")
    if not p or p.startswith("/") or ".." in p or looks_like_url_or_remote_path(p):
        return False
    return any(p.lower().endswith(ext) for ext in _AUDIO_EXTS)


def _extract_path_from_last_user_for_audio(messages: Sequence[BaseMessage]) -> str:
    last_user = None
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            last_user = msg
            break
    if last_user is None:
        return ""
    content = str(getattr(last_user, "content", "") or "")
    for candidate in _paths_from_file_ref_tags(content):
        cleaned = _clean_user_path_candidate(candidate).replace("\\", "/")
        if _looks_like_audio_workspace_rel_path(cleaned):
            return cleaned
    for match in _AUDIO_EXT_RE.finditer(content):
        cleaned = _clean_user_path_candidate(match.group(1)).replace("\\", "/")
        if _looks_like_audio_workspace_rel_path(cleaned):
            return cleaned
    return ""


def _workspace_audio_path_to_backend_data_arg(rel_path: str, workspace_id: str) -> str:
    rel = _clean_user_path_candidate(rel_path).replace("\\", "/").lstrip("/")
    if not rel or rel.startswith("backend/data/"):
        return rel
    if not workspace_id:
        return rel
    if not _looks_like_audio_workspace_rel_path(rel):
        return rel

    from app.api.files import get_workspace_root_path
    from app.core.user_context import users_data_root

    ws_root = get_workspace_root_path(workspace_id).resolve()
    target = (ws_root / rel).resolve()
    try:
        target.relative_to(ws_root)
    except ValueError:
        return rel

    data_root = users_data_root().resolve().parent
    try:
        data_rel = target.relative_to(data_root).as_posix()
    except ValueError:
        return rel
    return f"backend/data/{data_rel}"


def _apply_audio_asr_path_from_user_message(
    arguments: dict,
    messages: Sequence[BaseMessage],
    workspace_id: str,
) -> None:
    """For audio-asr MCP, convert workspace-relative audio paths to backend/data paths."""
    cur = str(arguments.get("path") or arguments.get("__arg1") or "").strip()
    if cur.startswith("backend/data/"):
        arguments["path"] = cur
        arguments.pop("__arg1", None)
        return

    user_audio_path = _extract_path_from_last_user_for_audio(messages)
    source = cur if _looks_like_audio_workspace_rel_path(cur) else user_audio_path
    if not source:
        return
    converted = _workspace_audio_path_to_backend_data_arg(source, workspace_id)
    if converted and converted != cur:
        logger.info("audio_asr: 工作区音频路径转换为 backend/data 路径: %s -> %s", source, converted)
        arguments["path"] = converted
        arguments.pop("__arg1", None)


def _tool_name_looks_like_bound_mcp(name: str) -> bool:
    """区分「本技能声明的 MCP 工具（server_tool）」与工作区 / 脚本 / 包装类工具。"""
    n = (name or "").strip()
    if "_" not in n:
        return False
    if n.startswith("run_skill_script_"):
        return False
    head, _ = n.split("_", 1)
    if head in ("filesystem",):
        return False
    if n in {
        "read_file",
        "write_workspace_file",
        "edit_workspace_file",
        "rename_workspace_file",
        "mkdir_workspace",
        "list_workspace_directory",
        "call_api",
    }:
        return False
    return True


def _skill_execution_extra_instructions(tools: List[ToolSpec]) -> str:
    """随实际绑定工具生成「多步规则 / 工作区 / call_api」说明，避免禁用能力后仍误导模型。"""
    names = {getattr(t, "name", "") for t in tools}
    parts: List[str] = []
    script_names = sorted(n for n in names if n.startswith("run_skill_script_"))
    if not script_names:
        parts.append(
            "## 多步任务规则\n"
            "需要多步工具调用时，连续完成所有必要步骤；任务完成后再回复。\n\n"
        )
    file_lines: List[str] = []
    if "read_file" in names:
        file_lines.append("- read_file: 读取工作区内相对路径对应的文件内容（例如 note/test.md、notes/report.md）。")
    if "write_workspace_file" in names:
        file_lines.append("- write_workspace_file: 将文本写入工作区文件（path 为相对路径，如 note/draft.md）。")
    if "edit_workspace_file" in names:
        file_lines.append("- edit_workspace_file: 对工作区内文件做增量修改（用 old_text → new_text）。")
    if "rename_workspace_file" in names:
        file_lines.append("- rename_workspace_file: 重命名工作区内文件或目录。")
    if "mkdir_workspace" in names:
        file_lines.append("- mkdir_workspace: 在工作区内新建目录。")
    if "list_workspace_directory" in names:
        file_lines.append("- list_workspace_directory: 递归列出目录中文件（含子目录）。")
    if file_lines:
        parts.append("## 文件操作（当前会话工作区）\n\n你拥有以下与「当前会话工作区」相关的工具：\n")
        parts.append("\n".join(file_lines) + "\n\n**强制规则（优先级很高）：**\n")
        if "read_file" in names:
            parts.append(
                "- 当用户消息中出现「读取/打开/查看/查/展示 + 某个路径或文件名」时，"
                "你**必须优先调用 `read_file`**，而不是只用自然语言解释路径是否正确；"
                "path 必须用**用户本条消息里写的路径**，不要用会话里较早提到的旧文件路径。\n"
            )
        if "write_workspace_file" in names or "edit_workspace_file" in names:
            parts.append(
                "- 当用户让你「保存/写入/覆盖某个文件」时，优先调用 `write_workspace_file` 或 `edit_workspace_file`，"
                "而不是只说「请手动保存」。\n"
            )
        if "write_workspace_file" in names:
            parts.append(_WORKSPACE_TASK_FILE_RULE)
        parts.append("- 对于【文件引用：…】标签，path 一律视为工作区内相对路径使用（如 `report.md` 或 `notes/report.txt`）。\n")
        parts.append(
            "- 所有 path 都应当是**当前会话工作区的相对路径**，不要暴露或要求用户输入任何 "
            "`agent-outputs/`、`workspaces/<会话ID>/...` 这类内部前缀。\n\n"
            "若工具返回「文件不存在」，你可以根据工具返回的候选路径列表请用户确认，但**不要凭空猜测文件内容**。\n\n"
        )
    if "call_api" in names:
        parts.append(
            "## 外部 HTTP（call_api）\n\n"
            "当需要获取**公开**网页或 HTTP API 的响应时，使用 `call_api`。参数为 "
            "`url`、`method`、`headers_json`、`body`；POST/PUT 时显式设置 method，并把 headers_json/body 写成 JSON 字符串。"
            "服务端已做基础 SSRF 防护，无法访问内网或本机地址；若页面需登录或强反爬，结果可能不完整。\n\n"
        )
    if "audio-asr_transcribe_audio_file" in names:
        parts.append(
            "## 音频转写路径规则\n\n"
            "调用 `audio-asr_transcribe_audio_file` 时，如果用户消息包含【文件引用：…】或工作区文件名，"
            "path 使用用户本条消息中的工作区相对路径即可（例如 `meeting.mp3`）。运行时会在工具执行前把它转换成 "
            "`backend/data/...` 完整数据路径；不要要求用户提供 `backend/data/`、`users/<user_id>/`、"
            "`sessions/workspaces/<session_id>/` 等内部路径。\n\n"
        )
    if script_names:
        parts.append(
            "## 技能脚本工具\n\n"
            "用结构化工具调用执行当前技能脚本：`script_path` 填 scripts/ 下相对路径，"
            "`cli_args_json` 填 JSON 数组字符串（如 `[\"--query\",\"用户原话\"]`）。"
            "不要用 `input_json`，不要传宿主机绝对路径。\n\n"
            + "\n".join(f"- `{n}`" for n in script_names)
            + "\n\n"
        )
    mcp_names = sorted({getattr(t, "name", "") for t in tools if _tool_name_looks_like_bound_mcp(getattr(t, "name", ""))})
    if mcp_names:
        parts.append(
            "## 本技能绑定的 MCP 工具\n\n"
            "以下工具由本技能声明并已加载；当流程需要对应外部能力（检索、地图、浏览器、读特定格式文件等）时，"
            "**必须优先使用这些 MCP 工具**完成步骤，不要用无关工具替代或仅靠猜测。"
            "参数以该工具 schema 为准，不要把所有参数塞进 `__arg1`，除非该工具本身只接受单字符串参数。\n\n"
            + "\n".join(f"- `{n}`" for n in mcp_names)
            + "\n\n"
        )
    return "".join(parts)


def _get_tool_call_arguments(tool_call: dict) -> dict:
    """从 tool_call 得到参数字典。支持 args / arguments，若为 JSON 字符串则解析。"""
    raw = tool_call.get("args") or tool_call.get("arguments")
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("tool_call arguments 非合法 JSON: %s", raw[:200])
    return {}


def _get_mcp_input_schema(tool_name: str, tools: Sequence[ToolSpec]) -> dict | None:
    """从 tools 列表中按 tool_name 取出 MCP 工具的 inputSchema，供 __arg1 等通用参数映射。"""
    if not tools:
        return None
    for t in tools:
        if getattr(t, "name", None) == tool_name:
            return getattr(t, "_mcp_input_schema", None)
    return None


def _extract_description_from_content(content: str, tool_name: str) -> str | None:
    """当 tool_calls 的 args 为空时，从同条 AIMessage 的 content 中解析 description。
    兼容 content 中的 ```json { "tool": "...", "arguments": { "description": "..." } } ``` 或 "description": "..."。
    """
    if not (content and isinstance(content, str) and tool_name.strip()):
        return None
    import re
    # 1) 先尝试从代码块中的 JSON 解析（含 tool / arguments）
    for block in re.findall(r"```(?:json)?\s*([\s\S]*?)```", content):
        block = block.strip()
        if not block:
            continue
        try:
            obj = json.loads(block)
            if not isinstance(obj, dict):
                continue
            # 若指定了 tool，需匹配当前工具名
            if "tool" in obj and obj.get("tool") != tool_name:
                continue
            args = obj.get("arguments") or obj
            desc = args.get("description") if isinstance(args, dict) else None
            if desc and isinstance(desc, str) and desc.strip():
                return desc.strip()
        except (json.JSONDecodeError, TypeError):
            continue
    # 2) 整段 content 当作 JSON 试一次（部分模型直接输出单个 JSON）
    try:
        obj = json.loads(content.strip())
        if isinstance(obj, dict):
            args = obj.get("arguments") or obj
            desc = args.get("description") if isinstance(args, dict) else None
            if desc and isinstance(desc, str) and desc.strip():
                return desc.strip()
    except (json.JSONDecodeError, TypeError):
        pass
    # 3) 正则匹配 "description": "..."（含简单转义）
    m = re.search(r'"description"\s*:\s*"((?:[^"\\]|\\.)*)"', content)
    if m:
        s = m.group(1).encode().decode("unicode_escape") if "\\" in m.group(1) else m.group(1)
        if s.strip():
            return s.strip()
    return None

# 可通过 LLM_AGENT_TIMEOUT 调整（秒），默认 180。多轮工具调用时上下文较长，需更长时间
_LLM_AGENT_TIMEOUT = int(os.getenv("LLM_AGENT_TIMEOUT", "180"))
_SKILL_AGENT_MAX_STEPS = max(2, int(os.getenv("SKILL_AGENT_MAX_STEPS", "6")))
_SKILL_AGENT_MAX_REPEATED_TOOL_ROUNDS = max(
    1, int(os.getenv("SKILL_AGENT_MAX_REPEATED_TOOL_ROUNDS", "1"))
)

_WORKSPACE_TASK_FILE_RULE = (
    "- 需要创建任务文件时，必须先调用 `write_workspace_file` 创建或覆盖该文件；"
    "path 固定使用 `speaker_task.txt` 或 `memory/speaker_task.txt`。"
    "确认写入成功后，才允许再调用 `read_file` 读取；"
    "不要在未写入成功前猜测或读取 `speaker_task.txt`。\n"
)


def _resolve_mangled_tool_name(tool_name: str, valid_names: List[str]) -> str | None:
    """当模型将多个工具名拼接（如 amap-maps_maps_geo + amap-maps_maps_weather）时，解析出第一个有效工具名。"""
    if tool_name in valid_names:
        return tool_name
    # 优先：取最长的「合法名称且为 tool_name 前缀」
    for name in sorted(valid_names, key=len, reverse=True):
        if tool_name.startswith(name):
            return name
    # 否则：取在 tool_name 中最先出现的合法名称
    best = None
    best_pos = 999999
    for name in valid_names:
        pos = tool_name.find(name)
        if pos != -1 and pos < best_pos:
            best_pos = pos
            best = name
    return best


async def _execute_tool_safely(tool: ToolSpec, arguments: dict) -> object:
    """统一执行工具，兼容 func=None 但 coroutine 可用的 ToolSpec。"""
    func = getattr(tool, "func", None)
    if callable(func):
        raw = func(**arguments)
        return await raw if asyncio.iscoroutine(raw) else raw

    coroutine_fn = getattr(tool, "coroutine", None)
    if callable(coroutine_fn):
        raw = coroutine_fn(**arguments)
        return await raw if asyncio.iscoroutine(raw) else raw

    if hasattr(tool, "arun"):
        tool_input = json.dumps(arguments) if arguments else "{}"
        return await tool.arun(tool_input)

    if hasattr(tool, "run"):
        tool_input = json.dumps(arguments) if arguments else "{}"
        return await asyncio.to_thread(tool.run, tool_input)

    raise RuntimeError(f"工具 {getattr(tool, 'name', 'unknown')} 无法执行")

class AgentState(TypedDict):
    """Agent 状态"""
    messages: Annotated[Sequence[BaseMessage], "对话消息列表"]
    tools: List[ToolSpec]

def create_react_agent(
    llm,
    tools: list[ToolSpec],
    skills_instruction: str = "",
    skill_routing_rules: str = "",
    extra_system_prompt: str = "",
):
    """创建 ReAct Agent。extra_system_prompt 为设置中的系统提示词，每次 chat 前注入到 prompt 最前。
    skill_routing_rules 由 SkillsLoader.get_skill_routing_rules() 动态生成，来自各 SKILL.md 的 description。"""
    logger.info(f"创建 ReAct Agent，工具数量: {len(tools)}, 技能指令长度: {len(skills_instruction)}, 技能路由规则长度: {len(skill_routing_rules)}, 额外系统提示词长度: {len(extra_system_prompt)}")
    
    # 构建系统提示词：先拼接设置中的系统提示词（每次 chat 前注入）
    system_prompt = ""
    if extra_system_prompt and extra_system_prompt.strip():
        system_prompt += extra_system_prompt.strip() + "\n\n"
    system_prompt += """你是一个有用的 AI 助手，可以使用工具来帮助用户。

你可以使用以下工具：
"""
    
    # 添加工具描述
    for tool in tools:
        system_prompt += f"- {tool.name}: {tool.description}\n"
    if tools:
        logger.info("已添加工具指令到系统提示词")
    # 若包含 Exa 工具，注入 Exa MCP 使用说明（仅调用 exa 时生效）
    if any(t.name == "exa_web_search_exa" for t in tools):
        system_prompt += """
## Exa 搜索工具使用说明
调用 exa_web_search_exa 时**必须**使用参数名 query（必需）传递搜索关键词，不要使用 __arg1。示例：{"query": "北京 烟花 燃放", "numResults": 10}。
可选参数：numResults（数量）、livecrawl（'fallback'|'preferred'|'always'|'never'）、type（'auto'|'fast'）。type 不要用 'news' 等无效值。

"""
    system_prompt += """
当你需要使用工具时，必须使用模型的结构化工具调用（tool_calls / function calling），不要把工具调用 JSON 写进正文。

当你不需要使用工具时，直接回复用户的问题。

## 文件操作（当前会话工作区）

你拥有以下与“当前会话工作区”相关的工具：
- read_file: 读取工作区内相对路径对应的文件内容（例如 note/test.md、notes/report.md）。
- write_workspace_file: 将文本写入工作区文件（path 为相对路径，如 note/draft.md）。
- edit_workspace_file: 对工作区内文件做增量修改（用 old_text → new_text）。
- rename_workspace_file: 重命名工作区内文件或目录。
- mkdir_workspace: 在工作区内新建目录。
- list_workspace_directory: 递归列出目录中文件（含子目录）。

**强制规则（优先级很高）：**
- 当用户消息中出现“读取/打开/查看/查/展示 + 某个路径或文件名”（例如 `读取 note/test.md`、`查看 output/pages/xxx/text.md`），你**必须优先调用 `read_file`**，而不是只用自然语言解释路径是否正确；path 必须用**用户本条消息里的路径**，不要沿用会话中较早提到的旧路径。
- 当用户让你“保存/写入/覆盖某个文件”时，优先调用 `write_workspace_file` 或 `edit_workspace_file`，而不是只说“请手动保存”。
- 需要创建任务文件时，必须先调用 `write_workspace_file` 创建或覆盖该文件；path 固定使用 `speaker_task.txt` 或 `memory/speaker_task.txt`。确认写入成功后，才允许再调用 `read_file` 读取；不要在未写入成功前猜测或读取 `speaker_task.txt`。
- 对于【文件引用：…】标签，path 一律视为工作区内相对路径使用（如 `report.md` 或 `notes/report.txt`）。
- 所有 path 都应当是**当前会话工作区的相对路径**，不要暴露或要求用户输入任何 `agent-outputs/`、`workspaces/<会话ID>/...` 这类内部前缀。

若工具返回“文件不存在”，你可以根据工具返回的候选路径列表请用户确认，但**不要凭空猜测文件内容**。

"""
    
    # 添加 Skills 指令（技能选择规则由 SkillsLoader 从各 SKILL.md 的 when_to_use/description 动态生成）
    if skills_instruction:
        if skill_routing_rules:
            system_prompt += """
## 技能选择（必须优先执行）

根据用户请求**先判断应使用哪个技能**，然后**仅按该技能的说明执行**，不要混用其他技能的工具或话术：

"""
            system_prompt += skill_routing_rules
            system_prompt += """

确定技能后，只调用该技能所需工具，并只输出该技能风格的回答。

"""
        else:
            system_prompt += """
## 技能选择（必须优先执行）

根据用户请求选择最合适的技能，按该技能说明执行，不要混用其他技能的工具或话术。

"""
        system_prompt += f"\n## 可用技能\n{skills_instruction}\n"
        logger.info("已添加技能指令到系统提示词")

    # 定义节点
    def should_continue(state: AgentState):
        """判断是否继续"""
        messages = state["messages"]
        last_message = messages[-1]
        
        logger.info(f"should_continue: 检查最后一条消息，类型: {type(last_message).__name__}")
        
        # 检查最后一条消息是否包含工具调用
        if isinstance(last_message, AIMessage):
            # 优先检查模型返回的结构化工具调用
            if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
                logger.info(f"should_continue: 检测到 {len(last_message.tool_calls)} 个结构化工具调用")
                return "call_tool"
            
            # 回退到文本解析（兼容旧格式）
            content = last_message.content
            logger.info(f"should_continue: AIMessage 内容 (前200字符): {str(content)[:200]}...")
            
            if isinstance(content, str) and "tool_call" in content.lower():
                try:
                    # 尝试解析 JSON
                    if "```json" in content:
                        json_str = content.split("```json")[1].split("```")[0].strip()
                    elif "```" in content:
                        json_str = content.split("```")[1].split("```")[0].strip()
                    else:
                        json_str = content
                    
                    logger.info(f"should_continue: 尝试解析 JSON: {json_str[:200]}...")
                    tool_call = json.loads(json_str)
                    logger.info(f"should_continue: 解析成功，action: {tool_call.get('action')}, tool: {tool_call.get('tool')}")
                    
                    if tool_call.get("action") == "tool_call":
                        return "call_tool"
                except Exception as e:
                    logger.warning(f"should_continue: JSON 解析失败: {e}")
        
        return "end"
    
    async def call_model(state: AgentState):
        """调用模型（异步版本）"""
        messages = list(state["messages"])
        # 添加系统消息
        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=system_prompt)] + messages
        
        # 使用 bind_tools 让 LLM 返回结构化工具调用
        client = llm.get_client()
        if tools:
            client = bind_tools_compat(client, tools)
        
        # 日志：本次输入大模型的提示词概览
        msg_summary = []
        for i, m in enumerate(messages):
            role = getattr(m, "type", type(m).__name__.replace("Message", "").lower())
            content = getattr(m, "content", str(m)) or ""
            s = str(content)
            if role == "system":
                msg_summary.append(f"  [{i+1}] {role}: 共 {len(s)} 字符，前150字: {s[:150]}…" if len(s) > 150 else f"  [{i+1}] {role}: {s}")
            else:
                preview = (s[:150] + "…") if len(s) > 150 else s
                msg_summary.append(f"  [{i+1}] {role}: {preview}")
        logger.info("输入大模型的提示词:\n" + "\n".join(msg_summary))
        
        # 使用异步调用（带超时，避免卡死）
        logger.info("call_model: 正在调用 LLM...")
        try:
            response = await asyncio.wait_for(client.ainvoke(messages), timeout=float(_LLM_AGENT_TIMEOUT))
        except asyncio.TimeoutError:
            logger.error(f"call_model: LLM 调用超时（{_LLM_AGENT_TIMEOUT}秒）")
            response = AIMessage(content="抱歉，模型响应超时，请稍后重试或检查网络与 API 配置。")
        logger.info(f"call_model: LLM 响应类型: {type(response).__name__}")
        logger.info(f"call_model: LLM 响应内容类型: {type(response.content).__name__}")
        logger.info(f"call_model: LLM 响应内容 (前200字符): {str(response.content)[:200]}...")
        
        # 检查是否有工具调用
        if hasattr(response, 'tool_calls') and response.tool_calls:
            logger.info(f"call_model: 检测到 {len(response.tool_calls)} 个工具调用")
            for tool_call in response.tool_calls:
                logger.info(f"call_model: 工具调用 - {tool_call.get('name')}, 参数: {tool_call.get('args')}")
        else:
            logger.info(f"call_model: 没有工具调用，响应内容: {str(response.content)[:200]}...")
        
        return {"messages": messages + [response]}
    
    async def call_tool(state: AgentState):
        """调用工具（异步版本）"""
        messages = state["messages"]
        last_message = messages[-1]
        
        logger.info(f"call_tool: 开始处理工具调用，最后一条消息类型: {type(last_message).__name__}")
        
        def normalize_tool_args(tool_name: str, arguments: dict, tools_list: Sequence[ToolSpec]) -> dict:
            """规范化工具参数。run_skill_script_* 不做 MCP 规范化；其余名含 '_' 的用 MCP 规范化，并传入 schema 以便 __arg1 自动映射到首参。"""
            args = dict(arguments) if arguments else {}
            if tool_name.startswith("run_skill_script_"):
                return args
            idx = tool_name.find("_")
            if idx >= 0:
                server_id = tool_name[:idx]
                original_tool_name = tool_name[idx + 1:]
                input_schema = _get_mcp_input_schema(tool_name, tools_list)
                from app.mcp.manager import normalize_mcp_kwargs_for_call
                return normalize_mcp_kwargs_for_call(server_id, original_tool_name, args, input_schema=input_schema)
            return args

        tool_results = []
        
        # 优先处理模型返回的结构化工具调用
        if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
            logger.info(f"call_tool: 处理 {len(last_message.tool_calls)} 个结构化工具调用")
            for tool_call in last_message.tool_calls:
                tool_name = tool_call.get("name") or tool_call.get("id", "")
                arguments = normalize_tool_args(tool_name, _get_tool_call_arguments(tool_call), state["tools"])
                # 若 volces-icon 的 description 仍为空，从同条消息 content 中解析（模型常把参数写在正文 JSON 里）
                if tool_name == "volces-icon_generate_app_icon" and not (arguments.get("description") or "").strip():
                    fallback = _extract_description_from_content(str(last_message.content or ""), tool_name)
                    if fallback:
                        arguments["description"] = fallback
                        logger.info(f"call_tool: 已从 content 补全 description，长度: {len(fallback)}")
                logger.info(f"call_tool: 工具名称: {tool_name}, 参数: {arguments}")
                logger.info(f"call_tool: 可用工具列表: {[t.name for t in state['tools']]}")
                
                # 查找工具（若不存在则尝试纠错：模型可能将多个工具名拼接）
                tool = None
                valid_names = [t.name for t in state["tools"]]
                if tool_name not in valid_names:
                    resolved = _resolve_mangled_tool_name(tool_name, valid_names)
                    if resolved:
                        tool_name = resolved
                        logger.info(f"call_tool: 工具名纠错后使用: {tool_name}")
                for t in state["tools"]:
                    if t.name == tool_name:
                        tool = t
                        logger.info(f"call_tool: 找到工具: {tool_name}")
                        break
                
                if tool:
                    logger.info(f"call_tool: 开始执行工具: {tool_name}")
                    try:
                        logger.info(f"call_tool: 参数: {arguments}")
                        result = await _execute_tool_safely(tool, arguments)
                        
                        logger.info(f"call_tool: 工具执行结果: {result}")
                        tool_results.append(f"工具 {tool_name} 的执行结果: {result}")
                    except Exception as e:
                        error_msg = f"工具 {tool_name} 执行错误: {str(e)}"
                        logger.error(f"call_tool: {error_msg}", exc_info=True)
                        tool_results.append(error_msg)
                else:
                    error_msg = f"工具 {tool_name} 不存在。可用工具: {', '.join([t.name for t in state['tools']])}"
                    logger.error(f"call_tool: {error_msg}")
                    tool_results.append(error_msg)
            
            tool_msgs: list[ToolMessage] = []
            for i, tr in enumerate(tool_results):
                tcid = (last_message.tool_calls[i].get("id") if i < len(last_message.tool_calls) else None) or f"tool-{i}"
                tool_msgs.append(ToolMessage(content=tr, tool_call_id=str(tcid)))
            return {"messages": tool_msgs}
        
        # 回退到文本解析（兼容旧格式）
        content = last_message.content
        logger.info(f"call_tool: 消息内容 (前200字符): {str(content)[:200]}...")
        
        try:
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                json_str = content.split("```")[1].split("```")[0].strip()
            else:
                json_str = content
            
            logger.info(f"call_tool: 提取的 JSON: {json_str}")
            tool_call = json.loads(json_str)
            tool_name = tool_call.get("tool")
            arguments = normalize_tool_args(tool_name, _get_tool_call_arguments(tool_call), state["tools"])
            if tool_name == "volces-icon_generate_app_icon" and not (arguments.get("description") or "").strip():
                fallback = _extract_description_from_content(str(last_message.content or ""), tool_name)
                if fallback:
                    arguments["description"] = fallback
                    logger.info(f"call_tool: 已从 content 补全 description，长度: {len(fallback)}")
            logger.info(f"call_tool: 工具名称: {tool_name}, 参数: {arguments}")
            logger.info(f"call_tool: 可用工具列表: {[t.name for t in state['tools']]}")
            
            # 查找工具（若不存在则尝试纠错：模型可能将多个工具名拼接，如 amap-maps_maps_geoamap-maps_maps_weather）
            tool = None
            resolved_name: str | None = None
            for t in state["tools"]:
                if t.name == tool_name:
                    tool = t
                    logger.info(f"call_tool: 找到工具: {tool_name}")
                    break
            if not tool:
                resolved_name = _resolve_mangled_tool_name(tool_name, [t.name for t in state["tools"]])
                if resolved_name:
                    tool_name = resolved_name
                    for t in state["tools"]:
                        if t.name == tool_name:
                            tool = t
                            logger.info(f"call_tool: 工具名纠错后使用: {tool_name}")
                            break
            
            if tool:
                logger.info(f"call_tool: 开始执行工具: {tool_name}")
                logger.info(f"call_tool: 参数: {arguments}")
                try:
                    result = await _execute_tool_safely(tool, arguments)
                except Exception as e:
                    error_msg = f"工具 {tool_name} 执行错误: {str(e)}"
                    logger.error(f"call_tool: {error_msg}", exc_info=True)
                    result = error_msg
                
                logger.info(f"call_tool: 工具执行结果: {result}")
                if resolved_name:
                    result = f"{result}\n\n（注意：您填写了拼接后的工具名，已仅执行第一个工具「{tool_name}」。请在下一条回复中单独调用其余工具，每次一个。）"
                return {
                    "messages": [
                        HumanMessage(content=f"工具 {tool_name} 的执行结果: {result}")
                    ]
                }
            else:
                error_msg = f"工具 {tool_name} 不存在。可用工具: {', '.join([t.name for t in state['tools']])}"
                logger.error(f"call_tool: {error_msg}")
                return {
                    "messages": [
                        HumanMessage(content=error_msg)
                    ]
                }
        except json.JSONDecodeError as e:
            error_msg = f"工具调用 JSON 解析错误: {str(e)}"
            logger.error(f"call_tool: {error_msg}")
            return {
                "messages": [
                    HumanMessage(content=error_msg)
                ]
            }
        except Exception as e:
            error_msg = f"工具调用错误: {str(e)}"
            logger.error(f"call_tool: {error_msg}", exc_info=True)
            return {
                "messages": [
                    HumanMessage(content=error_msg)
                ]
            }
    
    async def _tool_runner(state: AgentState, tools_list: list[ToolSpec]):
        return await call_tool(state)

    return SimpleAgent(
        llm=llm,
        tools=tools,
        system_prompt=system_prompt,
        tool_runner=_tool_runner,
        timeout_s=float(_LLM_AGENT_TIMEOUT),
        max_steps=_SKILL_AGENT_MAX_STEPS,
        max_repeated_tool_rounds=_SKILL_AGENT_MAX_REPEATED_TOOL_ROUNDS,
    )


def create_skill_execution_agent(
    llm,
    tools: list[ToolSpec],
    skill_full_content: str,
    extra_system_prompt: str = "",
    expert_self_awareness: str = "",
    t_request_start: float = None,
    stop_after_tool_names: tuple[str, ...] = (),
    synthesize_after_tools: bool = True,
    synthesize_after_read_file_paths: tuple[str, ...] = (),
):
    """
    创建技能执行 Agent：仅用于「第二次调用」。
    系统提示词 = 用户设置 + 选中技能的完整内容 + 工具列表。
    按 skill 步骤执行，某一步需要时调用 MCP 工具。
    """
    logger.debug(f"创建技能执行 Agent，工具数量: {len(tools)}，技能内容长度: {len(skill_full_content)}")

    system_prompt = ""
    if extra_system_prompt and extra_system_prompt.strip():
        system_prompt += extra_system_prompt.strip() + "\n\n"
    system_prompt += """你是一个有用的 AI 助手，正在按以下技能说明执行用户请求。

"""
    system_prompt += skill_full_content
    if expert_self_awareness and expert_self_awareness.strip():
        system_prompt += "\n\n---\n\n" + expert_self_awareness.strip()
    system_prompt += """

你可以使用以下工具：
"""
    for tool in tools:
        system_prompt += f"- {tool.name}: {tool.description}\n"
    if tools:
        logger.debug("已添加工具指令到系统提示词")
    # 若包含 Exa 工具，注入 Exa MCP 使用说明（仅调用 exa 时生效）
    if any(t.name == "exa_web_search_exa" for t in tools):
        system_prompt += """
## Exa 搜索工具使用说明
调用 exa_web_search_exa 时**必须**使用参数名 query（必需）传递搜索关键词，不要使用 __arg1。示例：{"query": "北京 烟花 燃放", "numResults": 10}。
可选参数：numResults（数量）、livecrawl（'fallback'|'preferred'|'always'|'never'）、type（'auto'|'fast'）。type 不要用 'news' 等无效值。

"""
    system_prompt += """
当你需要使用工具时，**必须**使用模型的结构化工具调用（tool_calls / function calling）来调用工具；
不要输出任何形如 `{"action":"tool_call", ...}` 的 JSON 作为正文（那是历史兼容格式，已移除）。

当你不需要使用工具时，直接回复用户的问题。

"""
    system_prompt += _skill_execution_extra_instructions(tools)

    async def call_model(state: AgentState, config=None):
        messages = list(state["messages"])
        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=system_prompt)] + messages

        client = llm.get_client()
        if tools:
            client = bind_tools_compat(client, tools)
        msg_summary = []
        for i, m in enumerate(messages):
            role = getattr(m, "type", type(m).__name__.replace("Message", "").lower())
            content = getattr(m, "content", str(m)) or ""
            s = str(content)
            if role == "system":
                msg_summary.append(f"  [{i+1}] {role}: 共 {len(s)} 字符，前150字: {s[:150]}…" if len(s) > 150 else f"  [{i+1}] {role}: {s}")
            else:
                preview = (s[:150] + "…") if len(s) > 150 else s
                msg_summary.append(f"  [{i+1}] {role}: {preview}")
        logger.debug("输入大模型的提示词（技能执行）:\n" + "\n".join(msg_summary))
        t0 = time.perf_counter()
        elapsed = (t0 - t_request_start) if t_request_start else 0
        logger.debug(f"call_model: 开始调用 LLM (流程已耗时 {elapsed:.2f}s)")
        try:
            # 优先 astream：token 级流式，供 stream_mode="messages" 推送；传入 config 以支持 tracer（Python < 3.11 需显式传递）
            invoke_kw = {"config": config} if config is not None else {}

            async def _consume_stream():
                resp = None
                async for chunk in client.astream(messages, **invoke_kw):
                    resp = chunk if resp is None else resp + chunk
                return resp if resp is not None else AIMessage(content="")

            try:
                response = await asyncio.wait_for(
                    _consume_stream(), timeout=float(_LLM_AGENT_TIMEOUT)
                )
            except Exception as stream_err:
                logger.warning(f"call_model: astream 失败，回退到 ainvoke: {stream_err}")
                response = await asyncio.wait_for(
                    client.ainvoke(messages, **invoke_kw), timeout=float(_LLM_AGENT_TIMEOUT)
                )
            logger.debug(f"call_model LLM 完成: {time.perf_counter() - t0:.2f}s")
        except asyncio.TimeoutError:
            logger.error(f"call_model: LLM 调用超时（{_LLM_AGENT_TIMEOUT}秒）")
            response = AIMessage(content="抱歉，模型响应超时，请稍后重试。")
        return {"messages": messages + [response]}

    def should_continue(state: AgentState):
        messages = state["messages"]
        last_message = messages[-1]
        if isinstance(last_message, AIMessage):
            if hasattr(last_message, "tool_calls") and last_message.tool_calls:
                return "call_tool"
            if isinstance(last_message.content, str) and "tool_call" in last_message.content.lower():
                try:
                    if "```json" in last_message.content:
                        json_str = last_message.content.split("```json")[1].split("```")[0].strip()
                    elif "```" in last_message.content:
                        json_str = last_message.content.split("```")[1].split("```")[0].strip()
                    else:
                        json_str = last_message.content
                    tool_call = json.loads(json_str)
                    if tool_call.get("action") == "tool_call":
                        return "call_tool"
                except Exception:
                    pass
        return "end"

    async def call_tool(state: AgentState):
        return await _call_tool_impl(state, tools)

    async def _tool_runner(state: AgentState, tools_list: list[ToolSpec]):
        return await _call_tool_impl(state, tools_list)

    return SimpleAgent(
        llm=llm,
        tools=tools,
        system_prompt=system_prompt,
        tool_runner=_tool_runner,
        timeout_s=float(_LLM_AGENT_TIMEOUT),
        max_steps=_SKILL_AGENT_MAX_STEPS,
        max_repeated_tool_rounds=_SKILL_AGENT_MAX_REPEATED_TOOL_ROUNDS,
        stop_after_tool_names=stop_after_tool_names,
        synthesize_after_tools=synthesize_after_tools,
        synthesize_after_read_file_paths=synthesize_after_read_file_paths,
    )


async def _call_tool_impl(state: AgentState, tools: list[ToolSpec]):
    """工具调用实现（供 create_skill_execution_agent 复用）"""
    messages = state["messages"]
    last_message = messages[-1]
    tool_results = []
    tool_attempt_debug: list[dict] = []
    tool_calls_trace: list[dict] = []
    tool_raw_outputs: list[str] = []
    max_tool_result_chars = 4000
    tool_result_cache = state.get("tool_result_cache") if isinstance(state, dict) else None
    if not isinstance(tool_result_cache, dict):
        tool_result_cache = {}

    def _cache_key_for_tool(tool_name: str, arguments: dict) -> str:
        try:
            args_key = json.dumps(arguments or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except Exception:
            args_key = str(arguments or {})
        return f"{tool_name}:{args_key}"

    def _cacheable_script_result(result: object) -> bool:
        try:
            parsed = json.loads(str(result or ""))
        except Exception:
            return True
        if isinstance(parsed, dict) and parsed.get("ok") is False:
            return False
        stdout = parsed.get("stdout") if isinstance(parsed, dict) else None
        if isinstance(stdout, str) and stdout.strip().startswith("{"):
            try:
                stdout_payload = json.loads(stdout)
            except Exception:
                stdout_payload = None
            if isinstance(stdout_payload, dict) and stdout_payload.get("ok") is False:
                return False
        return True

    def _script_done_instruction(*, cached: bool = False) -> str:
        prefix = "已复用同一轮内相同参数的脚本执行结果。" if cached else "脚本已执行完成。"
        return (
            f"\n\n{prefix}请直接基于上方工具结果中的 stdout/stderr/returncode 生成最终答复。"
            "stdout/stderr 是返回字段，不是工作区文件；不要调用 read_file 读取 stdout、stderr 或 scripts/<脚本名>，"
            "也不要再次调用同一个脚本和相同参数。"
        )

    def _tool_message_content(tool_name: str, result_for_prompt: str, *, cached: bool = False) -> str:
        suffix = _script_done_instruction(cached=cached) if tool_name.startswith("run_skill_script_") else ""
        return f"工具 {tool_name} 的执行结果: {result_for_prompt}{suffix}"

    def _audio_transcription_text_for_prompt(tool_name: str, result: object) -> str | None:
        if not tool_name.startswith("run_skill_script_audio-transcription"):
            return None
        text = str(result) if not isinstance(result, str) else result
        try:
            outer = json.loads(text)
        except Exception:
            return None
        stdout = outer.get("stdout") if isinstance(outer, dict) else None
        if not isinstance(stdout, str) or not stdout.strip():
            return None
        try:
            payload = json.loads(stdout.strip())
        except Exception:
            return stdout.strip()
        if not isinstance(payload, dict):
            return stdout.strip()
        transcript = payload.get("text")
        if not isinstance(transcript, str) or not transcript.strip():
            return stdout.strip()
        return transcript.strip()

    def _safe_tool_result_for_prompt(result: object, tool_name: str = "") -> str:
        """限制工具结果进入模型上下文的长度，避免超长内容（如 base64 图片）撑爆 token。"""
        audio_transcription_text = _audio_transcription_text_for_prompt(tool_name, result)
        if audio_transcription_text is not None:
            return audio_transcription_text
        text = str(result) if not isinstance(result, str) else result
        stripped = text.strip()
        if stripped.startswith("data:image/"):
            preview = stripped[:120]
            return (
                f"[图片数据已生成，原始 data URL 过长，已省略；长度约 {len(stripped)} 字符]\n"
                f"预览前缀: {preview}..."
            )
        if len(text) > max_tool_result_chars:
            return text[:max_tool_result_chars].rstrip() + "\n...[工具结果已截断]"
        return text

    def _extract_paths_from_last_user(messages: Sequence[BaseMessage]) -> list[str]:
        """从最近一条用户消息中提取可能的文件路径列表（用于 rename 参数兜底）。"""
        import re

        last_user = None
        for m in reversed(messages):
            from langchain_core.messages import HumanMessage as _HM

            if isinstance(m, _HM):
                last_user = m
                break
        if last_user is None:
            return []
        content = str(getattr(last_user, "content", "") or "").strip()
        if not content:
            return []
        paths: list[str] = []
        # 1) 先提取反引号中的候选
        for c in re.findall(r"`([^`]+)`", content):
            s = c.strip()
            if ("/" in s or "." in s) and s not in paths:
                paths.append(s)
        # 2) 再补充普通文本中的 xxx.yyy 样式
        for m in re.findall(r"([A-Za-z0-9_\-./]+\.[A-Za-z0-9]+)", content):
            s = m.strip()
            if s not in paths:
                paths.append(s)
        return paths

    def normalize_tool_args(tool_name: str, arguments: dict, tools_list: Sequence[ToolSpec]) -> dict:
        """与主 call_tool 一致：MCP 工具用 schema 做 __arg1→首参 等映射。"""
        args = dict(arguments) if arguments else {}
        if tool_name.startswith("run_skill_script_"):
            return args
        idx = tool_name.find("_")
        if idx >= 0:
            server_id = tool_name[:idx]
            original_tool_name = tool_name[idx + 1:]
            input_schema = _get_mcp_input_schema(tool_name, tools_list)
            from app.mcp.manager import normalize_mcp_kwargs_for_call
            return normalize_mcp_kwargs_for_call(server_id, original_tool_name, args, input_schema=input_schema)
        # 非 MCP 工具（read_file 等）直接返回
        return args

    workspace_id = str(state.get("workspace_id") or "") if isinstance(state, dict) else ""

    def _resolve_tool_name_for_skill_call(raw_name: str, tools_list: Sequence[ToolSpec]) -> str:
        requested = str(raw_name or "").strip()
        valid_names = [getattr(t, "name", "") for t in tools_list if getattr(t, "name", "")]
        if requested in valid_names:
            return requested
        # 兼容非法字符 skill_id：run_skill_script_新-skill -> run_skill_script_<sanitized>
        if requested.startswith("run_skill_script_"):
            skill_suffix = requested[len("run_skill_script_") :]
            normalized = build_skill_script_tool_name(skill_suffix)
            if normalized in valid_names:
                return normalized
        # 别名兼容：群聊里常见模型按单聊习惯调用 run_skill_script
        if requested == "run_skill_script":
            candidates = [n for n in valid_names if n.startswith("run_skill_script_")]
            if len(candidates) == 1:
                return candidates[0]
        resolved = _resolve_mangled_tool_name(requested, valid_names)
        return resolved or requested

    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        for tool_call in last_message.tool_calls:
            requested_tool_name = tool_call.get("name") or tool_call.get("id", "")
            tool_name = _resolve_tool_name_for_skill_call(requested_tool_name, state["tools"])
            tool_call_id = str(tool_call.get("id") or tool_call.get("tool_call_id") or tool_name or "tool")
            arguments = normalize_tool_args(tool_name, _get_tool_call_arguments(tool_call), tools)
            tool = None
            for t in state["tools"]:
                if t.name == tool_name:
                    tool = t
                    break
            if tool:
                if tool_name == "audio-asr_transcribe_audio_file":
                    _apply_audio_asr_path_from_user_message(arguments, messages, workspace_id)
                # read_file：从最近用户消息补全 path，或在模型沿用旧路径时用用户本条消息覆盖
                if _tool_is_workspace_plain_read_file(tool_name):
                    _apply_read_file_path_from_user_message(arguments, messages)
                # rename_workspace_file 兜底：若缺 path/new_name，则从最近用户消息中提取两个路径
                if tool_name == "rename_workspace_file":
                    has_src = bool(arguments.get("path"))
                    has_dst = bool(arguments.get("new_name"))
                    if not (has_src and has_dst):
                        candidates = _extract_paths_from_last_user(messages)
                        if len(candidates) >= 2:
                            arguments.setdefault("path", candidates[0])
                            arguments.setdefault("new_name", candidates[1])
                tool_attempt_debug.append({
                    "requested_tool": requested_tool_name,
                    "resolved_tool": tool_name,
                    "matched": True,
                    "available_tools": [t.name for t in state["tools"]][:30],
                })
                try:
                    t_tool = time.perf_counter()
                    tool_calls_trace.append({"tool": tool_name, "arguments": arguments})
                    cache_key = _cache_key_for_tool(tool_name, arguments)
                    cached_entry = tool_result_cache.get(cache_key) if tool_name.startswith("run_skill_script_") else None
                    if isinstance(cached_entry, dict):
                        result = cached_entry.get("raw", "")
                        result_for_prompt = str(cached_entry.get("prompt") or _safe_tool_result_for_prompt(result, tool_name))
                        logger.info(
                            "sandbox_script_cache_hit tool=%s args_hash=%s raw_len=%s",
                            tool_name,
                            str(abs(hash(cache_key))),
                            len(str(result)),
                        )
                        tool_attempt_debug.append({
                            "source": "run_skill_script_cache_hit",
                            "tool": tool_name,
                            "matched": True,
                        })
                        tool_results.append(ToolMessage(content=_tool_message_content(tool_name, result_for_prompt, cached=True), tool_call_id=tool_call_id))
                        tool_raw_outputs.append(str(result))
                    else:
                        result = await _execute_tool_safely(tool, arguments)
                        result_for_prompt = _safe_tool_result_for_prompt(result, tool_name)
                        if tool_name.startswith("run_skill_script_") and _cacheable_script_result(result):
                            tool_result_cache[cache_key] = {"raw": str(result), "prompt": result_for_prompt}
                            logger.debug(
                                "sandbox_script_cache_store tool=%s args_hash=%s raw_len=%s",
                                tool_name,
                                str(abs(hash(cache_key))),
                                len(str(result)),
                            )
                        tool_results.append(ToolMessage(content=_tool_message_content(tool_name, result_for_prompt), tool_call_id=tool_call_id))
                        tool_raw_outputs.append(str(result))
                except Exception as e:
                    tool_results.append(ToolMessage(content=f"工具 {tool_name} 执行错误: {str(e)}", tool_call_id=tool_call_id))
                    tool_raw_outputs.append(f"工具 {tool_name} 执行错误: {str(e)}")
            else:
                tool_attempt_debug.append({
                    "requested_tool": requested_tool_name,
                    "resolved_tool": tool_name,
                    "matched": False,
                    "available_tools": [t.name for t in state["tools"]][:30],
                })
                if tool_name == "read_file":
                    tool_results.append(ToolMessage(
                        content="工具 read_file 已废弃。请改用 file-reader_read_file 读取工作区文件，path 填工作区内相对路径（如 test.md 或 workspaces/<会话ID>/test.md）。",
                        tool_call_id=tool_call_id,
                    ))
                else:
                    tool_results.append(ToolMessage(content=f"工具 {tool_name} 不存在。可用: {', '.join([t.name for t in state['tools']])}", tool_call_id=tool_call_id))
        return {
            "messages": tool_results,
            "tool_attempt_debug": tool_attempt_debug,
            "tool_calls": tool_calls_trace,
            "tool_raw_outputs": tool_raw_outputs,
        }

    content = last_message.content
    try:
        if "```json" in content:
            json_str = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            json_str = content.split("```")[1].split("```")[0].strip()
        else:
            json_str = content
        tool_call = json.loads(json_str)
        requested_tool_name = tool_call.get("tool")
        tool_name = _resolve_tool_name_for_skill_call(requested_tool_name, state["tools"])
        arguments = normalize_tool_args(tool_name, _get_tool_call_arguments(tool_call), tools)
        tool = None
        for t in state["tools"]:
            if t.name == tool_name:
                tool = t
                break
        if tool:
            if tool_name == "audio-asr_transcribe_audio_file":
                _apply_audio_asr_path_from_user_message(arguments, messages, workspace_id)
            if _tool_is_workspace_plain_read_file(tool_name):
                _apply_read_file_path_from_user_message(arguments, messages)
            if tool_name == "rename_workspace_file":
                has_src = bool(arguments.get("path"))
                has_dst = bool(arguments.get("new_name"))
                if not (has_src and has_dst):
                    candidates = _extract_paths_from_last_user(messages)
                    if len(candidates) >= 2:
                        arguments.setdefault("path", candidates[0])
                        arguments.setdefault("new_name", candidates[1])
            tool_attempt_debug.append({
                "requested_tool": requested_tool_name,
                "resolved_tool": tool_name,
                "matched": True,
                "available_tools": [t.name for t in state["tools"]][:30],
            })
            try:
                tool_calls_trace.append({"tool": tool_name, "arguments": arguments})
                cache_key = _cache_key_for_tool(tool_name, arguments)
                cached_entry = tool_result_cache.get(cache_key) if tool_name.startswith("run_skill_script_") else None
                if isinstance(cached_entry, dict):
                    result = cached_entry.get("raw", "")
                    result_for_prompt = str(cached_entry.get("prompt") or _safe_tool_result_for_prompt(result, tool_name))
                    logger.info(
                        "sandbox_script_cache_hit tool=%s args_hash=%s raw_len=%s",
                        tool_name,
                        str(abs(hash(cache_key))),
                        len(str(result)),
                    )
                    tool_attempt_debug.append({
                        "source": "run_skill_script_cache_hit",
                        "tool": tool_name,
                        "matched": True,
                    })
                else:
                    result = await _execute_tool_safely(tool, arguments)
                    result_for_prompt = _safe_tool_result_for_prompt(result, tool_name)
                    if tool_name.startswith("run_skill_script_") and _cacheable_script_result(result):
                        tool_result_cache[cache_key] = {"raw": str(result), "prompt": result_for_prompt}
                        logger.debug(
                            "sandbox_script_cache_store tool=%s args_hash=%s raw_len=%s",
                            tool_name,
                            str(abs(hash(cache_key))),
                            len(str(result)),
                        )
                tool_raw_outputs.append(str(result))
                # 注意：当模型没有返回结构化 tool_calls（而是通过 content JSON 回退解析）时，
                # 不能向 OpenAI ChatCompletions 发送 role=tool 的消息（必须紧跟在带 tool_calls 的 assistant 之后）。
                # 这里将工具输出作为普通 HumanMessage 反馈给模型，确保消息序列合法。
                return {
                    "messages": [HumanMessage(content=_tool_message_content(tool_name, result_for_prompt, cached=isinstance(cached_entry, dict)))],
                    "tool_attempt_debug": tool_attempt_debug,
                    "tool_calls": tool_calls_trace,
                    "tool_raw_outputs": tool_raw_outputs,
                }
            except Exception as e:
                tool_raw_outputs.append(f"工具 {tool_name} 执行错误: {str(e)}")
                return {
                    "messages": [HumanMessage(content=f"工具 {tool_name} 执行错误: {str(e)}")],
                    "tool_attempt_debug": tool_attempt_debug,
                    "tool_calls": tool_calls_trace,
                    "tool_raw_outputs": tool_raw_outputs,
                }
        tool_attempt_debug.append({
            "requested_tool": requested_tool_name,
            "resolved_tool": tool_name,
            "matched": False,
            "available_tools": [t.name for t in state["tools"]][:30],
        })
        if tool_name == "read_file":
            return {
                "messages": [HumanMessage(content="工具 read_file 已废弃。请改用 file-reader_read_file 读取工作区文件，path 填工作区内相对路径（如 test.md 或 workspaces/<会话ID>/test.md）。")],
                "tool_attempt_debug": tool_attempt_debug,
                "tool_calls": tool_calls_trace,
                "tool_raw_outputs": tool_raw_outputs,
            }
        return {
            "messages": [HumanMessage(content=f"工具 {tool_name} 不存在")],
            "tool_attempt_debug": tool_attempt_debug,
            "tool_calls": tool_calls_trace,
            "tool_raw_outputs": tool_raw_outputs,
        }
    except Exception as e:
        return {
            "messages": [HumanMessage(content=f"工具调用解析错误: {str(e)}")],
            "tool_attempt_debug": tool_attempt_debug,
            "tool_calls": tool_calls_trace,
            "tool_raw_outputs": tool_raw_outputs,
        }
