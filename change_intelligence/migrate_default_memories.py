from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Dict, List

from novyx import Novyx, NovyxError

from .novyx_store import NovyxConfig, NovyxStore


def should_migrate(memory: Dict[str, object]) -> bool:
    if memory.get("space_id") is not None:
        return False

    agent_id = memory.get("agent_id")
    if agent_id == "change-intelligence":
        return True

    tags = set(memory.get("tags") or [])
    if "source:change-intelligence-app" in tags:
        return True

    return False


def snapshot_record(memory: Dict[str, object]) -> Dict[str, object]:
    return {
        "uuid": memory["uuid"],
        "observation": memory["observation"],
        "tags": list(memory.get("tags") or []),
        "context": memory.get("context") or None,
        "importance": int(memory.get("importance") or 5),
        "agent_id": str(memory.get("agent_id") or "change-intelligence"),
    }


def migrate_memories(
    client: Novyx,
    store: NovyxStore,
    limit: int,
    delete_originals: bool,
    snapshot_path: str | None,
) -> Dict[str, object]:
    all_memories = client.memories(limit=limit)
    candidates = [memory for memory in all_memories if should_migrate(memory)]
    snapshots = [snapshot_record(memory) for memory in candidates]

    if snapshot_path:
        Path(snapshot_path).write_text(json.dumps(snapshots, indent=2), encoding="utf8")

    migrated: List[Dict[str, object]] = []
    skipped: List[Dict[str, object]] = []

    for memory in snapshots:
        try:
            if delete_originals:
                client.forget(str(memory["uuid"]))
            created = client.remember(
                memory["observation"],
                tags=list(memory.get("tags") or []),
                context=memory.get("context") or None,
                importance=int(memory.get("importance") or 5),
                agent_id=str(memory.get("agent_id") or "change-intelligence"),
                space_id=store.space_id,
            )
            migrated.append(
                {
                    "old_uuid": memory["uuid"],
                    "new_uuid": created.get("uuid"),
                    "observation": memory["observation"],
                }
            )
        except NovyxError as error:
            skipped.append(
                {
                    "uuid": memory.get("uuid"),
                    "observation": memory.get("observation"),
                    "error": str(error),
                }
            )

    return {
        "space_id": store.space_id,
        "candidate_count": len(candidates),
        "migrated_count": len(migrated),
        "deleted_originals": delete_originals,
        "migrated": migrated,
        "skipped": skipped,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Move default-space Change Intelligence memories into the dedicated space.")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--delete-originals", action="store_true")
    parser.add_argument("--snapshot-path")
    args = parser.parse_args()

    client = Novyx(
        api_key=os.environ["NOVYX_API_KEY"],
        api_url=os.environ.get("NOVYX_API_URL") or "https://novyx-ram-api.fly.dev",
        agent_id=os.environ.get("NOVYX_AGENT_ID", "change-intelligence"),
        source="change-intelligence-app",
    )
    store = NovyxStore(
        NovyxConfig(
            api_key=os.environ["NOVYX_API_KEY"],
            api_url=os.environ.get("NOVYX_API_URL"),
            agent_id=os.environ.get("NOVYX_AGENT_ID", "change-intelligence"),
        ),
        client=client,
    )

    result = migrate_memories(client, store, args.limit, args.delete_originals, args.snapshot_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
