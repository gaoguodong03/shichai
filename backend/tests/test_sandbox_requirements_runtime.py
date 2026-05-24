import base64

from app.agent import sandbox_requirements_runtime as rt


def test_requirements_summary_normalizes_package_keys():
    out = rt.requirements_package_summary("Pandas>=2\n# comment\nxlrd==2.0.2\npandas<3\n")

    assert out["count"] == 2
    assert out["preview"] == ["pandas", "xlrd"]
    assert out["has_playwright"] is False


def test_requirements_b64_strips_empty_content():
    assert rt.requirements_b64("  \n") == ""

    encoded = rt.requirements_b64("pendulum==3.2.0\n")

    assert base64.b64decode(encoded).decode("utf-8") == "pendulum==3.2.0"


def test_command_exit_code_handles_common_adapter_shapes():
    assert rt.command_exit_code({"exit_code": 7}) == 7
    assert rt.command_exit_code({"ok": False}) == 1
    assert rt.command_exit_code({"stdout": "ok"}) is None
