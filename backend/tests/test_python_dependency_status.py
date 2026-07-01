from __future__ import annotations

import json
from pathlib import Path

from app.core.python_dependency_status import resolve_dependency_status


class _FakeCompletedProcess:
    def __init__(self, returncode: int = 0, stderr: str = ""):
        self.returncode = returncode
        self.stdout = ""
        self.stderr = stderr


def _runner_with_reports(reports_by_requirements: dict[tuple[str, ...], dict]):
    def runner(cmd, **_kwargs):
        report_path = Path(cmd[cmd.index("--report") + 1])
        req_path = Path(cmd[cmd.index("-r") + 1])
        requirements = tuple(x.strip() for x in req_path.read_text(encoding="utf-8").splitlines() if x.strip())
        report = reports_by_requirements.get(requirements)
        if report is None:
            return _FakeCompletedProcess(returncode=1, stderr=f"no report for {requirements!r}")
        report_path.write_text(json.dumps(report), encoding="utf-8")
        return _FakeCompletedProcess()

    return runner


def _report(*packages: tuple[str, str]) -> dict:
    return {
        "install": [
            {"metadata": {"name": name, "version": version}}
            for name, version in packages
        ]
    }


def test_resolve_dependency_status_accepts_transitive_dependency_from_settings():
    runner = _runner_with_reports(
        {
            ("biglib==1.0",): _report(("biglib", "1.0"), ("smalllib", "2.0")),
            ("biglib==1.0", "smalllib>=1"): _report(("biglib", "1.0"), ("smalllib", "2.0")),
        }
    )

    result = resolve_dependency_status(
        settings_requirements="biglib==1.0\n",
        skill_requirements=["smalllib>=1"],
        runner=runner,
    )

    assert result["resolver"]["ok"] is True
    assert result["requirements"][0]["status"] == "satisfied"
    assert result["requirements"][0]["covered_by"] == "settings_resolved_closure"


def test_resolve_dependency_status_reports_missing_when_skill_changes_resolved_closure():
    runner = _runner_with_reports(
        {
            ("biglib==1.0",): _report(("biglib", "1.0")),
            ("biglib==1.0", "smalllib>=1"): _report(("biglib", "1.0"), ("smalllib", "2.0")),
        }
    )

    result = resolve_dependency_status(
        settings_requirements="biglib==1.0\n",
        skill_requirements=["smalllib>=1"],
        runner=runner,
    )

    item = result["requirements"][0]
    assert item["status"] == "missing"
    assert item["missing_packages"] == [{"name": "smalllib", "version": "2.0"}]


def test_resolve_dependency_status_reports_conflict_when_pip_cannot_resolve_combined_requirements():
    runner = _runner_with_reports({("smalllib==1",): _report(("smalllib", "1"))})

    result = resolve_dependency_status(
        settings_requirements="smalllib==1\n",
        skill_requirements=["smalllib==2"],
        runner=runner,
    )

    item = result["requirements"][0]
    assert item["status"] == "conflict"
    assert "no report" in item["message"]


def test_resolve_dependency_status_reports_invalid_skill_requirement():
    result = resolve_dependency_status(
        settings_requirements="",
        skill_requirements=["not a valid ==="],
        runner=_runner_with_reports({}),
    )

    assert result["resolver"]["ok"] is True
    assert result["requirements"][0]["status"] == "invalid"
