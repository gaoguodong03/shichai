"""Pip-backed Python dependency coverage checks for Skill requirements."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Tuple

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name


Runner = Callable[..., Any]


def _requirement_lines(raw: str | Iterable[str]) -> List[str]:
    if isinstance(raw, str):
        source = raw.splitlines()
    else:
        source = [str(x or "") for x in raw]
    out: List[str] = []
    seen: set[str] = set()
    for line in source:
        item = str(line or "").strip()
        if not item or item.startswith("#"):
            continue
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _package_set_from_report(report: Dict[str, Any]) -> Dict[str, str]:
    packages: Dict[str, str] = {}
    for item in report.get("install") or []:
        if not isinstance(item, dict):
            continue
        meta = item.get("metadata")
        if not isinstance(meta, dict):
            continue
        name = str(meta.get("name") or "").strip()
        version = str(meta.get("version") or "").strip()
        if not name:
            continue
        packages[str(canonicalize_name(name))] = version
    return packages


def _pip_resolve(
    requirements: List[str],
    *,
    runner: Runner,
    python_executable: str,
    timeout_seconds: int,
) -> Tuple[Dict[str, str], str]:
    if not requirements:
        return {}, ""
    with tempfile.TemporaryDirectory(prefix="st49-pip-resolve-") as tmp:
        tmp_dir = Path(tmp)
        requirements_path = tmp_dir / "requirements.txt"
        report_path = tmp_dir / "report.json"
        requirements_path.write_text("\n".join(requirements) + "\n", encoding="utf-8")
        cmd = [
            python_executable,
            "-m",
            "pip",
            "install",
            "--dry-run",
            "--ignore-installed",
            "--disable-pip-version-check",
            "--report",
            str(report_path),
            "-r",
            str(requirements_path),
        ]
        proc = runner(cmd, capture_output=True, text=True, timeout=timeout_seconds)
        if getattr(proc, "returncode", 1) != 0:
            err = str(getattr(proc, "stderr", "") or getattr(proc, "stdout", "") or "pip resolver failed").strip()
            return {}, err
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            return {}, f"pip report parse failed: {e}"
        return _package_set_from_report(report), ""


def _inactive_marker(req: Requirement) -> bool:
    try:
        return req.marker is not None and not req.marker.evaluate()
    except Exception:
        return False


def resolve_dependency_status(
    *,
    settings_requirements: str | Iterable[str],
    skill_requirements: Iterable[str],
    runner: Runner = subprocess.run,
    python_executable: str = sys.executable,
    timeout_seconds: int = 90,
) -> Dict[str, Any]:
    """Return whether Skill requirements are covered by current settings requirements.

    The coverage check delegates dependency closure computation to pip. For each
    Skill requirement, it compares the dry-run resolved package set for settings
    requirements with the set for settings plus that Skill requirement.
    """

    settings_lines = _requirement_lines(settings_requirements)
    skill_lines = _requirement_lines(skill_requirements)
    statuses: List[Dict[str, Any]] = []

    settings_packages, settings_error = _pip_resolve(
        settings_lines,
        runner=runner,
        python_executable=python_executable,
        timeout_seconds=timeout_seconds,
    )
    if settings_error:
        return {
            "resolver": {"ok": False, "message": settings_error},
            "requirements": [
                {
                    "requirement": line,
                    "name": "",
                    "status": "unknown",
                    "message": settings_error,
                    "missing_packages": [],
                }
                for line in skill_lines
            ],
        }

    for line in skill_lines:
        try:
            req = Requirement(line)
        except InvalidRequirement as e:
            statuses.append(
                {
                    "requirement": line,
                    "name": "",
                    "status": "invalid",
                    "message": str(e),
                    "missing_packages": [],
                }
            )
            continue

        name = str(canonicalize_name(req.name))
        if _inactive_marker(req):
            statuses.append(
                {
                    "requirement": line,
                    "name": name,
                    "status": "skipped",
                    "message": "environment marker is not active",
                    "missing_packages": [],
                }
            )
            continue

        combined_packages, combined_error = _pip_resolve(
            settings_lines + [line],
            runner=runner,
            python_executable=python_executable,
            timeout_seconds=timeout_seconds,
        )
        if combined_error:
            statuses.append(
                {
                    "requirement": line,
                    "name": name,
                    "status": "conflict",
                    "message": combined_error,
                    "missing_packages": [],
                }
            )
            continue

        missing = [
            {"name": pkg, "version": version}
            for pkg, version in sorted(combined_packages.items())
            if settings_packages.get(pkg) != version
        ]
        if not missing:
            status = "satisfied"
            message = ""
        elif name in settings_packages:
            status = "conflict"
            message = "settings requirements resolve a different package version or dependency closure"
        else:
            status = "missing"
            message = "not covered by settings requirements resolved closure"
        statuses.append(
            {
                "requirement": line,
                "name": name,
                "status": status,
                "message": message,
                "covered_by": "settings_resolved_closure" if status == "satisfied" else "",
                "missing_packages": missing,
            }
        )

    return {"resolver": {"ok": True, "message": ""}, "requirements": statuses}
