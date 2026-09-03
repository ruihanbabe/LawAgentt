"""场景策略契约与住宅租赁押金纠纷 MVP 实现。"""

from __future__ import annotations

import re
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


FactLayer = Literal["intake", "analysis", "action"]


class FactKeySpec(BaseModel):
    """某处理层需要了解的一个事实字段。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(min_length=1, max_length=100)
    layer: FactLayer
    required: bool
    description: str = Field(min_length=1, max_length=500)


class ClaimItemSpec(BaseModel):
    """场景允许分析的一个权益或救济项目。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    item_key: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=100)
    relief_kind: Literal["monetary", "non_monetary", "disputed_catchall"]
    legal_basis_hint: str = Field(min_length=1, max_length=500)
    applicability_signal: str = Field(min_length=1, max_length=500)


class PartyLabels(BaseModel):
    """仅用于向用户渲染的本方与对方称谓。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    self_label: str = Field(min_length=1, max_length=100)
    counterparty_label: str = Field(min_length=1, max_length=100)


class ActionTemplateSpec(BaseModel):
    """根据案件事实确定性选择的一组行动建议模板。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    condition_key: str = Field(min_length=1, max_length=100)
    materials: tuple[str, ...] = ()
    low_cost_communication: tuple[str, ...] = ()
    formal_notice: tuple[str, ...] = ()
    other_remedies: tuple[str, ...] = ()


@runtime_checkable
class ScenarioPack(Protocol):
    """通用 Runtime 消费的场景策略边界。"""

    scenario_id: str

    def required_fact_keys(self, layer: FactLayer) -> list[FactKeySpec]: ...

    def party_labels(self, facts: dict[str, str]) -> PartyLabels: ...

    def retrieval_query_prefix(self) -> str: ...

    def claim_items(self) -> list[ClaimItemSpec]: ...

    def is_claim_item_applicable(
        self, item_key: str, facts: dict[str, str]
    ) -> Literal["applicable", "not_applicable", "uncertain"]: ...

    def is_out_of_scope(self, facts: dict[str, str]) -> bool: ...

    def extract_facts(self, text: str, existing_facts: dict[str, str]) -> dict[str, str]: ...

    def action_templates(self, facts: dict[str, str]) -> ActionTemplateSpec: ...

    def dispatch_trigger_fields(self) -> frozenset[str]: ...


class RentalDepositScenarioPack:
    """中国大陆住宅租赁押金纠纷场景策略。"""

    scenario_id = "rental-deposit-v0.1"

    _fact_specs = (
        FactKeySpec(key="tenancy_ended", layer="intake", required=True,
                    description="租赁是否已经结束，并且你是否已经交还房屋和钥匙？"),
        FactKeySpec(key="deposit_amount", layer="intake", required=True,
                    description="押金金额是多少，并且你是否有相应支付凭证？"),
        FactKeySpec(key="counterparty_position", layer="intake", required=True,
                    description="房东给出的不退或扣除押金的具体理由是什么？"),
        FactKeySpec(key="contract_terms", layer="intake", required=True,
                    description="合同对押金返还、扣款条件和返还时间有什么约定？"),
        FactKeySpec(key="evidence", layer="intake", required=True,
                    description="你目前有合同、押金支付记录、交房记录或与房东的沟通记录吗？"),
        FactKeySpec(key="event_date", layer="intake", required=True,
                    description="押金应返还或发生扣款争议的大致日期是什么？请尽量提供 YYYY-MM-DD。"),
        FactKeySpec(key="scope_status", layer="intake", required=True,
                    description="租赁物是否为境内住宅，且不涉及转租、群租或组织承租？"),
        FactKeySpec(key="property_use", layer="analysis", required=False,
                    description="租赁物是否为住宅"),
        FactKeySpec(key="sublease_or_group_rental", layer="analysis", required=False,
                    description="是否涉及转租、群租等排除情形"),
        FactKeySpec(key="desired_action", layer="action", required=False,
                    description="用户希望沟通、催告、调解或诉讼"),
    )
    _claim_items = (
        ClaimItemSpec(item_key="refundable_deposit_base", display_name="应退押金基数",
                       relief_kind="monetary",
                       legal_basis_hint="住宅租赁押金返还 合同约定 押金支付凭证",
                       applicability_signal="存在押金金额及支付凭证"),
        ClaimItemSpec(item_key="deductions", display_name="扣除项",
                       relief_kind="monetary",
                       legal_basis_hint="租赁押金扣除 欠租 欠费 房屋损坏 举证责任",
                       applicability_signal="对方提出欠租、欠费、损坏等扣除理由"),
        ClaimItemSpec(item_key="liquidated_damages", display_name="违约金",
                       relief_kind="monetary",
                       legal_basis_hint="租赁合同违约金 约定 调整 民法典",
                       applicability_signal="合同包含违约金、违约或提前退租约定"),
        ClaimItemSpec(item_key="overdue_interest", display_name="逾期利息/资金占用赔偿",
                       relief_kind="monetary",
                       legal_basis_hint="押金逾期返还 利息 资金占用损失",
                       applicability_signal="租赁已结束且押金返还期限可能届满"),
        ClaimItemSpec(item_key="disputed_deductions", display_name="争议扣除项",
                       relief_kind="disputed_catchall",
                       legal_basis_hint="押金争议扣除 合理损耗 维修费用 证据",
                       applicability_signal="存在目录未覆盖或依据、金额尚不明确的争议"),
    )
    _amount_pattern = re.compile(
        r"(?:押金|保证金)(?:是|为|共|金额)?\s*(?:人民币)?\s*"
        r"(?P<amount>\d+(?:\.\d{1,2})?)\s*(?P<unit>元|万元|万)?"
    )
    _date_pattern = re.compile(r"(?<!\d)(20\d{2}-\d{2}-\d{2})(?!\d)")

    def required_fact_keys(self, layer: FactLayer) -> list[FactKeySpec]:
        return [spec for spec in self._fact_specs if spec.layer == layer]

    def party_labels(self, facts: dict[str, str]) -> PartyLabels:
        return PartyLabels(self_label="承租人", counterparty_label="房东")

    def retrieval_query_prefix(self) -> str:
        return "住宅租赁 押金返还"

    def claim_items(self) -> list[ClaimItemSpec]:
        return list(self._claim_items)

    def is_claim_item_applicable(
        self, item_key: str, facts: dict[str, str]
    ) -> Literal["applicable", "not_applicable", "uncertain"]:
        if item_key not in {item.item_key for item in self._claim_items}:
            raise ValueError(f"unknown claim item: {item_key}")
        if item_key == "refundable_deposit_base":
            return "applicable" if facts.get("deposit_amount") else "uncertain"
        if item_key == "deductions":
            return "applicable" if facts.get("counterparty_position") else "uncertain"
        if item_key == "liquidated_damages":
            terms = facts.get("contract_terms", "")
            if not terms:
                return "uncertain"
            return "applicable" if any(
                marker in terms for marker in ("违约金", "违约", "提前退租")
            ) else "not_applicable"
        if item_key == "overdue_interest":
            if not facts.get("tenancy_ended") or not facts.get("event_date"):
                return "uncertain"
            return "applicable" if facts["tenancy_ended"] == "yes" else "not_applicable"
        reason = facts.get("counterparty_position", "")
        if not reason:
            return "uncertain"
        return "applicable" if any(
            marker in reason for marker in ("争议", "损坏", "维修", "卫生", "欠费", "扣")
        ) else "uncertain"

    def is_out_of_scope(self, facts: dict[str, str]) -> bool:
        property_use = facts.get("property_use", "").lower()
        scope = facts.get("scope_status", "").lower()
        sublease = facts.get("sublease_or_group_rental", "").lower()
        return (
            property_use in {"non_residential", "commercial", "非住宅", "商铺", "办公"}
            or scope in {"out_of_scope", "excluded", "排除"}
            or sublease in {"yes", "true", "转租", "群租"}
        )

    def extract_facts(self, text: str, existing_facts: dict[str, str]) -> dict[str, str]:
        """仅提取文本中的显式信号，且不修改或覆盖既有事实。"""
        extracted: dict[str, str] = {}

        def add(key: str, value: str) -> None:
            if key not in existing_facts and key not in extracted:
                extracted[key] = value

        if any(marker in text for marker in ("已退租", "已经退租", "已交房", "交还钥匙", "交了钥匙")):
            add("tenancy_ended", "yes")
        elif any(marker in text for marker in ("没退租", "还没退租", "尚未退租", "仍在租")):
            add("tenancy_ended", "no")

        amount_match = self._amount_pattern.search(text)
        if amount_match:
            add("deposit_amount", f"{amount_match.group('amount')}{amount_match.group('unit') or '元'}")

        reason_markers = ("房屋损坏", "损坏", "欠租", "欠费", "卫生", "提前退租", "违约", "不说理由")
        reason = next((marker for marker in reason_markers if marker in text), None)
        if reason:
            add("counterparty_position", reason)
        if "没有书面合同" in text or "没签合同" in text:
            add("contract_terms", "no_written_contract")
        elif "违约金" in text or "提前退租" in text:
            add("contract_terms", "包含违约金或提前退租约定")
        elif "合同" in text:
            add("contract_terms", "mentioned")
        if any(marker in text for marker in ("转账", "聊天记录", "收据", "交房记录", "照片")):
            add("evidence", "available")
        date_match = self._date_pattern.search(text)
        if date_match:
            add("event_date", date_match.group(1))
        if any(marker in text for marker in ("商铺", "办公室", "办公用房", "非住宅")):
            add("property_use", "non_residential")
            add("scope_status", "out_of_scope")
        elif any(marker in text for marker in ("住宅", "住房", "公寓")):
            add("property_use", "residential")
            add("scope_status", "in_scope")
        if "转租" in text:
            add("sublease_or_group_rental", "转租")
            if "scope_status" not in existing_facts:
                extracted["scope_status"] = "out_of_scope"
        elif "群租" in text:
            add("sublease_or_group_rental", "群租")
            if "scope_status" not in existing_facts:
                extracted["scope_status"] = "out_of_scope"
        return extracted

    def action_templates(self, facts: dict[str, str]) -> ActionTemplateSpec:
        if facts.get("contract_terms") == "no_written_contract":
            return ActionTemplateSpec(
                condition_key="missing_written_contract",
                materials=("整理押金转账、收据、聊天记录和实际入住证明",),
                low_cost_communication=("书面确认租赁关系、押金金额及返还期限",),
                formal_notice=("按现有交易证据整理催告要点并设定合理期限",),
                other_remedies=("准备调解或诉讼所需的租赁关系证明链",),
            )
        return ActionTemplateSpec(
            condition_key="standard_deposit_dispute",
            materials=("整理合同、押金支付凭证、交房记录和双方沟通记录",),
            low_cost_communication=("书面要求房东逐项说明扣款依据并提供凭证",),
            formal_notice=("根据合同约定整理返还押金的正式催告要点",),
            other_remedies=("保留调解、投诉或诉讼所需材料并核对管辖信息",),
        )

    def dispatch_trigger_fields(self) -> frozenset[str]:
        return frozenset({"confirmed_facts", "sufficiency", "evidence_ids"})


class PlaceholderScenarioPack:
    """仅用于验证 Runtime 与具体法律场景解耦的极简场景。"""

    scenario_id = "placeholder-v0.1"
    _topic = FactKeySpec(
        key="topic",
        layer="intake",
        required=True,
        description="请简要说明需要处理的事项？",
    )

    def required_fact_keys(self, layer: FactLayer) -> list[FactKeySpec]:
        return [self._topic] if layer == "intake" else []

    def party_labels(self, facts: dict[str, str]) -> PartyLabels:
        return PartyLabels(self_label="用户", counterparty_label="对方")

    def retrieval_query_prefix(self) -> str:
        return "一般事项处理"

    def claim_items(self) -> list[ClaimItemSpec]:
        return []

    def is_claim_item_applicable(
        self, item_key: str, facts: dict[str, str]
    ) -> Literal["applicable", "not_applicable", "uncertain"]:
        raise ValueError(f"unknown claim item: {item_key}")

    def is_out_of_scope(self, facts: dict[str, str]) -> bool:
        return False

    def extract_facts(self, text: str, existing_facts: dict[str, str]) -> dict[str, str]:
        if "topic" in existing_facts or not text.strip():
            return {}
        return {"topic": text.strip()[:500]}

    def action_templates(self, facts: dict[str, str]) -> ActionTemplateSpec:
        return ActionTemplateSpec(
            condition_key="placeholder",
            materials=("整理与事项直接相关的现有材料",),
            low_cost_communication=("先通过可留痕方式确认事实和对方意见",),
            formal_notice=("需要时整理书面说明要点",),
            other_remedies=("根据事项类型确认可用的后续处理渠道",),
        )

    def dispatch_trigger_fields(self) -> frozenset[str]:
        return frozenset({"confirmed_facts", "sufficiency"})


# 与需求文档中的中文名称对应；两者指向同一实现，避免产生两套规则。
DepositDisputeScenarioPack = RentalDepositScenarioPack


__all__ = [
    "ActionTemplateSpec",
    "ClaimItemSpec",
    "DepositDisputeScenarioPack",
    "FactKeySpec",
    "FactLayer",
    "PlaceholderScenarioPack",
    "PartyLabels",
    "RentalDepositScenarioPack",
    "ScenarioPack",
]
