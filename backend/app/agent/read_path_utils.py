"""read_file 路径规范化：剥离模型把中文说明与路径拼在同一参数里的情况。"""
from __future__ import annotations

import re

# 不用 \\b 结尾：在「路径.md」后紧跟中文时 \\b 往往不成立（\\w 含中日文），会导致无法匹配 note/test.md
_ASCII_REL_PATH_IN_JUNK = re.compile(
    r"([a-zA-Z0-9_\-]+(?:/[a-zA-Z0-9_\-]+)*\.(?:md|txt|json|yaml|yml|csv|html|htm|xml|py|ts|js|vue|css))"
    r"(?![a-zA-Z0-9_\-./])",
    re.I,
)
_ROOT_FILE_ASCII = re.compile(
    r"(?<![a-zA-Z0-9_\-./])([a-zA-Z0-9_\-]+\.(?:md|txt|json|yaml|yml|csv|html|htm|xml|py|ts|js|vue|css))"
    r"(?![a-zA-Z0-9_\-./])",
    re.I,
)


def strip_llm_junk_from_read_path(path: str) -> str:
    """若 path 混入「就是/路径就是」等说明性文字，只保留其中的工作区相对路径片段。"""
    p = (path or "").strip().replace("\\", "/")
    if not p or ".." in p:
        return ""
    m = _ASCII_REL_PATH_IN_JUNK.fullmatch(p)
    if m:
        return m.group(1)
    if "就是" not in p and "路径就是" not in p and "路径是" not in p:
        return p
    # 同一句里可能同时出现 note/test.md 与 test.md：优先带目录前缀的较长路径
    ascii_hits = [x.group(1) for x in _ASCII_REL_PATH_IN_JUNK.finditer(p)]
    if ascii_hits:
        return max(ascii_hits, key=lambda x: (x.count("/"), len(x)))
    m3 = _ROOT_FILE_ASCII.search(p)
    if m3:
        return m3.group(1)
    return p


def looks_like_url_or_remote_path(path: str) -> bool:
    """模型常把对话里的 GitHub 链接误当作本地 path；此类输入不应进工作区解析。"""
    p = (path or "").strip().replace("\\", "/")
    if not p:
        return False
    pl = p.lower()
    if pl.startswith("//"):
        return True
    if "://" in pl:
        return True
    # 无协议：整段以常见站点域名开头（如 github.com/org/...）
    if re.match(r"^[a-z0-9][a-z0-9.-]*\.[a-z]{2,}/", pl):
        return True
    if pl.startswith("www."):
        return True
    return False
