from __future__ import annotations

from pathlib import Path


def test_volces_icon_has_no_hardcoded_local_debug_path():
    backend_root = Path(__file__).resolve().parents[1]
    source = (backend_root / "app/mcp/stdio/volces_icon.py").read_text(encoding="utf-8")
    assert "/Users/ggd/" not in source
    assert "mycode/DHA/.cursor/debug.log" not in source


def test_volces_icon_does_not_append_local_debug_files():
    backend_root = Path(__file__).resolve().parents[1]
    source = (backend_root / "app/mcp/stdio/volces_icon.py").read_text(encoding="utf-8")
    assert "VOLCES_ICON_DEBUG_LOG" not in source
    assert "open(log_path" not in source
