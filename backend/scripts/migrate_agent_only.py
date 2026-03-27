from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


KEY_RENAMES = {
    "dha_id": "agent_id",
    "dha_ids": "agent_ids",
    "leader_dha_id": "leader_agent_id",
    "suggested_add_dha_ids": "suggested_add_agent_ids",
    "suggested_add_dha_id": "suggested_add_agent_id",
    "auto_invited_dha_ids": "auto_invited_agent_ids",
    "resume_target_dha_id": "resume_target_agent_id",
    "pending_owner_dha_id": "pending_owner_agent_id",
    "owner_dha_id": "owner_agent_id",
    "last_speaker_dha_id": "last_speaker_agent_id",
    "target_dha_id": "target_agent_id",
    "joined_dha_ids": "joined_agent_ids",
    "dha_map": "agent_map",
}


def _convert_value(v: Any) -> Any:
    if isinstance(v, str):
        s = v.strip()
        if s.startswith("dha-"):
            return f"agent-{s[4:]}"
        return v
    if isinstance(v, list):
        return [_convert_value(x) for x in v]
    if isinstance(v, dict):
        out = {}
        for k, vv in v.items():
            nk = KEY_RENAMES.get(k, k)
            out[nk] = _convert_value(vv)
        return out
    return v


def _candidate_files(repo_root: Path) -> list[Path]:
    out: list[Path] = []
    out.extend((repo_root / "backend" / "data" / "sessions").glob("group_*.json"))
    out.extend((repo_root / "backend" / "config").glob("*.json"))
    users_root = repo_root / "backend" / "data" / "users"
    if users_root.exists():
        for user_dir in users_root.iterdir():
            if not user_dir.is_dir():
                continue
            out.extend((user_dir / "config").glob("*.json"))
            out.extend((user_dir / "sessions").glob("group_*.json"))
    # Only migrate files explicitly in the project plan scope.
    allow = (
        "dha_instances.json",
        "session_presets.json",
        "group_sessions_meta.json",
    )
    filtered: list[Path] = []
    for p in out:
        n = p.name
        if n in allow or n.startswith("group_history_group-"):
            filtered.append(p)
    # stable order
    return sorted(set(filtered), key=lambda p: str(p).lower())


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    files = _candidate_files(repo_root)
    if not files:
        print("No target files found.")
        return

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    changed = 0
    skipped = 0
    for p in files:
        try:
            raw = p.read_text(encoding="utf-8")
            data = json.loads(raw)
        except Exception:
            skipped += 1
            continue

        converted = _convert_value(data)
        new_raw = json.dumps(converted, ensure_ascii=False, indent=2)
        if new_raw == raw:
            continue

        backup = p.with_suffix(p.suffix + f".bak.{stamp}")
        backup.write_text(raw, encoding="utf-8")
        p.write_text(new_raw, encoding="utf-8")
        changed += 1
        print(f"migrated: {p}")

    print(f"done: changed={changed}, skipped={skipped}, scanned={len(files)}")


if __name__ == "__main__":
    main()

