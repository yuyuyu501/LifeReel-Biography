"""Bounded, schema-validated memory calls. Never log private model output."""

import json
import logging
import re
import time
from typing import Annotated, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.billing.usage import current_context
from lifereel_api.modules.memory.recovery import check_call_budget
from lifereel_api.providers.openai_compatible import OpenAICompatibleClient

logger = logging.getLogger(__name__)
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Output(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class Claim(Output):
    claim_text: Text
    claim_type: Literal["recollection", "event", "relationship", "place", "time"]
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)


class Entity(Output):
    name: Text
    normalized_name: Text
    entity_type: Literal["person", "place", "organization"]
    relationship: Text
    source_claim_ids: list[Text] = Field(min_length=1)


class Anchor(Output):
    year: int | None = Field(ge=1800, le=2200)
    time_text: Text
    event_text: Text
    precision: Literal["year", "relative", "approximate"]
    source_claim_id: Text


class Conflict(Output):
    conflict_key: Text
    description: Text
    claim_ids: list[Text] = Field(min_length=2)


class Correction(Output):
    """Event-level replacement: never discard other facts in a source claim."""

    old_timeline_index: int = Field(ge=0)
    new_timeline_index: int = Field(ge=0)
    evidence_quote: Text
    conflict_keys: list[Text] = Field(default_factory=list)


class Structure(Output):
    entities: list[Entity]
    timeline: list[Anchor]
    conflicts: list[Conflict]
    corrections: list[Correction] = Field(default_factory=list)


class Biography(Output):
    biography: Text = Field(max_length=260)


SCHEMAS = {"claim": Claim, "graph": Structure, "biography": Biography}


def validate(stage, result, user):
    parsed = SCHEMAS[stage].model_validate(result).model_dump()
    if stage == "graph":
        sources = json.loads(user)["claims"]
        allowed = {item["claim_id"] for item in sources}
        for i, item in enumerate(parsed["entities"]):
            if not set(item["source_claim_ids"]) <= allowed:
                raise ValueError(f"entities.{i}.source_claim_ids: unknown_source")
        for i, item in enumerate(parsed["timeline"]):
            if item["source_claim_id"] not in allowed:
                raise ValueError(f"timeline.{i}.source_claim_id: unknown_source")
        for i, item in enumerate(parsed["conflicts"]):
            ids = set(item["claim_ids"])
            if len(ids) < 2 or not ids <= allowed:
                raise ValueError(f"conflicts.{i}.claim_ids: invalid_sources")
        removed = set()
        by_id = {item["claim_id"]: item for item in sources}
        order = {item["claim_id"]: i for i, item in enumerate(sources)}
        for i, correction in enumerate(parsed["corrections"]):
            old_index, new_index = (correction[k] for k in (
                "old_timeline_index", "new_timeline_index",
            ))
            if (max(old_index, new_index) >= len(parsed["timeline"])
                    or old_index == new_index or old_index in removed):
                raise ValueError(f"corrections.{i}: invalid_event_reference")
            old, new = (parsed["timeline"][j] for j in (old_index, new_index))
            old_id, new_id = old["source_claim_id"], new["source_claim_id"]
            source = by_id[new_id]
            quote = correction["evidence_quote"]
            evidence = source.get("source_quote") or source.get("claim_text", "")
            if (order[new_id] <= order[old_id]
                    or source.get("chapter_id") != by_id[old_id].get("chapter_id")
                    or quote not in evidence
                    or not re.search(r"更正|纠正|说错|记错|不是.{0,24}(?:而是|是)|应为|改为", quote)
                    or re.search(r"可能|也许|大概|不确定|记不清|或许|好像", quote)):
                raise ValueError(f"corrections.{i}: explicit_correction_required")
            # Both competing dates must occur in the cited correction, rather
            # than allowing an unrelated 'I was wrong' to remove an event.
            if old["year"] is not None and new["year"] is not None:
                if any(str(anchor["year"]) not in quote for anchor in (old, new)):
                    raise ValueError(f"corrections.{i}: correction_dates_required")
            removed.add(old_index)
            keys = set(correction["conflict_keys"])
            matches = [c for c in parsed["conflicts"] if c["conflict_key"] in keys
                       and set(c["claim_ids"]) == {old_id, new_id}]
            if {c["conflict_key"] for c in matches} != keys:
                raise ValueError(f"corrections.{i}: invalid_conflict_reference")
            if not matches:
                matches = [{"conflict_key": f"correction:{old_id}:{new_id}",
                            "description": "用户已明确更正：" + quote,
                            "claim_ids": [old_id, new_id]}]
                parsed["conflicts"].extend(matches)
            for conflict in matches:
                conflict["status"] = "resolved"
        parsed["timeline"] = [item for i, item in enumerate(parsed["timeline"]) if i not in removed]
    return parsed


class MemoryClient(OpenAICompatibleClient):
    def __init__(self, *args, stage, **kwargs):
        kwargs.setdefault("task", "memory")
        super().__init__(*args, **kwargs)
        self.stage = stage

    def chat_json(self, system, user):
        schema = json.dumps(SCHEMAS[self.stage].model_json_schema(), ensure_ascii=False)
        instructions = (
            system + "\n以以下 JSON Schema 为准。枚举字段只选一个值，不能输出竖线连接的选项。"
            "全部字段均需符合指定类型。不能添加事实。\n" + schema
        )
        correction = ""
        # Initial call plus ONE correction or safe transport retry, never nested retries.
        for attempt in range(2):
            provider_diagnostic = {}
            try:
                check_call_budget()
                result = super().chat_json(instructions + correction, user)
                return validate(self.stage, result, user)
            except (ValidationError, json.JSONDecodeError, ValueError) as exc:
                provider_diagnostic = getattr(exc, "diagnostic", {})
                if isinstance(exc, ValidationError):
                    reason = "; ".join(
                        f"{'.'.join(map(str, e['loc']))}: {e['type']}"
                        for e in exc.errors(include_input=False, include_context=False)[:8]
                    )
                elif isinstance(exc, json.JSONDecodeError):
                    reason = f"json: invalid_json at {exc.pos}"
                else:
                    reason = str(exc)[:400]
                code = ErrorCode.MEMORY_LLM_RESPONSE_INVALID
                correction = (
                    "\n上次返回未通过格式校验："
                    + reason
                    + "。请重新依据原始输入生成符合 Schema 的完整 JSON；不要解释，不要臆造。"
                )
                retryable = True
            except ApiError:
                raise
            except Exception as exc:
                provider_diagnostic = getattr(exc, "diagnostic", {})
                reason = type(exc).__name__
                code = ErrorCode.MEMORY_LLM_REQUEST_FAILED
                # No timeout is retried automatically, including connect/write/pool timeouts.
                retryable = isinstance(exc, httpx.ConnectError) or (
                    isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429
                )
                if retryable and attempt == 0:
                    time.sleep(1)
            context = current_context()
            diagnostic = {
                **provider_diagnostic, "stage": self.stage, "attempt": attempt + 1,
                "reason": reason,
            }
            logger.warning(
                "memory.validation workflow=%s diagnostic=%s",
                context[2] if context else None,
                json.dumps(diagnostic),
            )
            if attempt == 1 or not retryable:
                error = ApiError(502, code)
                error.diagnostic = diagnostic
                raise error
        raise AssertionError("unreachable")
