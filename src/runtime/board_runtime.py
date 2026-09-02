"""共享任务板 Orchestrator、claim 仲裁和最小可运行 Agent 集。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

from intake.blackboard import RiskAssessment, RiskLevel, SufficiencyDecision
from runtime.messages import AgentMessage, AgentRole, MessageType
from runtime.context import AgentContextView, ContextService
from runtime.agent_models import CandidateGenerator, StructuredModelRunner
from safety.delivery_gate import DeliveryGate
from runtime.final_response import FinalResponseContent, FinalResponseSections
from safety.law_validity import is_law_effective_on
from runtime.model_provider import ModelGateway, ModelProfile
from runtime.identifiers import utc_now
from runtime.tools import ToolExecutor, ToolResultStatus
from scenario_pack import RentalDepositScenarioPack, ScenarioPack
from runtime.taskboard import (
    AgentRunBoard,
    Artifact,
    ArtifactType,
    BoardTask,
    ClaimCandidate,
    EventType,
    EventVisibility,
    RunStatus,
    TaskStatus,
)


@dataclass(slots=True)
class AgentDelivery:
    artifacts: list[Artifact] = field(default_factory=list)
    derived_tasks: list[BoardTask] = field(default_factory=list)
    messages: list[AgentMessage] = field(default_factory=list)


class BoardAgent(Protocol):
    agent_id: str
    role: AgentRole
    capabilities: frozenset[str]

    def confidence_for(self, board: AgentRunBoard, task: BoardTask) -> float: ...

    def execute(
        self,
        board: AgentRunBoard,
        task: BoardTask,
        context: AgentContextView,
    ) -> AgentDelivery: ...


class BoardRuntimeError(ValueError):
    pass


class TaskBoardRuntime:
    """唯一推进任务板全局状态的 Orchestrator。"""

    def __init__(
        self,
        agents: list[BoardAgent],
        *,
        context_service: ContextService | None = None,
        delivery_gate: DeliveryGate | None = None,
    ) -> None:
        self.agents = {agent.agent_id: agent for agent in agents}
        if len(self.agents) != len(agents):
            raise ValueError("agent_id must be unique")
        self._agent_claims: dict[tuple[str, str], int] = {}
        self.context_service = context_service or ContextService()
        self.delivery_gate = delivery_gate or DeliveryGate()

    def create_root_task(self, board: AgentRunBoard) -> BoardTask:
        task = BoardTask(
            run_id=board.run_id,
            task_type="assess_safety",
            objective="评估当前用户消息的风险并建立本轮安全基线",
            priority=0,
            required_capabilities=["risk_assessment"],
            deduplication_key=f"assess_safety:{board.current_message_id}",
        )
        self.add_task(board, task)
        return task

    def add_task(self, board: AgentRunBoard, task: BoardTask) -> BoardTask | None:
        if task.run_id != board.run_id:
            raise BoardRuntimeError("task run_id mismatch")
        existing = next(
            (
                item
                for item in board.tasks
                if item.deduplication_key == task.deduplication_key
                and item.status not in {TaskStatus.FAILED, TaskStatus.CANCELLED}
            ),
            None,
        )
        if existing:
            board.append_event(
                EventType.TASK_DEDUPLICATED,
                actor_type="orchestrator",
                actor_id="orchestrator",
                task_id=existing.task_id,
                payload={"deduplication_key": task.deduplication_key},
            )
            return None
        if len(board.tasks) >= board.limits.max_tasks:
            raise BoardRuntimeError("max_tasks exhausted")
        if task.parent_task_id:
            parent = board.task(task.parent_task_id)
            if task.depth != parent.depth + 1:
                raise BoardRuntimeError("child task depth must equal parent depth + 1")
            if task.depth > board.limits.max_task_depth:
                raise BoardRuntimeError("max_task_depth exhausted")
            children = [item for item in board.tasks if item.parent_task_id == parent.task_id]
            if len(children) >= board.limits.max_children_per_task:
                raise BoardRuntimeError("max_children_per_task exhausted")
        for dependency_id in task.dependency_ids:
            dependency = board.task(dependency_id)
            if dependency.task_id == task.task_id or dependency.parent_task_id == task.task_id:
                raise BoardRuntimeError("task dependency cycle detected")
        board.tasks.append(task)
        board.append_event(
            EventType.TASK_CREATED,
            actor_type="orchestrator",
            actor_id="orchestrator",
            task_id=task.task_id,
            payload={"task_type": task.task_type, "priority": task.priority},
        )
        return task

    def run(self, board: AgentRunBoard, *, history: list[object] | None = None) -> AgentRunBoard:
        context_history = list(history or [])
        if not board.tasks:
            self.create_root_task(board)
        while board.status == RunStatus.RUNNING:
            if self._budget_exhausted(board):
                self._stop_for_budget(board)
                break
            board.round += 1
            before = self._progress_signature(board)
            claims_this_round: dict[str, int] = {}
            open_tasks = list(board.open_tasks)
            if not open_tasks:
                self._finish_or_mark_no_progress(board)
                if board.status != RunStatus.RUNNING:
                    break
                continue

            for task in open_tasks:
                agent = self._select_agent(board, task, claims_this_round)
                if agent is None:
                    task.status = TaskStatus.BLOCKED
                    task.failure_code = "no_capable_agent"
                    task.updated_at = utc_now()
                    continue
                self._execute_claim(board, task, agent, context_history)
                claims_this_round[agent.agent_id] = claims_this_round.get(agent.agent_id, 0) + 1

            after = self._progress_signature(board)
            if after == before:
                board.no_progress_rounds += 1
                board.append_event(
                    EventType.NO_PROGRESS,
                    actor_type="orchestrator",
                    actor_id="orchestrator",
                    payload={"round": board.round, "count": board.no_progress_rounds},
                )
            else:
                board.no_progress_rounds = 0
            if board.no_progress_rounds >= board.limits.max_no_progress_rounds:
                board.status = RunStatus.LIMITED
                break
        return board

    def _select_agent(
        self,
        board: AgentRunBoard,
        task: BoardTask,
        claims_this_round: dict[str, int],
    ) -> BoardAgent | None:
        candidates: list[tuple[float, str, BoardAgent]] = []
        required = set(task.required_capabilities)
        for agent in self.agents.values():
            if not required.issubset(agent.capabilities):
                continue
            claim_key = (board.run_id, agent.agent_id)
            if self._agent_claims.get(claim_key, 0) >= board.limits.max_claims_per_agent:
                continue
            if claims_this_round.get(agent.agent_id, 0) >= board.limits.max_claims_per_agent_per_round:
                continue
            confidence = agent.confidence_for(board, task)
            candidate = ClaimCandidate(
                agent_id=agent.agent_id,
                agent_role=agent.role,
                confidence=confidence,
                reason=f"capabilities={','.join(sorted(required)) or 'none'}",
            )
            task.claim_candidates.append(candidate)
            board.append_event(
                EventType.CLAIM_REQUESTED,
                actor_type="agent",
                actor_id=agent.agent_id,
                task_id=task.task_id,
                payload={"confidence": confidence},
            )
            candidates.append((confidence, agent.agent_id, agent))
        if not candidates:
            return None
        candidates.sort(key=lambda item: (-item[0], item[1]))
        winner = candidates[0][2]
        for _, agent_id, _ in candidates[1:]:
            board.append_event(
                EventType.CLAIM_REJECTED,
                actor_type="orchestrator",
                actor_id="orchestrator",
                task_id=task.task_id,
                payload={"agent_id": agent_id, "winner": winner.agent_id},
            )
        return winner

    def _execute_claim(
        self,
        board: AgentRunBoard,
        task: BoardTask,
        agent: BoardAgent,
        history: list[object],
    ) -> None:
        task.status = TaskStatus.CLAIMED
        task.claimed_by = agent.agent_id
        task.claim_count += 1
        task.updated_at = utc_now()
        board.total_claims += 1
        claim_key = (board.run_id, agent.agent_id)
        self._agent_claims[claim_key] = self._agent_claims.get(claim_key, 0) + 1
        board.append_event(
            EventType.CLAIM_ACCEPTED,
            actor_type="orchestrator",
            actor_id="orchestrator",
            task_id=task.task_id,
            payload={"agent_id": agent.agent_id},
        )
        task.status = TaskStatus.RUNNING
        task.attempt_count += 1
        board.append_event(
            EventType.TASK_STARTED,
            actor_type="agent",
            actor_id=agent.agent_id,
            task_id=task.task_id,
        )
        try:
            context = self.context_service.build(
                role=agent.role,
                task=task,
                board=board,
                history=history,
            )
            board.append_event(
                EventType.CONTEXT_BUILT,
                actor_type="context_service",
                actor_id="context-service-v0.1",
                task_id=task.task_id,
                payload={
                    "context_id": context.context_id,
                    "role": context.role.value,
                    "content_hash": context.content_hash,
                    "source_count": len(context.source_refs),
                    "is_truncated": context.is_truncated,
                    "omitted_sections": list(context.omitted_sections),
                },
                visibility=EventVisibility.DEVELOPER,
            )
            delivery = agent.execute(board, task, context)
            for artifact in delivery.artifacts:
                if artifact.run_id != board.run_id or artifact.task_id != task.task_id:
                    raise BoardRuntimeError("artifact identity mismatch")
                board.artifacts.append(artifact)
                task.output_artifact_ids.append(artifact.artifact_id)
                board.append_event(
                    EventType.ARTIFACT_CREATED,
                    actor_type="agent",
                    actor_id=agent.agent_id,
                    task_id=task.task_id,
                    artifact_id=artifact.artifact_id,
                    payload={"artifact_type": artifact.artifact_type.value},
                )
            for message in delivery.messages:
                if message.run_id != board.run_id:
                    raise BoardRuntimeError("message run_id mismatch")
                board.messages.append(message)
                board.append_event(
                    EventType.MESSAGE_SENT,
                    actor_type="agent",
                    actor_id=agent.agent_id,
                    task_id=task.task_id,
                    payload={
                        "message_id": message.message_id,
                        "message_type": message.message_type.value,
                        "to_role": message.to_role.value,
                    },
                )
            for derived in delivery.derived_tasks:
                self.add_task(board, derived)
            task.status = TaskStatus.COMPLETED
            board.append_event(
                EventType.TASK_COMPLETED,
                actor_type="agent",
                actor_id=agent.agent_id,
                task_id=task.task_id,
                payload={"artifact_ids": list(task.output_artifact_ids)},
            )
        except Exception as exc:
            task.status = TaskStatus.FAILED
            task.failure_code = "agent_execution_failed"
            board.append_event(
                EventType.TASK_FAILED,
                actor_type="agent",
                actor_id=agent.agent_id,
                task_id=task.task_id,
                payload={"error_code": task.failure_code, "error_type": type(exc).__name__},
            )
        finally:
            task.updated_at = utc_now()

    def _finish_or_mark_no_progress(self, board: AgentRunBoard) -> None:
        final_candidates = [artifact for artifact in board.artifacts if artifact.artifact_type == ArtifactType.FINAL_RESPONSE]
        if final_candidates:
            gate_result = self.delivery_gate.evaluate(board)
            if gate_result.approved:
                accepted = board.artifact(gate_result.final_artifact_id or "")
                event_type = EventType.DELIVERY_ACCEPTED
            else:
                accepted = self.delivery_gate.safe_error_artifact(
                    board,
                    task_id=final_candidates[-1].task_id,
                    result=gate_result,
                )
                board.artifacts.append(accepted)
                event_type = EventType.DELIVERY_BLOCKED
            if gate_result.approved:
                accepted.review_status = "accepted"
            board.accepted_artifact_id = accepted.artifact_id
            board.status = RunStatus.COMPLETED if gate_result.approved else RunStatus.FAILED
            board.append_event(
                event_type,
                actor_type="delivery_gate",
                actor_id="delivery-gate-v0.1",
                task_id=accepted.task_id,
                artifact_id=accepted.artifact_id,
                payload={
                    "failure_codes": list(gate_result.failure_codes),
                    "passed_checks": [item.value for item in gate_result.passed_checks],
                },
                visibility=EventVisibility.ADMIN,
            )
            board.append_event(
                EventType.ARTIFACT_ACCEPTED,
                actor_type="delivery_gate",
                actor_id="delivery-gate-v0.1",
                task_id=accepted.task_id,
                artifact_id=accepted.artifact_id,
            )
            board.append_event(
                EventType.RUN_COMPLETED,
                actor_type="orchestrator",
                actor_id="orchestrator",
                artifact_id=accepted.artifact_id,
                visibility=EventVisibility.ADMIN,
            )
            return
        if all(task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.BLOCKED} for task in board.tasks):
            board.status = RunStatus.LIMITED
            return
        board.no_progress_rounds += 1

    @staticmethod
    def _progress_signature(board: AgentRunBoard) -> tuple[int, int, int]:
        return (
            len([task for task in board.tasks if task.status == TaskStatus.COMPLETED]),
            len(board.artifacts),
            len(board.tasks),
        )

    @staticmethod
    def _budget_exhausted(board: AgentRunBoard) -> bool:
        return board.round >= board.limits.max_rounds or board.total_claims >= board.limits.max_total_claims

    @staticmethod
    def _stop_for_budget(board: AgentRunBoard) -> None:
        board.status = RunStatus.LIMITED
        board.append_event(
            EventType.BUDGET_EXHAUSTED,
            actor_type="orchestrator",
            actor_id="orchestrator",
            payload={"round": board.round, "total_claims": board.total_claims},
        )


def _child_task(
    board: AgentRunBoard,
    parent: BoardTask,
    *,
    task_type: str,
    objective: str,
    capability: str,
    input_artifact_ids: list[str],
    priority: int,
) -> BoardTask:
    return BoardTask(
        run_id=board.run_id,
        parent_task_id=parent.task_id,
        task_type=task_type,
        objective=objective,
        priority=priority,
        required_capabilities=[capability],
        depth=parent.depth + 1,
        dependency_ids=[parent.task_id],
        deduplication_key=f"{task_type}:{board.current_message_id}",
        input_artifact_ids=input_artifact_ids,
    )


class SafetyAgent:
    agent_id = "safety-agent-v0"
    role = AgentRole.SAFETY
    capabilities = frozenset({"risk_assessment"})
    model_profile = ModelProfile.SAFETY_FAST

    def __init__(self, candidate_generator: CandidateGenerator | None = None) -> None:
        self.candidate_generator = candidate_generator

    def confidence_for(self, board: AgentRunBoard, task: BoardTask) -> float:
        return 0.95 if task.task_type == "assess_safety" else 0.0

    def execute(self, board: AgentRunBoard, task: BoardTask, context: AgentContextView) -> AgentDelivery:
        high_markers = ("杀", "自杀", "拿刀", "报复", "威胁人身", "正在打我")
        medium_markers = ("堵门", "威胁", "跟踪", "骚扰")
        if any(marker in board.sanitized_input for marker in high_markers):
            level, signals, action = RiskLevel.HIGH, ["immediate_safety"], "safety_response"
        elif any(marker in board.sanitized_input for marker in medium_markers):
            level, signals, action = RiskLevel.MEDIUM, ["potential_personal_safety"], "continue_with_warning"
        else:
            level, signals, action = RiskLevel.LOW, [], "continue"
        candidate = _model_candidate(
            self.candidate_generator, board, task, context, self.model_profile,
            "你是安全分类器。只基于给定脱敏上下文返回结构化风险候选，不提供法律结论。",
            _object_schema({
                "level": {"type": "string", "enum": [item.value for item in RiskLevel]},
                "signal_types": {"type": "array", "items": {"type": "string"}},
                "recommended_action": {"type": "string"},
            }, ["level", "signal_types", "recommended_action"]),
        )
        if candidate and level != RiskLevel.HIGH:
            try:
                proposed_level = RiskLevel(candidate.get("level"))
                risk_rank = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}
                if risk_rank[proposed_level] >= risk_rank[level]:
                    level = proposed_level
                signals = [str(item) for item in candidate.get("signal_types", [])][:8]
                action = str(candidate.get("recommended_action") or action)[:200]
            except (TypeError, ValueError):
                pass
        assessment = RiskAssessment(
            assessed_through_message_id=board.current_message_id,
            level=level,
            signal_types=signals,
            recommended_action=action,
        )
        board.blackboard.risk_assessments.append(assessment)
        artifact = Artifact(
            run_id=board.run_id,
            task_id=task.task_id,
            artifact_type=ArtifactType.RISK_REVIEW,
            producer_agent=self.agent_id,
            risk_level=level.value,
            content=assessment.model_dump(mode="json"),
            confidence=0.9,
        )
        next_task = _child_task(
            board,
            task,
            task_type="understand_message",
            objective="识别意图、场景、事实候选和信息缺口",
            capability="message_understanding",
            input_artifact_ids=[artifact.artifact_id],
            priority=10,
        )
        return AgentDelivery(
            artifacts=[artifact],
            derived_tasks=[next_task],
            messages=[AgentMessage(
                run_id=board.run_id,
                from_role=self.role,
                to_role=AgentRole.ORCHESTRATOR,
                message_type=MessageType.RISK_RESULT,
                payload={"artifact_id": artifact.artifact_id, "level": level.value},
                confidence=0.9,
            )],
        )


class UnderstandingAgent:
    agent_id = "understanding-agent-v0"
    role = AgentRole.INTAKE
    capabilities = frozenset({"message_understanding"})
    model_profile = ModelProfile.UNDERSTANDING_STRUCTURED
    def __init__(
        self,
        candidate_generator: CandidateGenerator | None = None,
        scenario_pack: ScenarioPack | None = None,
    ) -> None:
        self.candidate_generator = candidate_generator
        self.scenario_pack = scenario_pack or RentalDepositScenarioPack()

    def confidence_for(self, board: AgentRunBoard, task: BoardTask) -> float:
        return 0.9 if task.task_type == "understand_message" else 0.0

    def execute(self, board: AgentRunBoard, task: BoardTask, context: AgentContextView) -> AgentDelivery:
        text = board.sanitized_input
        facts = board.blackboard.confirmed_facts
        candidate = _model_candidate(
            self.candidate_generator, board, task, context, self.model_profile,
            "抽取用户陈述中的候选事实。候选不得自动标为用户确认，不得补全用户未提供的信息。",
            _object_schema({
                "candidate_facts": {"type": "object", "additionalProperties": {"type": "string"}},
            }, ["candidate_facts"]),
        )
        if candidate and isinstance(candidate.get("candidate_facts"), dict):
            for key, value in candidate["candidate_facts"].items():
                if isinstance(key, str) and isinstance(value, str) and key not in facts:
                    board.blackboard.candidate_facts[key[:100]] = value[:1_000]
        extracted_facts = self.scenario_pack.extract_facts(text, facts)
        facts.update(extracted_facts)
        if "event_date" in extracted_facts:
            try:
                board.blackboard.event_date = date.fromisoformat(extracted_facts["event_date"])
            except ValueError:
                pass
        if "不知道" in text:
            for key in board.blackboard.sufficiency.missing_fact_keys:
                if key not in board.blackboard.sufficiency.unknown_to_user_fact_keys:
                    board.blackboard.sufficiency.unknown_to_user_fact_keys.append(key)

        required_specs = [
            spec for spec in self.scenario_pack.required_fact_keys("intake") if spec.required
        ]
        required = [spec.key for spec in required_specs]
        question_by_key = {spec.key: spec.description for spec in required_specs}
        missing = [
            key for key in required
            if key not in facts and key not in board.blackboard.sufficiency.unknown_to_user_fact_keys
        ]
        sufficiency = board.blackboard.sufficiency
        sufficiency.missing_fact_keys = missing
        available_questions = [key for key in missing if key not in sufficiency.asked_question_keys]
        if not missing:
            sufficiency.decision = SufficiencyDecision.START_RETRIEVAL
        elif sufficiency.clarification_round >= sufficiency.max_clarification_rounds:
            sufficiency.decision = SufficiencyDecision.DELIVER_LIMITED_RESPONSE
        elif available_questions:
            sufficiency.decision = SufficiencyDecision.ASK_CLARIFICATION
            selected = available_questions[:3]
            sufficiency.asked_question_keys.extend(selected)
            sufficiency.clarification_round += 1
        else:
            sufficiency.decision = SufficiencyDecision.DELIVER_LIMITED_RESPONSE
            selected = []

        artifact = Artifact(
            run_id=board.run_id,
            task_id=task.task_id,
            artifact_type=ArtifactType.SUFFICIENCY_ASSESSMENT,
            producer_agent=self.agent_id,
            content={
                "intent": self.scenario_pack.scenario_id,
                "scenario_id": self.scenario_pack.scenario_id,
                "out_of_scope": self.scenario_pack.is_out_of_scope(facts),
                "confirmed_facts": dict(facts),
                "missing_fact_keys": list(missing),
                "decision": sufficiency.decision.value,
                "question_keys": selected if 'selected' in locals() else [],
                "questions": [
                    question_by_key[key] for key in (selected if 'selected' in locals() else [])
                ],
            },
            confidence=0.8,
        )
        if sufficiency.decision == SufficiencyDecision.START_RETRIEVAL:
            next_task = _child_task(
                board, task, task_type="retrieve_context", objective="规划最小法规与案例检索",
                capability="context_retrieval", input_artifact_ids=[artifact.artifact_id], priority=20,
            )
        else:
            next_task = _child_task(
                board, task, task_type="compose_response", objective="生成追问或证据受限回复",
                capability="response_drafting", input_artifact_ids=[artifact.artifact_id], priority=20,
            )
        return AgentDelivery(artifacts=[artifact], derived_tasks=[next_task])


class RetrievalAgent:
    """生成检索意图，并且只通过唯一 ToolExecutor 执行。"""

    agent_id = "retrieval-agent-v0"
    role = AgentRole.RETRIEVAL
    capabilities = frozenset({"context_retrieval"})
    model_profile = ModelProfile.RETRIEVAL_PLANNER

    def __init__(
        self,
        tool_executor: ToolExecutor | None = None,
        candidate_generator: CandidateGenerator | None = None,
        scenario_pack: ScenarioPack | None = None,
    ) -> None:
        self.tool_executor = tool_executor
        self.candidate_generator = candidate_generator
        self.scenario_pack = scenario_pack or RentalDepositScenarioPack()

    def confidence_for(self, board: AgentRunBoard, task: BoardTask) -> float:
        return 0.9 if task.task_type == "retrieve_context" else 0.0

    def execute(self, board: AgentRunBoard, task: BoardTask, context: AgentContextView) -> AgentDelivery:
        query_parts = [self.scenario_pack.retrieval_query_prefix().strip()]
        query_parts.extend(board.blackboard.confirmed_facts.values())
        query = " ".join(part for part in query_parts if part)
        candidate = _model_candidate(
            self.candidate_generator, board, task, context, self.model_profile,
            "生成一个简洁中文法律检索查询。不得生成数据库过滤器或任意工具名。",
            _object_schema({"query": {"type": "string"}}, ["query"]),
        )
        if candidate and isinstance(candidate.get("query"), str) and candidate["query"].strip():
            query = candidate["query"].strip()[:1_000]
        plan = Artifact(
            run_id=board.run_id, task_id=task.task_id,
            artifact_type=ArtifactType.RETRIEVAL_PLAN, producer_agent=self.agent_id,
            content={
                "intents": [
                    {"tool_name": "search_statutes", "arguments": {"query": query, "top_k": 5}},
                    {"tool_name": "search_cases", "arguments": {"query": query, "top_k": 5}},
                ],
                "execution_status": "pending" if self.tool_executor is None else "approved",
            },
            validation_status="valid",
        )
        results: list[dict[str, object]] = []
        evidence_refs: list[str] = []
        warnings: list[str] = []
        if self.tool_executor is None:
            warnings.append("tool_executor_unavailable")
        else:
            for intent in plan.content["intents"]:
                result = self.tool_executor.execute(intent["tool_name"], intent["arguments"])
                serialized_items = [item.model_dump(mode="json") for item in result.items]
                item_refs = [_evidence_ref(item) for item in result.items]
                evidence_refs.extend(item_refs)
                warnings.extend(result.warnings)
                results.append(
                    {
                        "tool_name": result.tool_name,
                        "status": result.status.value,
                        "items": serialized_items,
                        "evidence_refs": item_refs,
                        "warnings": list(result.warnings),
                        "latency_ms": result.latency_ms,
                        "trace_id": result.trace_id,
                    }
                )
        unique_refs = list(dict.fromkeys(evidence_refs))
        for evidence_id in unique_refs:
            if evidence_id not in board.blackboard.evidence_ids:
                board.blackboard.evidence_ids.append(evidence_id)
        evidence = Artifact(
            run_id=board.run_id,
            task_id=task.task_id,
            artifact_type=ArtifactType.RAG_EVIDENCE_BUNDLE,
            producer_agent=self.agent_id,
            source_artifact_ids=[plan.artifact_id],
            evidence_refs=unique_refs,
            content={
                "results": results,
                "warnings": warnings,
                "evidence_count": len(unique_refs),
                "is_sufficient": bool(unique_refs),
            },
            validation_status="valid" if unique_refs else "partial",
        )
        next_task = _child_task(
            board, task, task_type="analyze_evidence", objective="根据安全 Evidence Bundle 形成受限分析",
            capability="evidence_analysis", input_artifact_ids=[evidence.artifact_id], priority=30,
        )
        return AgentDelivery(artifacts=[plan, evidence], derived_tasks=[next_task])


class AnalysisAgent:
    agent_id = "analysis-agent-v0"
    role = AgentRole.ANALYSIS
    capabilities = frozenset({"evidence_analysis"})
    model_profile = ModelProfile.LEGAL_ANALYSIS

    def __init__(
        self,
        candidate_generator: CandidateGenerator | None = None,
        scenario_pack: ScenarioPack | None = None,
    ) -> None:
        self.candidate_generator = candidate_generator
        self.scenario_pack = scenario_pack or RentalDepositScenarioPack()

    def confidence_for(self, board: AgentRunBoard, task: BoardTask) -> float:
        return 0.9 if task.task_type == "analyze_evidence" else 0.0

    def execute(self, board: AgentRunBoard, task: BoardTask, context: AgentContextView) -> AgentDelivery:
        evidence = board.artifact(task.input_artifact_ids[0])
        evidence_refs = list(evidence.evidence_refs)
        candidate = _model_candidate(
            self.candidate_generator, board, task, context, self.model_profile,
            "仅依据 Evidence DTO 形成条件化法律分析。每个实质主张必须绑定已有 evidence ID。",
            _object_schema({
                "claims": {"type": "array", "items": {"type": "object"}},
                "limitations": {"type": "array", "items": {"type": "string"}},
            }, ["claims", "limitations"]),
        )
        law_items = [
            item
            for result in evidence.content.get("results", [])
            if isinstance(result, dict)
            for item in result.get("items", [])
            if isinstance(item, dict) and item.get("kind") == "law"
        ]
        law_versions_confirmed = bool(law_items) and all(
            is_law_effective_on(item, board.blackboard.event_date)
            for item in law_items
        )
        if evidence_refs and law_versions_confirmed:
            claims = [
                {
                    "text": "争议责任需要结合已确认事实、约定内容和有来源标识的证据判断。",
                    "evidence_ids": evidence_refs,
                }
            ]
            limitations = ["当前结论为基于固定数据快照的初步信息，不替代律师意见或裁判。"]
            decision = "supported_answer"
            model_claims = _validated_claims(candidate, set(evidence_refs))
            if model_claims:
                claims = model_claims
                limitations = [str(item)[:1_000] for item in candidate.get("limitations", [])[:10]]
        elif evidence_refs:
            claims = []
            limitations = ["法规版本或效力状态尚未确认，不能据此给出具体法律结论。"]
            decision = "constructive_abstention"
        else:
            claims = []
            limitations = ["真实法规与案例检索没有返回可用证据"]
            decision = "limited_answer"
        amount_items = []
        if not self.scenario_pack.is_out_of_scope(board.blackboard.confirmed_facts):
            law_refs = [ref for ref in evidence_refs if ref.startswith("law:")]
            amount_items = [
                {
                    "item_key": item.item_key,
                    "display_name": item.display_name,
                    "legal_basis_hint": item.legal_basis_hint,
                    "legal_basis_refs": law_refs,
                    "calculation_logic": item.calculation_logic,
                    "requires_user_confirmation": True,
                }
                for item in self.scenario_pack.amount_calculation_items()
                if self.scenario_pack.is_amount_item_applicable(
                    item.item_key, board.blackboard.confirmed_facts
                )
            ]
        artifact = Artifact(
            run_id=board.run_id, task_id=task.task_id,
            artifact_type=ArtifactType.ISSUE_ANALYSIS, producer_agent=self.agent_id,
            source_artifact_ids=list(task.input_artifact_ids),
            evidence_refs=evidence_refs,
            content={
                "decision": decision,
                "claims": claims,
                "limitations": limitations,
                "amount_items": amount_items,
            },
        )
        next_task = _child_task(
            board, task, task_type="compose_response", objective="生成证据受限回复",
            capability="response_drafting", input_artifact_ids=[artifact.artifact_id], priority=40,
        )
        return AgentDelivery(artifacts=[artifact], derived_tasks=[next_task])


class ResponseAgent:
    agent_id = "response-agent-v0"
    role = AgentRole.DRAFTING
    capabilities = frozenset({"response_drafting"})
    model_profile = ModelProfile.RESPONSE_GENERATION

    def __init__(self, candidate_generator: CandidateGenerator | None = None) -> None:
        self.candidate_generator = candidate_generator

    def confidence_for(self, board: AgentRunBoard, task: BoardTask) -> float:
        return 0.9 if task.task_type == "compose_response" else 0.0

    def execute(self, board: AgentRunBoard, task: BoardTask, context: AgentContextView) -> AgentDelivery:
        sufficiency = board.blackboard.sufficiency
        if sufficiency.decision == SufficiencyDecision.ASK_CLARIFICATION:
            source = board.artifact(task.input_artifact_ids[0])
            questions = [str(item) for item in source.content.get("questions", [])]
            response = "为了判断是否进入法律检索，请补充：\n" + "\n".join(
                f"{index}. {question}" for index, question in enumerate(questions, 1)
            )
            decision = "clarification_needed"
        else:
            source = board.artifact(task.input_artifact_ids[0])
            decision = str(source.content.get("decision") or "limited_answer")
            if decision == SufficiencyDecision.DELIVER_LIMITED_RESPONSE.value:
                decision = "limited_answer"
            claims = source.content.get("claims") or []
            if claims:
                response = "初步分析：" + " ".join(str(item["text"]) for item in claims)
                response += "\n证据引用：" + "、".join(source.evidence_refs)
            else:
                if decision == "constructive_abstention":
                    response = (
                        "当前证据的法规版本或效力状态尚未确认，因此不能安全给出具体法律结论。"
                        "建议核对事件日期和权威法规版本后再继续分析。"
                    )
                else:
                    response = (
                        "我已记录目前能够确认的信息。当前检索没有返回可用于支持具体法律结论的证据，"
                        "因此本轮只提供有限结果。"
                    )
        candidate = _model_candidate(
            self.candidate_generator, board, task, context, self.model_profile,
            "根据候选分析生成简洁中文答复。不得增加新的事实、引用、金额或法律主张。",
            _object_schema({"response": {"type": "string"}}, ["response"]),
        )
        if candidate and isinstance(candidate.get("response"), str) and candidate["response"].strip():
            response = candidate["response"].strip()[:12_000]
        artifact = Artifact(
            run_id=board.run_id, task_id=task.task_id,
            artifact_type=ArtifactType.RESPONSE_CANDIDATE, producer_agent=self.agent_id,
            source_artifact_ids=list(task.input_artifact_ids),
            evidence_refs=list(source.evidence_refs) if 'source' in locals() else [],
            content=_final_response_content(
                board=board,
                response=response,
                decision=decision,
                claims=claims if 'claims' in locals() else [],
                evidence_refs=list(source.evidence_refs) if 'source' in locals() else [],
                limitations=source.content.get("limitations") or (
                    ["当前信息不足，不能形成具体法律结论。"]
                    if decision in {"limited_answer", "constructive_abstention"}
                    else []
                ),
            ),
            review_status="pending",
        )
        review_task = _child_task(
            board, task, task_type="review_response", objective="独立复核候选回复是否可交付",
            capability="response_review", input_artifact_ids=[artifact.artifact_id], priority=50,
        )
        return AgentDelivery(artifacts=[artifact], derived_tasks=[review_task])


class ReviewAgent:
    agent_id = "review-agent-v0"
    role = AgentRole.REVIEW
    capabilities = frozenset({"response_review"})
    model_profile = ModelProfile.INDEPENDENT_REVIEW

    def __init__(self, candidate_generator: CandidateGenerator | None = None) -> None:
        self.candidate_generator = candidate_generator

    def confidence_for(self, board: AgentRunBoard, task: BoardTask) -> float:
        return 0.95 if task.task_type == "review_response" else 0.0

    def execute(self, board: AgentRunBoard, task: BoardTask, context: AgentContextView) -> AgentDelivery:
        candidate = board.artifact(task.input_artifact_ids[0])
        claims = candidate.content.get("claims") or []
        cited_ids = set(candidate.evidence_refs)
        claims_are_grounded = all(
            set(item.get("evidence_ids") or []).issubset(cited_ids)
            and bool(item.get("evidence_ids"))
            for item in claims
        )
        deterministic_approved = bool(candidate.content.get("response")) and claims_are_grounded
        approved = deterministic_approved
        model_review = _model_candidate(
            self.candidate_generator, board, task, context, self.model_profile,
            "独立审查候选回答。证据不足、引用不支持或越权时必须拒绝。",
            _object_schema({
                "approved": {"type": "boolean"},
                "reason": {"type": "string"},
            }, ["approved", "reason"]),
        )
        review_reason = "no_unsupported_claims" if approved else "invalid_candidate"
        if model_review is not None:
            approved = approved and model_review.get("approved") is True
            if deterministic_approved:
                review_reason = str(model_review.get("reason") or review_reason)[:1_000]
        review = Artifact(
            run_id=board.run_id, task_id=task.task_id,
            artifact_type=ArtifactType.REVIEW_RESULT, producer_agent=self.agent_id,
            source_artifact_ids=[candidate.artifact_id],
            content={"approved": approved, "reason": review_reason},
            review_status="approved" if approved else "rejected",
        )
        final = Artifact(
            run_id=board.run_id, task_id=task.task_id,
            artifact_type=ArtifactType.FINAL_RESPONSE, producer_agent=self.agent_id,
            source_artifact_ids=[candidate.artifact_id, review.artifact_id],
            evidence_refs=list(candidate.evidence_refs),
            content=dict(candidate.content) if approved else {"response": "当前无法安全生成回复。", "decision": "failed"},
            review_status="approved" if approved else "rejected",
            validation_status="valid" if approved else "invalid",
        )
        return AgentDelivery(artifacts=[review, final])


def _evidence_ref(item: object) -> str:
    if hasattr(item, "chunk_id"):
        return f"law:{getattr(item, 'chunk_id')}"
    return f"case:{getattr(item, 'case_id')}"


def build_default_agents(
    tool_executor: ToolExecutor | None = None,
    model_gateway: ModelGateway | None = None,
    scenario_pack: ScenarioPack | None = None,
) -> list[BoardAgent]:
    candidates = StructuredModelRunner(model_gateway) if model_gateway is not None else None
    pack = scenario_pack or RentalDepositScenarioPack()
    return [
        SafetyAgent(candidates),
        UnderstandingAgent(candidates, pack),
        RetrievalAgent(tool_executor, candidates, pack),
        AnalysisAgent(candidates, pack),
        ResponseAgent(candidates),
        ReviewAgent(candidates),
    ]


def _model_candidate(
    generator: CandidateGenerator | None,
    board: AgentRunBoard,
    task: BoardTask,
    context: AgentContextView,
    profile: ModelProfile,
    system_prompt: str,
    response_schema: dict[str, Any],
) -> dict[str, Any] | None:
    if generator is None:
        return None
    return generator.generate(
        board=board,
        task=task,
        context=context,
        profile=profile,
        system_prompt=system_prompt,
        response_schema=response_schema,
    )


def _object_schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _validated_claims(candidate: dict[str, Any] | None, allowed_ids: set[str]) -> list[dict[str, Any]]:
    if not candidate or not isinstance(candidate.get("claims"), list):
        return []
    validated: list[dict[str, Any]] = []
    for item in candidate["claims"][:20]:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            continue
        evidence_ids = item.get("evidence_ids")
        if not isinstance(evidence_ids, list) or not evidence_ids:
            continue
        normalized_ids = [str(value) for value in evidence_ids]
        if not set(normalized_ids).issubset(allowed_ids):
            continue
        validated.append({"text": item["text"][:2_000], "evidence_ids": normalized_ids})
    return validated


def _final_response_content(
    *,
    board: AgentRunBoard,
    response: str,
    decision: str,
    claims: list[dict[str, Any]],
    evidence_refs: list[str],
    limitations: list[str],
) -> dict[str, Any]:
    law_refs = [item for item in evidence_refs if item.startswith("law:")]
    case_refs = [item for item in evidence_refs if item.startswith("case:")]
    sections = FinalResponseSections(
        current_situation=[f"{key}: {value}" for key, value in board.blackboard.confirmed_facts.items()],
        preliminary_assessment=[str(item.get("text")) for item in claims],
        statutes=law_refs,
        similar_cases=case_refs,
        materials=["合同、押金支付记录、交房记录和沟通记录"],
        low_cost_communication=["先以可留痕方式核对扣款项目和依据"],
        formal_notice=["必要时发送载明事实、金额和回复期限的书面催告"],
        other_remedies=["根据证据与当地程序咨询调解、诉讼或专业律师"],
        limitations=list(limitations),
    )
    content = FinalResponseContent(
        response=response,
        decision=decision,
        confirmed_facts=dict(board.blackboard.confirmed_facts),
        unresolved_facts=list(board.blackboard.sufficiency.missing_fact_keys),
        claims=claims,
        sections=sections,
        citation_map={f"claim:{index}": list(item["evidence_ids"]) for index, item in enumerate(claims)},
        source_snapshot_versions=[],
        limitations=list(limitations),
    )
    return content.model_dump(mode="json")


# 兼容旧导入；新代码使用 UnderstandingAgent/ResponseAgent。
IntentAgent = UnderstandingAgent
SafeResponseAgent = ResponseAgent
