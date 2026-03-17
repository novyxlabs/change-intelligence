from __future__ import annotations

import json
import os

from novyx import Novyx

from .novyx_store import NovyxConfig, NovyxStore


BOOTSTRAP_MEMORIES = [
    {
        "observation": "tools/entity_generator.py, tools/ingestor.py, tools/pii_validator.py, tools/query.py changed -> quickstart.md was flagged for review",
        "tags": ["change-pattern", "docs-impact", "source:change-intelligence-app"],
        "context": "novyxlabs/novyx-core#1",
        "importance": 10,
    },
    {
        "observation": "src/billing/createCheckoutSession.ts changed -> billing.md was flagged for review",
        "tags": ["change-pattern", "docs-impact", "source:change-intelligence-app"],
        "context": "novyxlabs/change-intelligence-demo#1",
        "importance": 10,
    },
    {
        "observation": "extensions/novyx_ram/routers/memories.py, extensions/novyx_ram/services/file_memory_store.py, packages/novyx-control/src/config.js, packages/novyx-control/src/connectors/http.js, packages/novyx-control/src/db.js, packages/novyx-control/src/server.js, packages/novyx-control/tests/action-service.test.js, packages/novyx-control/tests/server.test.js changed -> api-keys.md was accepted after merge",
        "tags": ["change-pattern", "merge-feedback", "accepted", "predicted", "source:change-intelligence-app"],
        "context": "novyxlabs/novyx-core#900002",
        "importance": 9,
    },
    {
        "observation": "packages/novyx-mcp/novyx_mcp/cloud_backend.py, packages/novyx-mcp/novyx_mcp/local_backend.py, packages/novyx-mcp/novyx_mcp/local_schema.py, packages/novyx-mcp/novyx_mcp/server.py, packages/novyx-mcp/pyproject.toml changed -> tools-reference.md was accepted after merge",
        "tags": ["change-pattern", "merge-feedback", "accepted", "predicted", "source:change-intelligence-app"],
        "context": "novyxlabs/novyx-core#900001",
        "importance": 9,
    },
    {
        "observation": "tools/entity_generator.py, tools/ingestor.py, tools/pii_validator.py, tools/query.py changed -> changelog.md was predicted for docs review",
        "tags": ["change-pattern", "docs-impact", "predicted", "source:change-intelligence-app"],
        "context": "novyxlabs/novyx-core#1",
        "importance": 9,
    },
    {
        "observation": "Feedback on novyxlabs/novyx-core#900001: wrong-doc",
        "tags": ["ci-feedback", "wrong-doc", "source:change-intelligence-app"],
        "context": "novyxlabs/novyx-core#900001",
        "importance": 8,
    },
    {
        "observation": "tools/entity_generator.py, tools/ingestor.py, tools/pii_validator.py, tools/query.py changed -> guides/memory-spaces.md was predicted for docs review",
        "tags": ["change-pattern", "docs-impact", "predicted", "source:change-intelligence-app"],
        "context": "novyxlabs/novyx-core#1",
        "importance": 4,
    },
]


def main() -> None:
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

    created = []
    for memory in BOOTSTRAP_MEMORIES:
        result = client.remember(
            memory["observation"],
            tags=memory["tags"],
            context=memory["context"],
            importance=memory["importance"],
            agent_id=os.environ.get("NOVYX_AGENT_ID", "change-intelligence"),
            space_id=store.space_id,
        )
        created.append(
            {
                "uuid": result.get("uuid"),
                "observation": memory["observation"],
            }
        )

    print(json.dumps({"space_id": store.space_id, "created": created}, indent=2))


if __name__ == "__main__":
    main()
