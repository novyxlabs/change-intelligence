from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .analysis import analyze_patch
from .github_client import GitHubClient, build_patch_from_files
from novyx import NovyxError

from .novyx_store import NovyxConfig, NovyxStore
from .service import ServiceConfig, process_github_event, split_repository


def build_store() -> NovyxStore:
    return NovyxStore(
        NovyxConfig(
            api_key=os.environ["NOVYX_API_KEY"],
            api_url=os.environ.get("NOVYX_API_URL"),
            agent_id=os.environ.get("NOVYX_AGENT_ID", "change-intelligence"),
        )
    )


def build_service_config(github_client: GitHubClient, store: NovyxStore) -> ServiceConfig:
    return ServiceConfig(
        docs_root=Path(os.environ.get("DOCS_ROOT", "docs")).resolve(),
        docs_repo=os.environ.get("DOCS_REPO"),
        docs_path=os.environ.get("DOCS_PATH", "docs"),
        novyx_store=store,
        github_client=github_client,
        confidence_threshold=int(os.environ.get("CONFIDENCE_THRESHOLD", "60")),
    )


def replay_recent_prs(
    github_client: GitHubClient,
    store: NovyxStore,
    repository: str,
    limit: int,
) -> List[Dict[str, object]]:
    if limit <= 0:
        return []
    owner, repo = split_repository(repository)
    config = build_service_config(github_client, store)
    results: List[Dict[str, object]] = []

    for pull in github_client.pull_requests(owner, repo, per_page=limit):
        if not pull.get("merged_at"):
            continue
        payload = {
            "action": "closed",
            "repository": {"full_name": repository},
            "pull_request": {
                "number": pull["number"],
                "merged_at": pull["merged_at"],
                "head": {"sha": ((pull.get("head") or {}).get("sha"))},
            },
        }
        result = process_github_event(json.dumps(payload), None, config)
        recommendations = (result.get("payload") or {}).get("recommendations") or []
        top = recommendations[0] if recommendations else {}
        results.append(
            {
                "number": pull["number"],
                "title": pull.get("title"),
                "merged_at": pull.get("merged_at"),
                "top_doc": top.get("relative_path"),
                "top_confidence": top.get("confidence"),
                "comment_suppressed": (result.get("payload") or {}).get("comment_suppressed"),
                "status_code": result.get("status_code"),
            }
        )

    return results


def top_feedback_command(recommendations: Sequence[Dict[str, object]], actual_docs: Sequence[str]) -> Optional[str]:
    actual = {Path(path).name for path in actual_docs}
    if not recommendations:
        return "/ci missed-doc" if actual else None
    if recommendations[0]["relative_path"] in actual:
        return "/ci correct"
    return "/ci wrong-doc" if actual else None


def seed_examples(
    github_client: GitHubClient,
    store: NovyxStore,
    seed_path: Path,
) -> List[Dict[str, object]]:
    seeds = json.loads(seed_path.read_text(encoding="utf8"))
    results: List[Dict[str, object]] = []

    for index, seed in enumerate(seeds, start=1):
        repository = seed["repository"]
        owner, repo = split_repository(repository)
        docs_repo = seed.get("docs_repo") or os.environ.get("DOCS_REPO")
        docs_path = seed.get("docs_path") or os.environ.get("DOCS_PATH", "docs")
        commit_sha = seed["commit"]
        actual_docs = list(seed.get("actual_docs") or [])

        if not docs_repo:
            raise ValueError("docs_repo is required for seed examples.")

        files = github_client.commit_files(owner, repo, commit_sha, None)
        patch = build_patch_from_files(files)
        docs_owner, docs_repo_name = split_repository(str(docs_repo))
        docs = github_client.repo_docs(docs_owner, docs_repo_name, str(docs_path), None, None)
        changed_files = [str(item["filename"]) for item in files if item.get("filename")]
        query = f"{repository} changed files: {', '.join(changed_files[:3])}"
        analysis = analyze_patch(
            patch,
            docs_root=Path(str(docs_path)).resolve(),
            docs=docs,
            learned_signals=store.rank_signals(repository, changed_files),
            patterns=store.recall_patterns(query),
            actual_docs_changed={Path(path).name for path in actual_docs} if actual_docs else None,
        )

        synthetic_pr = int(seed.get("synthetic_pull_request_number") or (900000 + index))
        try:
            learning_feedback = store.seed_accepted_docs(
                repository,
                synthetic_pr,
                analysis["summary"]["changed_files"],
                actual_docs,
            )
        except NovyxError as error:
            learning_feedback = {"error": str(error)}

        command = top_feedback_command(analysis["recommendations"], actual_docs)
        if command:
            try:
                store.record_feedback(
                    repository=repository,
                    pull_request_number=synthetic_pr,
                    command=command,
                    commenter="change-intelligence-backfill",
                    comment_url=f"https://github.com/{repository}/commit/{commit_sha}",
                )
            except NovyxError:
                pass

        top = analysis["recommendations"][0] if analysis["recommendations"] else {}
        results.append(
            {
                "commit": commit_sha,
                "repository": repository,
                "top_doc": top.get("relative_path"),
                "top_confidence": top.get("confidence"),
                "actual_docs": actual_docs,
                "learning_feedback": learning_feedback,
                "feedback_command": command,
            }
        )

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay historical PRs and seed curated training examples.")
    parser.add_argument("--repository", default="novyxlabs/novyx-core")
    parser.add_argument("--replay-limit", type=int, default=10)
    parser.add_argument("--seed-path")
    parser.add_argument("--output-path")
    args = parser.parse_args()

    github_client = GitHubClient.from_env()
    if github_client is None:
        raise SystemExit("GITHUB_TOKEN or GitHub App credentials are required.")

    store = build_store()
    payload = {
        "repository": args.repository,
        "replayed_prs": replay_recent_prs(github_client, store, args.repository, args.replay_limit),
        "seeded_examples": seed_examples(github_client, store, Path(args.seed_path)) if args.seed_path else [],
    }
    rendered = json.dumps(payload, indent=2)
    if args.output_path:
        Path(args.output_path).write_text(rendered, encoding="utf8")
    print(rendered)


if __name__ == "__main__":
    main()
