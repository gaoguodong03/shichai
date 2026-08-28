"""Verify model-authored expert file delivery against workspace facts."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.agent.group_chat_tool_trace import guard_unverified_delivery_claims
from app.agent.structured_output_contracts import ExpertFinalMessageBody


@dataclass(frozen=True)
class ExpertDeliveryVerification:
    message: ExpertFinalMessageBody
    unverified_paths: tuple[str, ...]
    claim_guard_applied: bool

    @property
    def is_verified(self) -> bool:
        return not self.unverified_paths and not self.claim_guard_applied


def _workspace_path_exists(workspace_root: Path | None, path: str, *, directory: bool) -> bool:
    if workspace_root is None:
        return False
    root = workspace_root.resolve()
    try:
        target = (root / str(path or "")).resolve()
        target.relative_to(root)
    except (OSError, ValueError):
        return False
    return target.is_dir() if directory else target.is_file()


def _tool_delivery_evidence(
    tool_results: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    calls: list[dict[str, Any]] = []
    output_texts: list[str] = []
    for result in tool_results or []:
        if not isinstance(result, dict):
            continue
        tool_call = result.get("tool_call") if isinstance(result.get("tool_call"), dict) else {}
        if tool_call:
            calls.append(
                {
                    "tool": tool_call.get("name"),
                    "arguments": tool_call.get("arguments") if isinstance(tool_call.get("arguments"), dict) else {},
                }
            )
        output = result.get("output") if isinstance(result.get("output"), dict) else {}
        for key in ("content", "stdout", "stderr"):
            value = output.get(key)
            if value not in (None, ""):
                output_texts.append(str(value))
        normalized_payload = {
            "execution_status": result.get("execution_status"),
            **output,
        }
        try:
            output_texts.append(json.dumps(normalized_payload, ensure_ascii=False, default=str))
        except Exception:
            pass
    return calls, output_texts


def verify_expert_message_delivery(
    message: ExpertFinalMessageBody,
    *,
    tool_results: list[dict[str, Any]] | None,
    workspace_root: Path | None,
) -> ExpertDeliveryVerification:
    """Remove nonexistent file refs and guard file-delivery claims without tool proof."""
    calls, output_texts = _tool_delivery_evidence(tool_results)
    guarded_content = guard_unverified_delivery_claims(
        message.content,
        tool_calls=calls,
        tool_output_texts=output_texts,
        workspace_root=workspace_root,
    )

    verified_attachments = []
    verified_artifacts = []
    unverified_paths: list[str] = []
    for attachment in message.attachments:
        if _workspace_path_exists(workspace_root, attachment.path, directory=False):
            verified_attachments.append(attachment)
        else:
            unverified_paths.append(attachment.path)
    for artifact in message.artifacts:
        if _workspace_path_exists(workspace_root, artifact.path, directory=artifact.type == "directory"):
            verified_artifacts.append(artifact)
        else:
            unverified_paths.append(artifact.path)

    deduped_paths = tuple(dict.fromkeys(path for path in unverified_paths if path))
    verified_message = message.model_copy(
        update={
            "content": guarded_content,
            "attachments": verified_attachments,
            "artifacts": verified_artifacts,
        }
    )
    return ExpertDeliveryVerification(
        message=verified_message,
        unverified_paths=deduped_paths,
        claim_guard_applied=guarded_content != message.content,
    )
