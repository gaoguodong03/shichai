from __future__ import annotations

from typing import Any

from app.agent.structured_output_contracts import ArtifactRef


def collect_artifacts(tool_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collect strict public artifact refs from vNext tool_result.output.artifacts."""
    artifacts: list[dict[str, Any]] = []
    for result in tool_results or []:
        if not isinstance(result, dict):
            continue
        output = result.get("output") if isinstance(result.get("output"), dict) else {}
        raw_artifacts = output.get("artifacts")
        if not isinstance(raw_artifacts, list):
            continue
        for item in raw_artifacts:
            if not isinstance(item, dict):
                continue
            public_ref = {
                "type": item.get("type"),
                "name": item.get("name"),
                "path": item.get("path"),
            }
            try:
                artifacts.append(ArtifactRef.model_validate(public_ref).model_dump())
            except Exception:
                continue
    return artifacts
