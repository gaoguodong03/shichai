from __future__ import annotations

from pathlib import Path


def test_volces_icon_has_no_hardcoded_local_debug_path():
    source = Path("backend/app/mcp/stdio/volces_icon.py").read_text(encoding="utf-8")
    assert "/Users/ggd/" not in source
    assert "mycode/DHA/.cursor/debug.log" not in source
