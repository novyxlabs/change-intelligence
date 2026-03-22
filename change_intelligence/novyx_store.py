from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
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
        self.client = client or Novyx(
            api_key=config.api_key,
            api_url=config.api_url or "https://novyx-ram-api.fly.dev",
            agent_id=config.agent_id,
            source=config.source,
        )
        self._space_id: Optional[str] = None

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
                },
            )
            tags = set(memory.get("tags") or [])
            if "accepted" in tags:
                bucket["accepted_hits"] += 1
            if "rejected" in tags:
                bucket["rejected_hits"] += 1

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
        comment_suppressed: bool = False,
        head_sha: Optional[str] = None,
        action: Optional[str] = None,
        patterns: Optional[Sequence[Dict[str, object]]] = None,
        learned_signals: Optional[Dict[str, Dict[str, object]]] = None,
        learning_feedback: Optional[Dict[str, Sequence[str]]] = None,
        release_notes: Optional[Dict[str, object]] = None,
        summary: Optional[Dict[str, object]] = None,
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

        run_memory = self._remember_run_outcome(
            repository,
            pull_request_number,
            changed_files,
            recommendations,
            comment_suppressed=comment_suppressed,
            head_sha=head_sha,
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
    ) -> Dict[str, object]:
        label = command.replace("/ci ", "").strip()
        latest = self.latest_analysis_for_pr(repository, pull_request_number)

        try:
            memory = self._remember(
                f"Feedback on {repository}#{pull_request_number}: {label}",
                importance=8,
                tags=["ci-feedback", label],
                context=f"{repository}#{pull_request_number}",
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
            else:
                raise

        graph_update = self._apply_feedback_graph_edges(
            repository,
            pull_request_number,
            label,
            latest,
        )
        audit = self._audit_snapshot(self._artifact_id(memory), limit=6)
        return {
            "status": "recorded",
            "feedback": label,
            "memory": memory,
            "graph_update": graph_update,
            "audit_entries": audit,
        }

    def _remember_run_outcome(
        self,
        repository: str,
        pull_request_number: int,
        changed_files: Sequence[str],
        recommendations: Sequence[Dict[str, object]],
        *,
        comment_suppressed: bool,
        head_sha: Optional[str],
    ) -> Dict[str, object]:
        top = recommendations[0] if recommendations else {}
        sha_label = f"@{head_sha[:12]}" if head_sha else ""
        try:
            return self._remember(
                f"Analysis run for {repository}#{pull_request_number}{sha_label}: {'suppressed' if comment_suppressed else 'commented'}",
                importance=5,
                tags=["analysis-run", "suppressed" if comment_suppressed else "commented"],
                context=f"{repository}#{pull_request_number}",
                metadata={
                    "repository": repository,
                    "pull_request_number": pull_request_number,
                    "comment_suppressed": comment_suppressed,
                    "head_sha": head_sha,
                    "changed_files": list(changed_files),
                    "top_doc": top.get("relative_path"),
                    "top_confidence": top.get("confidence"),
                    "recommendation_count": len(recommendations),
                },
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
            if "409" not in str(error):
                raise

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
