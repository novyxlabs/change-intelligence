from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import inspect
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from novyx import Novyx, NovyxError


@dataclass
class NovyxConfig:
    api_key: str
    agent_id: str = "change-intelligence"
    api_url: Optional[str] = None
    source: str = "change-intelligence-app"
    space_name: str = "change-intelligence"
    space_description: str = "Learning data for Change Intelligence — doc mappings, seeds, replay results"


class NovyxStore:
    def __init__(self, config: NovyxConfig, client: Optional[Novyx] = None):
        self.config = config
        self.client = client or self._build_client(config)
        self._space_id: Optional[str] = None

    def _build_client(self, config: NovyxConfig) -> Novyx:
        kwargs = {
            "api_key": config.api_key,
            "api_url": config.api_url or "https://novyx-ram-api.fly.dev",
            "agent_id": config.agent_id,
        }
        parameters = inspect.signature(Novyx).parameters
        if "source" in parameters:
            kwargs["source"] = config.source
        return Novyx(**kwargs)

    def recall_patterns(self, query: str, limit: int = 5) -> List[Dict[str, object]]:
        results = self.client.recall(
            query,
            limit=limit,
            tags=["change-pattern"],
            space_id=self.space_id,
        )
        return [
            {
                "id": memory.id,
                "observation": memory.observation,
                "score": memory.score,
                "tags": memory.tags,
                "metadata": getattr(memory, "metadata", None),
            }
            for memory in results
        ]

    def list_memories(self, tags: Sequence[str], limit: int = 200) -> List[Dict[str, object]]:
        try:
            return self.client.memories(limit=limit, tags=list(tags), space_id=self.space_id)
        except NovyxError:
            return []

    @property
    def space_id(self) -> str:
        if self._space_id is None:
            self._space_id = self._ensure_space_id()
        return self._space_id

    def rank_signals(self, repository: str, changed_files: Sequence[str]) -> Dict[str, Dict[str, object]]:
        signals: Dict[str, Dict[str, object]] = {}

        for path in changed_files:
            self._accumulate_triples(signals, path, "documents", "graph_hits")
            self._accumulate_triples(signals, path, "avoids_documenting", "rejected_hits")

        pattern_query = f"{repository} changed files: {', '.join(changed_files[:3])}"
        for memory in self.recall_patterns(pattern_query, limit=10):
            metadata = {}
            raw = memory.get("metadata")
            if isinstance(raw, dict):
                metadata = raw
            doc = metadata.get("relative_path")
            if not doc:
                continue
            bucket = signals.setdefault(
                str(doc),
                {
                    "graph_hits": 0,
                    "accepted_hits": 0,
                    "rejected_hits": 0,
                    "missed_hits": 0,
                    "exact_file_hits": 0,
                    "exact_rejected_file_hits": 0,
                },
            )
            tags = set(memory.get("tags") or [])
            if "accepted" in tags:
                bucket["accepted_hits"] += 1
            if "rejected" in tags:
                bucket["rejected_hits"] += 1
            if "missed" in tags:
                bucket["missed_hits"] += 1
            observation = str(memory.get("observation") or "")
            if any(path in observation for path in changed_files):
                if "rejected" in tags:
                    bucket["exact_rejected_file_hits"] += 1
                elif "accepted" in tags or "missed" in tags:
                    bucket["exact_file_hits"] += 1

        return signals

    def _accumulate_triples(
        self,
        signals: Dict[str, Dict[str, object]],
        subject: str,
        predicate: str,
        key: str,
    ) -> None:
        try:
            triples = self.client.triples(subject=subject, predicate=predicate, limit=50)
        except NovyxError:
            return

        for item in self._triple_items(triples):
            doc = self._doc_name_from_triple(item)
            if not doc:
                continue
            bucket = signals.setdefault(
                str(doc),
                {
                    "graph_hits": 0,
                    "accepted_hits": 0,
                    "rejected_hits": 0,
                    "missed_hits": 0,
                    "exact_file_hits": 0,
                    "exact_rejected_file_hits": 0,
                },
            )
            bucket[key] += 1

    def _doc_name_from_triple(self, item: Dict[str, object]) -> Optional[str]:
        doc = item.get("object_name")
        if isinstance(doc, str):
            return doc

        obj = item.get("object")
        if isinstance(obj, str):
            return obj
        if isinstance(obj, dict):
            name = obj.get("name")
            if isinstance(name, str):
                return name
        return None

    def _ensure_space_id(self) -> str:
        try:
            spaces = self.client.list_spaces()
        except NovyxError:
            spaces = {}

        for item in self._space_items(spaces):
            name = item.get("name")
            if isinstance(name, str) and name == self.config.space_name:
                space_id = item.get("space_id") or item.get("id")
                if isinstance(space_id, str):
                    return space_id

        created = self.client.create_space(
            name=self.config.space_name,
            description=self.config.space_description,
        )
        space_id = created.get("space_id") or created.get("id")
        if not isinstance(space_id, str):
            raise ValueError("Novyx space creation did not return a usable space_id.")
        return space_id

    def _space_items(self, spaces: Dict[str, object]) -> List[Dict[str, object]]:
        if isinstance(spaces, dict):
            for key in ("spaces", "items", "results"):
                if isinstance(spaces.get(key), list):
                    return [item for item in spaces[key] if isinstance(item, dict)]
        return []

    def record_analysis(
        self,
        repository: str,
        pull_request_number: int,
        changed_files: Sequence[str],
        recommendations: Sequence[Dict[str, object]],
        *,
        confidence_tier: str = "silent",
        comment_suppressed: bool = False,
        head_sha: Optional[str] = None,
        docs_repo: Optional[str] = None,
        docs_path: Optional[str] = None,
        action: Optional[str] = None,
        patterns: Optional[Sequence[Dict[str, object]]] = None,
        learned_signals: Optional[Dict[str, Dict[str, object]]] = None,
        learning_feedback: Optional[Dict[str, Sequence[str]]] = None,
        release_notes: Optional[Dict[str, object]] = None,
        support_updates: Optional[Dict[str, object]] = None,
        onboarding_updates: Optional[Dict[str, object]] = None,
        summary: Optional[Dict[str, object]] = None,
        side_effects: Optional[Dict[str, Dict[str, object]]] = None,
    ) -> Dict[str, object]:
        trace = self.client.trace_create(
            self.config.agent_id,
            metadata={
                "repository": repository,
                "pull_request_number": pull_request_number,
                "action": action,
                "head_sha": head_sha,
            },
        )
        trace_id = trace.get("trace_id")

        self.client.trace_step(
            trace_id,
            "observation",
            f"Analyzed files: {', '.join(changed_files) or 'none'}",
            metadata={"count": len(changed_files)},
        )
        self.client.trace_step(
            trace_id,
            "observation",
            f"Patterns recalled: {len(patterns or [])}; learned graph signals: {len(learned_signals or {})}",
            metadata={
                "patterns": len(patterns or []),
                "learned_signal_docs": len(learned_signals or {}),
            },
        )
        if summary:
            self.client.trace_step(
                trace_id,
                "observation",
                f"Changed symbols: {', '.join((summary.get('changed_symbols') or [])[:5]) or 'none'}",
                metadata={
                    "changed_files": len(summary.get("changed_files") or []),
                    "changed_symbols": len(summary.get("changed_symbols") or []),
                    "changed_surfaces": len(summary.get("changed_surfaces") or []),
                },
            )

        for recommendation in recommendations:
            for path in changed_files:
                self._safe_triple(
                    path,
                    "predicted_documents",
                    recommendation["relative_path"],
                    metadata={
                        "pull_request_number": pull_request_number,
                        "confidence": recommendation["confidence"],
                    },
                )
            self._remember_prediction(repository, pull_request_number, changed_files, recommendation)

        if learning_feedback:
            self.client.trace_step(
                trace_id,
                "observation",
                "Learning feedback applied after merge replay.",
                metadata={
                    "accepted": len(learning_feedback.get("accepted") or []),
                    "rejected": len(learning_feedback.get("rejected") or []),
                    "missed": len(learning_feedback.get("missed") or []),
                },
            )

        if release_notes:
            self.client.trace_step(
                trace_id,
                "action",
                f"Release-note draft {'included' if release_notes.get('included_in_report') else 'suppressed'}.",
                metadata={
                    "included_in_report": bool(release_notes.get("included_in_report")),
                    "confidence": release_notes.get("confidence"),
                    "affected_surfaces": len(release_notes.get("affected_surfaces") or []),
                },
            )
        if support_updates:
            self.client.trace_step(
                trace_id,
                "action",
                f"Support update draft {'included' if support_updates.get('included_in_report') else 'suppressed'}.",
                metadata={
                    "included_in_report": bool(support_updates.get("included_in_report")),
                    "confidence": support_updates.get("confidence"),
                    "recommended_docs": len(support_updates.get("recommended_docs") or []),
                },
            )
        if onboarding_updates:
            self.client.trace_step(
                trace_id,
                "action",
                f"Onboarding update draft {'included' if onboarding_updates.get('included_in_report') else 'suppressed'}.",
                metadata={
                    "included_in_report": bool(onboarding_updates.get("included_in_report")),
                    "confidence": onboarding_updates.get("confidence"),
                    "recommended_docs": len(onboarding_updates.get("recommended_docs") or []),
                },
            )

        run_memory = self._remember_run_outcome(
            repository,
            pull_request_number,
            changed_files,
            recommendations,
            confidence_tier=confidence_tier,
            comment_suppressed=comment_suppressed,
            head_sha=head_sha,
            docs_repo=docs_repo,
            docs_path=docs_path,
            side_effects=side_effects,
        )

        evaluation = self._evaluation_snapshot()
        if evaluation:
            self.client.trace_step(
                trace_id,
                "observation",
                "Novyx eval snapshot recorded for this run.",
                metadata=evaluation,
            )

        audit = self._audit_snapshot(self._artifact_id(run_memory), limit=8)
        if audit:
            self.client.trace_step(
                trace_id,
                "observation",
                f"Captured {len(audit)} audit entries for the analysis artifact.",
                metadata={"audit_entries": len(audit)},
            )

        finalized = self._finalize_trace(trace_id, recommendations)
        finalized["evaluation"] = evaluation
        finalized["audit_entries"] = audit
        finalized["analysis_memory_id"] = self._artifact_id(run_memory)
        return finalized

    def record_feedback(
        self,
        repository: str,
        pull_request_number: int,
        command: str,
        commenter: str,
        comment_url: str,
        conflict_strategy: Optional[str] = None,
    ) -> Dict[str, object]:
        label = command.replace("/ci ", "").strip()
        latest = self.latest_analysis_for_pr(repository, pull_request_number)
        rate_limited = False

        try:
            memory = self._remember(
                f"Feedback on {repository}#{pull_request_number}: {label}",
                importance=8,
                tags=["ci-feedback", label],
                context=f"{repository}#{pull_request_number}",
                conflict_strategy=conflict_strategy,
                metadata={
                    "repository": repository,
                    "pull_request_number": pull_request_number,
                    "feedback": label,
                    "commenter": commenter,
                    "comment_url": comment_url,
                    "analysis_memory_id": self._artifact_id(latest),
                },
            )
        except NovyxError as error:
            if "409" in str(error):
                memory = {}
            elif self._is_rate_limited_error(error):
                memory = {}
                rate_limited = True
            else:
                raise

        try:
            graph_update = self._apply_feedback_graph_edges(
                repository,
                pull_request_number,
                label,
                latest,
            )
        except NovyxError as error:
            if self._is_rate_limited_error(error):
                graph_update = {"updated": False, "reason": "write-rate-limited"}
                rate_limited = True
            else:
                raise
        audit = self._audit_snapshot(self._artifact_id(memory), limit=6)
        return {
            "status": "deferred" if rate_limited else "recorded",
            "feedback": label,
            "memory": memory,
            "graph_update": graph_update,
            "audit_entries": audit,
            "rate_limited": rate_limited,
        }

    def _remember_run_outcome(
        self,
        repository: str,
        pull_request_number: int,
        changed_files: Sequence[str],
        recommendations: Sequence[Dict[str, object]],
        *,
        confidence_tier: str,
        comment_suppressed: bool,
        head_sha: Optional[str],
        docs_repo: Optional[str],
        docs_path: Optional[str],
        side_effects: Optional[Dict[str, Dict[str, object]]] = None,
    ) -> Dict[str, object]:
        top = recommendations[0] if recommendations else {}
        sha_label = f"@{head_sha[:12]}" if head_sha else ""
        comment_effect = (side_effects or {}).get("github_comment") or {}
        novyx_effect = (side_effects or {}).get("novyx_record") or {}
        try:
            return self._remember(
                f"Analysis run for {repository}#{pull_request_number}{sha_label}: {confidence_tier}",
                importance=6 if confidence_tier == "high-confidence" else 5,
                tags=[
                    "analysis-run",
                    confidence_tier,
                    "suppressed" if comment_suppressed else "commented",
                    *(
                        ["github-comment-failed"]
                        if comment_effect.get("status") == "failed"
                        else []
                    ),
                    *(
                        ["novyx-record-failed"]
                        if novyx_effect.get("status") == "failed"
                        else []
                    ),
                ],
                context=f"{repository}#{pull_request_number}",
                metadata={
                    "repository": repository,
                    "docs_repo": docs_repo,
                    "docs_path": docs_path,
                    "pull_request_number": pull_request_number,
                    "confidence_tier": confidence_tier,
                    "comment_suppressed": comment_suppressed,
                    "head_sha": head_sha,
                    "changed_files": list(changed_files),
                    "top_doc": top.get("relative_path"),
                    "top_confidence": top.get("confidence"),
                    "recommendation_count": len(recommendations),
                    "github_comment_status": comment_effect.get("status"),
                    "github_comment_error": comment_effect.get("error"),
                    "novyx_record_status": novyx_effect.get("status"),
                    "novyx_record_error": novyx_effect.get("error"),
                },
            )
        except NovyxError as error:
            if "409" not in str(error):
                raise
        return {}

    def record_historical_analysis(
        self,
        repository: str,
        pull_request_number: int,
        *,
        changed_files: Sequence[str],
        top_doc: Optional[str],
        top_confidence: Optional[int],
        confidence_tier: str,
        comment_url: str,
        comment_created_at: Optional[str] = None,
        restore_metadata: bool = False,
        original_observation: Optional[str] = None,
    ) -> Dict[str, object]:
        tags = [
            "analysis-run",
            confidence_tier or "review-recommended",
            "commented",
            "historical-import",
            *(["metadata-restored"] if restore_metadata else []),
        ]
        parts = [
            (
                f"Historical analysis metadata restored for {repository}#{pull_request_number}"
                if restore_metadata
                else f"Historical analysis run imported for {repository}#{pull_request_number}"
            ),
            f"from {comment_url}",
            f"tier {confidence_tier or 'review-recommended'}",
        ]
        if top_doc:
            parts.append(f"top doc {top_doc}")
        if top_confidence is not None:
            parts.append(f"confidence {top_confidence}")
        if changed_files:
            parts.append(f"changed files {', '.join(changed_files[:5])}")
        if comment_created_at:
            parts.append(f"commented at {comment_created_at}")
        metadata: Dict[str, object] = {
            "repository": repository,
            "pull_request_number": pull_request_number,
            "confidence_tier": confidence_tier or "review-recommended",
            "comment_suppressed": False,
            "changed_files": list(changed_files),
            "top_doc": top_doc,
            "top_confidence": top_confidence,
            "recommendation_count": 1 if top_doc else 0,
            "github_comment_status": "commented",
            "github_comment_url": comment_url,
            "novyx_record_status": "historical-import",
            "source": "github-comment-backfill",
            "metadata_restored": restore_metadata,
        }
        if comment_created_at:
            metadata["github_comment_created_at"] = comment_created_at
        observation = original_observation or " | ".join(parts)
        try:
            return self._remember(
                observation,
                importance=5,
                tags=tags,
                context=f"{repository}#{pull_request_number}",
                conflict_strategy="lww",
                metadata=metadata,
            )
        except NovyxError as error:
            if "409" not in str(error):
                raise
        return {}

    def latest_analysis_for_pr(self, repository: str, pull_request_number: int) -> Optional[Dict[str, object]]:
        target_context = f"{repository}#{pull_request_number}"
        runs = [
            item
            for item in self.list_memories(["analysis-run"], limit=500)
            if item.get("context") == target_context
        ]
        if not runs:
            return None
        runs.sort(key=self._memory_sort_key, reverse=True)
        return runs[0]

    def evaluation_history(self, limit: int = 10) -> Dict[str, object]:
        return self.client.eval_history(limit=limit)

    def evaluation_drift(self, days: int = 7) -> Dict[str, object]:
        return self.client.eval_drift(days=days)

    def feedback_audit(self, limit: int = 50) -> List[Dict[str, object]]:
        return self.client.audit(limit=limit)

    def learn_from_merge(
        self,
        repository: str,
        pull_request_number: int,
        changed_files: Sequence[str],
        predicted_docs: Sequence[str],
        actual_docs: Sequence[str],
    ) -> Dict[str, object]:
        actual = {Path(path).name for path in actual_docs}
        predicted = {Path(path).name for path in predicted_docs}

        accepted = sorted(actual & predicted)
        rejected = sorted(predicted - actual)
        missed = sorted(actual - predicted)

        for doc in accepted:
            self._reinforce(repository, pull_request_number, changed_files, doc, accepted=True)
        for doc in rejected:
            self._reinforce(repository, pull_request_number, changed_files, doc, accepted=False)
        for doc in missed:
            self._remember_feedback(
                repository,
                pull_request_number,
                changed_files,
                doc,
                accepted=True,
                predicted=False,
            )
            for path in changed_files:
                self._safe_triple(
                    path,
                    "documents",
                    doc,
                    metadata={
                        "pull_request_number": pull_request_number,
                        "feedback": "missed",
                    },
                )

        return {
            "accepted": accepted,
            "rejected": rejected,
            "missed": missed,
        }

    def seed_accepted_docs(
        self,
        repository: str,
        pull_request_number: int,
        changed_files: Sequence[str],
        actual_docs: Sequence[str],
    ) -> Dict[str, object]:
        accepted = sorted({Path(path).name for path in actual_docs})
        for doc in accepted:
            self._reinforce(repository, pull_request_number, changed_files, doc, accepted=True)
        return {
            "accepted": accepted,
            "rejected": [],
            "missed": [],
        }

    def _reinforce(
        self,
        repository: str,
        pull_request_number: int,
        changed_files: Sequence[str],
        doc: str,
        accepted: bool,
    ) -> None:
        predicate = "documents" if accepted else "avoids_documenting"
        for path in changed_files:
            self._safe_triple(
                path,
                predicate,
                doc,
                metadata={
                    "pull_request_number": pull_request_number,
                    "feedback": "accepted" if accepted else "rejected",
                },
            )
        self._remember_feedback(
            repository,
            pull_request_number,
            changed_files,
            doc,
            accepted=accepted,
            predicted=True,
        )

    def _remember_prediction(
        self,
        repository: str,
        pull_request_number: int,
        changed_files: Sequence[str],
        recommendation: Dict[str, object],
    ) -> None:
        try:
            self._remember(
                f"{', '.join(changed_files)} changed -> {recommendation['relative_path']} was predicted for docs review",
                importance=max(4, min(10, int(recommendation["confidence"] / 10))),
                tags=["change-pattern", "docs-impact", "predicted"],
                context=f"{repository}#{pull_request_number}",
                metadata={
                    "repository": repository,
                    "pull_request_number": pull_request_number,
                    "relative_path": recommendation["relative_path"],
                    "confidence": recommendation["confidence"],
                    "score": recommendation["score"],
                    "evidence": recommendation["evidence"],
                },
            )
        except NovyxError as error:
            if "409" not in str(error):
                raise

    def _remember_feedback(
        self,
        repository: str,
        pull_request_number: int,
        changed_files: Sequence[str],
        doc: str,
        accepted: bool,
        predicted: bool,
    ) -> None:
        label = "accepted" if accepted else "rejected"
        sentence = (
            f"{', '.join(changed_files)} changed -> {doc} was {label} after merge"
            if predicted
            else f"{', '.join(changed_files)} changed -> {doc} should have been documented after merge"
        )
        try:
            self._remember(
                sentence,
                importance=9 if accepted else 2,
                tags=[
                    "change-pattern",
                    "merge-feedback",
                    label,
                    "predicted" if predicted else "missed",
                ],
                context=f"{repository}#{pull_request_number}",
                metadata={
                    "repository": repository,
                    "pull_request_number": pull_request_number,
                    "relative_path": doc,
                    "accepted": accepted,
                    "predicted": predicted,
                },
            )
        except NovyxError as error:
            if "409" not in str(error):
                raise

    def _remember(self, observation: str, **kwargs: object) -> Dict[str, object]:
        return self.client.remember(
            observation,
            space_id=self.space_id,
            **kwargs,
        )

    def _artifact_id(self, payload: Optional[Dict[str, object]]) -> Optional[str]:
        if not isinstance(payload, dict):
            return None
        for key in ("id", "memory_id", "artifact_id", "uuid"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    def _audit_snapshot(self, artifact_id: Optional[str], limit: int = 10) -> List[Dict[str, object]]:
        if not artifact_id:
            return []
        try:
            return self.client.audit(limit=limit, artifact_id=artifact_id)
        except NovyxError:
            return []

    def _evaluation_snapshot(self) -> Dict[str, object]:
        try:
            run = self.client.eval_run()
        except NovyxError:
            return {}
        try:
            drift = self.client.eval_drift(days=7)
        except NovyxError:
            drift = {}
        return {
            "health_score": run.get("health_score") or run.get("score"),
            "drift_score": drift.get("drift_score") or drift.get("score"),
            "drift_days": 7,
        }

    def _apply_feedback_graph_edges(
        self,
        repository: str,
        pull_request_number: int,
        label: str,
        latest_analysis: Optional[Dict[str, object]],
    ) -> Dict[str, object]:
        if not latest_analysis:
            return {"updated": False, "reason": "no-analysis-run"}

        metadata = latest_analysis.get("metadata")
        if not isinstance(metadata, dict):
            return {"updated": False, "reason": "missing-analysis-metadata"}

        top_doc = metadata.get("top_doc")
        if not isinstance(top_doc, str) or not top_doc:
            return {"updated": False, "reason": "no-top-doc"}

        changed_files = metadata.get("changed_files")
        if not isinstance(changed_files, list) or not changed_files:
            return {"updated": False, "reason": "no-changed-files"}

        if label == "correct":
            predicate = "documents"
            doc_targets = [top_doc]
        elif label == "wrong-doc":
            predicate = "avoids_documenting"
            doc_targets = [top_doc]
        elif label == "missed-doc":
            predicate = "documents"
            doc_targets = self._docs_from_feedback_context(repository, pull_request_number)
            if not doc_targets:
                return {"updated": False, "reason": "feedback-has-no-doc-target"}
        else:
            return {"updated": False, "reason": "feedback-has-no-doc-target"}

        for path in changed_files:
            if not isinstance(path, str) or not path:
                continue
            for doc in doc_targets:
                self._safe_triple(
                    path,
                    predicate,
                    doc,
                    metadata={
                        "repository": repository,
                        "pull_request_number": pull_request_number,
                        "feedback": label,
                        "source": "reviewer-feedback",
                        "recorded_at": datetime.now(timezone.utc).isoformat(),
                    },
                )

        return {
            "updated": True,
            "predicate": predicate,
            "doc": doc_targets[0],
            "docs": doc_targets,
            "changed_file_count": len(changed_files),
        }

    def _docs_from_feedback_context(self, repository: str, pull_request_number: int) -> List[str]:
        target_context = f"{repository}#{pull_request_number}"
        docs = []
        for item in self.list_memories(["ci-feedback"], limit=500):
            if item.get("context") != target_context:
                continue
            tags = set(item.get("tags") or [])
            if "missed-doc" not in tags:
                continue
            metadata = item.get("metadata")
            if not isinstance(metadata, dict):
                continue
            doc = metadata.get("doc") or metadata.get("relative_path")
            if isinstance(doc, str) and doc:
                docs.append(doc)
        return list(dict.fromkeys(docs))

    def _safe_triple(self, subject: str, predicate: str, object_name: str, metadata: Dict[str, object]) -> None:
        try:
            self.client.triple(subject, predicate, object_name, metadata=metadata)
        except NovyxError as error:
            if "409" not in str(error) and not self._is_rate_limited_error(error):
                raise

    def _is_rate_limited_error(self, error: Exception) -> bool:
        message = str(error).lower()
        return "write_rate_limit" in message or "rate limit" in message

    def _triple_items(self, triples: Dict[str, object]) -> List[Dict[str, object]]:
        if isinstance(triples, dict):
            for key in ("triples", "items", "results"):
                if isinstance(triples.get(key), list):
                    return [item for item in triples[key] if isinstance(item, dict)]
        return []

    def _memory_sort_key(self, item: Dict[str, object]) -> str:
        for key in ("created_at", "timestamp", "updated_at"):
            value = item.get(key)
            if isinstance(value, str):
                return value
        return ""

    def _finalize_trace(self, trace_id: str, recommendations: Sequence[Dict[str, object]]) -> Dict[str, object]:
        self.client.trace_step(
            trace_id,
            "action",
            f"Recommended docs: {', '.join(item['relative_path'] for item in recommendations) or 'none'}",
            metadata={"count": len(recommendations)},
        )
        self.client.trace_complete(trace_id)
        return {"trace_id": trace_id}
