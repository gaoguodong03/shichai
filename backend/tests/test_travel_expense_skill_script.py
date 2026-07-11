from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "users"
    / "user-23a7ad6fe421441793838ff8fdff6eb1"
    / "resources"
    / "skills"
    / "travel-expense-calculator"
    / "scripts"
    / "extract_travel_standards.py"
)


def _run_script(*args: str) -> dict:
    if not SCRIPT.is_file():
        pytest.skip(f"travel expense script fixture not present: {SCRIPT}")
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(completed.stdout)


def test_travel_expense_script_runs_without_pandas_for_single_city():
    payload = _run_script("--query", "南京差旅住宿标准")

    assert payload["execution_status"] == "succeeded"
    assert "result_code" not in payload
    assert "message" not in payload
    assert payload["next_action"]["handoff"] == "user"
    assert payload["next_action"]["resume"] == "same_skill"
    assert payload["artifacts"] == []
    assert "江苏南京市（常规时段）住宿费标准" in payload["content"]
    assert "其他人员380元/人·天" in payload["content"]


def test_travel_expense_script_does_not_treat_person_type_as_other_region():
    payload = _run_script("--query", "北京上海广州深圳其他人员住宿标准")

    assert payload["execution_status"] == "succeeded"
    assert payload["next_action"]["handoff"] == "user"
    assert payload["next_action"]["resume"] == "same_skill"
    assert payload["artifacts"] == []
    assert "北京全市（常规时段）其他人员住宿费上限为500元/人·天" in payload["content"]
    assert "上海全市（常规时段）其他人员住宿费上限为500元/人·天" in payload["content"]
    assert "广东广州市（常规时段）其他人员住宿费上限为450元/人·天" in payload["content"]
    assert "深圳全市（常规时段）其他人员住宿费上限为450元/人·天" in payload["content"]
    assert "其他地区" not in payload["content"]


def test_travel_expense_script_handles_missing_place_as_keep():
    payload = _run_script("--query", "差旅费标准是多少")

    assert payload["execution_status"] == "blocked"
    assert "result_code" not in payload
    assert "message" not in payload
    assert "content" in payload
    assert payload["artifacts"] == []
    assert payload["next_action"]["handoff"] == "user"
    assert payload["next_action"]["resume"] == "same_skill"
