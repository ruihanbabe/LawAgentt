"""最终交付的统一确定性门禁。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from safety.pii import PIIPolicy, PIIReviewer
from runtime.final_response import FinalResponseContent, safe_error_content
from safety.law_validity import is_law_effective_on
from runtime.taskboard import AgentRunBoard, Artifact, ArtifactType


class DeliveryDecision(StrEnum):
    DELIVER = "deliver"
    BLOCK = "block"


class DeliveryCheck(StrEnum):
    FINAL_PRESENT = "final_present"
    PROVENANCE_VALID = "provenance_valid"
    REVIEW_APPROVED = "review_approved"
    RESPONSE_PRESENT = "response_present"
    DECISION_VALID = "decision_valid"
    CLAIMS_GROUNDED = "claims_grounded"
    EVIDENCE_EXISTS = "evidence_exists"
    TEMPORAL_VALIDITY = "temporal_validity"
    PII_CLEAR = "pii_clear"
    NO_PROHIBITED_PROMISE = "no_prohibited_promise"
    NO_INTERNAL_IDENTIFIER = "no_internal_identifier"
    RESPONSE_STRUCTURE = "response_structure"


@dataclass(frozen=True, slots=True)
class DeliveryGateResult:
    decision: DeliveryDecision
    final_artifact_id: str | None
    passed_checks: tuple[DeliveryCheck, ...]
    failure_codes: tuple[str, ...]

    @property
    def approved(self) -> bool:
        return self.decision == DeliveryDecision.DELIVER


class DeliveryGate:
    """只接受具有 Candidate→Review→Final provenance 的安全交付。"""

    SAFE_ERROR_TEXT = "当前无法安全生成回复，请稍后重试或补充信息。"
    _allowed_decisions = {
        "clarification_needed",
        "intent_confirmation_needed",
        "supported_answer",
        "limited_answer",
        "constructive_abstention",
        "safe_error",
    }
    _prohibited_promises = (
        "保证胜诉",
        "一定胜诉",
        "包赢",
        "百分之百",
        "肯定能追回",
        "一定可以追回",
    )
    _internal_markers = (
        "run_",
        "task_",
        "artifact_",
        "modelreq_",
        "<context_json>",
        "system prompt",
    )

    def __init__(self, *, reviewer: PIIReviewer | None = None) -> None:
        self.reviewer = reviewer or PIIReviewer()

    def evaluate(self, board: AgentRunBoard) -> DeliveryGateResult:
        failures: list[str] = []
        passed: list[DeliveryCheck] = []
        finals = [item for item in board.artifacts if item.artifact_type == ArtifactType.FINAL_RESPONSE]
        if not finals:
            return DeliveryGateResult(
                decision=DeliveryDecision.BLOCK,
                final_artifact_id=None,
                passed_checks=(),
                failure_codes=("FINAL_MISSING",),
            )
        final = finals[-1]
        passed.append(DeliveryCheck.FINAL_PRESENT)

        sources = self._sources(board, final)
        candidate = next((item for item in sources if item.artifact_type == ArtifactType.RESPONSE_CANDIDATE), None)
        review = next((item for item in sources if item.artifact_type == ArtifactType.REVIEW_RESULT), None)
        if candidate is None or review is None or candidate.artifact_id not in review.source_artifact_ids:
            failures.append("PROVENANCE_INVALID")
        else:
            passed.append(DeliveryCheck.PROVENANCE_VALID)

        if (
            review is None
            or review.content.get("approved") is not True
            or review.review_status != "approved"
            or final.review_status != "approved"
            or final.validation_status != "valid"
        ):
            failures.append("REVIEW_NOT_APPROVED")
        else:
            passed.append(DeliveryCheck.REVIEW_APPROVED)

        response = final.content.get("response")
        if not isinstance(response, str) or not response.strip():
            failures.append("RESPONSE_MISSING")
        else:
            passed.append(DeliveryCheck.RESPONSE_PRESENT)

        decision = final.content.get("decision")
        if decision not in self._allowed_decisions:
            failures.append("DECISION_INVALID")
        else:
            passed.append(DeliveryCheck.DECISION_VALID)

        claims = final.content.get("claims") or []
        cited_ids = set(final.evidence_refs)
        grounded = isinstance(claims, list) and all(
            isinstance(item, dict)
            and isinstance(item.get("text"), str)
            and bool(item.get("text", "").strip())
            and isinstance(item.get("evidence_ids"), list)
            and bool(item["evidence_ids"])
            and set(str(value) for value in item["evidence_ids"]).issubset(cited_ids)
            for item in claims
        )
        if decision == "supported_answer" and not claims:
            grounded = False
        if not grounded:
            failures.append("CLAIMS_UNGROUNDED")
        else:
            passed.append(DeliveryCheck.CLAIMS_GROUNDED)

        known_evidence = {
            ref
            for item in board.artifacts
            if item.artifact_type == ArtifactType.RAG_EVIDENCE_BUNDLE
            for ref in item.evidence_refs
        }
        item_evidence_ids = {
            str(evidence_id)
            for section_name in ("amount_items", "disputed_items")
            for item in (final.content.get("sections") or {}).get(section_name, [])
            if isinstance(item, dict)
            for evidence_id in item.get("evidence_ids", [])
        }
        if (
            (cited_ids and not cited_ids.issubset(known_evidence))
            or not item_evidence_ids.issubset(cited_ids)
        ):
            failures.append("EVIDENCE_NOT_FOUND")
        else:
            passed.append(DeliveryCheck.EVIDENCE_EXISTS)

        law_items = {
            f"law:{item.get('chunk_id')}": item
            for artifact in board.artifacts
            if artifact.artifact_type == ArtifactType.RAG_EVIDENCE_BUNDLE
            for result in artifact.content.get("results", [])
            if isinstance(result, dict)
            for item in result.get("items", [])
            if isinstance(item, dict) and item.get("kind") == "law" and item.get("chunk_id")
        }
        cited_laws = [law_items[item] for item in cited_ids if item in law_items]
        temporal_valid = all(
            is_law_effective_on(item, board.blackboard.event_date)
            for item in cited_laws
        )
        if decision == "supported_answer" and (not cited_laws or not temporal_valid):
            failures.append("LAW_TEMPORAL_VALIDITY_UNCONFIRMED")
        else:
            passed.append(DeliveryCheck.TEMPORAL_VALIDITY)

        pii_review = self.reviewer.review(response if isinstance(response, str) else "", policy=PIIPolicy.BLOCK)
        if pii_review.blocked:
            failures.append("PII_LEAK")
        else:
            passed.append(DeliveryCheck.PII_CLEAR)

        normalized_response = response.lower() if isinstance(response, str) else ""
        if any(marker in normalized_response for marker in self._prohibited_promises):
            failures.append("PROHIBITED_PROMISE")
        else:
            passed.append(DeliveryCheck.NO_PROHIBITED_PROMISE)

        if any(marker in normalized_response for marker in self._internal_markers):
            failures.append("INTERNAL_IDENTIFIER_LEAK")
        else:
            passed.append(DeliveryCheck.NO_INTERNAL_IDENTIFIER)

        try:
            FinalResponseContent.model_validate(final.content)
            structure_valid = True
        except ValueError:
            structure_valid = False
        if not structure_valid:
            failures.append("RESPONSE_STRUCTURE_INVALID")
        else:
            passed.append(DeliveryCheck.RESPONSE_STRUCTURE)

        return DeliveryGateResult(
            decision=DeliveryDecision.BLOCK if failures else DeliveryDecision.DELIVER,
            final_artifact_id=final.artifact_id,
            passed_checks=tuple(passed),
            failure_codes=tuple(failures),
        )

    def safe_error_artifact(self, board: AgentRunBoard, *, task_id: str, result: DeliveryGateResult) -> Artifact:
        return Artifact(
            run_id=board.run_id,
            task_id=task_id,
            artifact_type=ArtifactType.FINAL_RESPONSE,
            producer_agent="delivery-gate-v0.1",
            content=safe_error_content(self.SAFE_ERROR_TEXT).model_dump(mode="json"),
            source_artifact_ids=[result.final_artifact_id] if result.final_artifact_id else [],
            validation_status="valid",
            review_status="gate_blocked",
            risk_level="low",
        )

    @staticmethod
    def _sources(board: AgentRunBoard, artifact: Artifact) -> list[Artifact]:
        known = {item.artifact_id: item for item in board.artifacts}
        return [known[item_id] for item_id in artifact.source_artifact_ids if item_id in known]
