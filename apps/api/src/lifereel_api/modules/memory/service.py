from __future__ import annotations

import json
import re
from uuid import UUID

from fastapi import status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from lifereel_api.core.config import get_settings
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.billing.usage import track_usage
from lifereel_api.modules.evidence.models import EvidenceObservation, SourceAsset
from lifereel_api.modules.identity.models import Person
from lifereel_api.modules.interview.models import InterviewRound, InterviewSession
from lifereel_api.modules.memory import recovery
from lifereel_api.modules.memory.models import (
    MemoryClaim,
    MemoryConflict,
    MemoryEntity,
    TimelineAnchor,
)
from lifereel_api.modules.memory.schemas import (
    MemoryCompileRequest,
    MemoryGraphEdge,
    MemoryGraphNode,
    MemoryGraphRead,
    MemoryOverview,
)
from lifereel_api.modules.memory.structured import MemoryClient

YEAR_PATTERN = re.compile(r"(?<!\d)((?:18|19|20)\d{2})年?")
BIRTH_SENTENCE_SPLIT_PATTERN = re.compile(r"[。！？!?；;，,\n]+")
NON_SUBJECT_BIRTH_PATTERN = re.compile(
    r"(?:孩子|子女|儿子|女儿|宝宝|长子|长女|次子|次女|孙子|孙女|外孙|外孙女|侄子|侄女).{0,8}出生"
)
ENTITY_WORDS = {
    "父亲": "person",
    "母亲": "person",
    "爸爸": "person",
    "妈妈": "person",
    "爷爷": "person",
    "奶奶": "person",
    "外公": "person",
    "外婆": "person",
    "哥哥": "person",
    "姐姐": "person",
    "弟弟": "person",
    "妹妹": "person",
    "老师": "person",
    "学校": "place",
    "村口": "place",
    "家乡": "place",
    "工厂": "organization",
    "部队": "organization",
}

RELATIONSHIP_LABELS = {
    "父亲": "父亲",
    "爸爸": "父亲",
    "母亲": "母亲",
    "妈妈": "母亲",
    "爷爷": "祖父",
    "奶奶": "祖母",
    "外公": "外祖父",
    "外婆": "外祖母",
    "哥哥": "兄长",
    "姐姐": "姐姐",
    "弟弟": "弟弟",
    "妹妹": "妹妹",
    "老师": "老师",
    "学校": "求学地点",
    "村口": "生活地点",
    "家乡": "故乡",
    "工厂": "工作单位",
    "部队": "服役单位",
}


def _extract_claim(text: str, source_kind: str) -> tuple[str, str, float, str, str | None]:
    settings = get_settings()
    model = settings.model_for("memory")
    if settings.llm_provider == "mock":
        return text, "recollection", 1.0, "rule", None
    if settings.llm_provider != "openai-compatible":
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorCode.MEMORY_LLM_CONFIGURATION_INCOMPLETE,
        )
    client = MemoryClient(
        settings.openai_compatible_base_url or "",
        settings.openai_compatible_api_key or "",
        model, stage="claim",
    )
    if not client.capabilities().configured:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorCode.MEMORY_LLM_CONFIGURATION_INCOMPLETE,
        )
    try:
        result = client.chat_json(
            "你是口述史证据整理员。只能根据输入原文整理一条可核对的记忆陈述，不得补充输入中"
            "没有的事实。保留不确定语气。只输出 JSON："
            '{"claim_text":"...","claim_type":"recollection|event|relationship|place|time",'
            '"confidence":0.0}。',
            json.dumps(
                {"source_kind": source_kind, "source_text": text[:20000]}, ensure_ascii=False
            ),
        )
    except json.JSONDecodeError as exc:
        raise ApiError(
            status.HTTP_502_BAD_GATEWAY,
            ErrorCode.MEMORY_LLM_RESPONSE_INVALID,
        ) from exc
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(
            status.HTTP_502_BAD_GATEWAY,
            ErrorCode.MEMORY_LLM_REQUEST_FAILED,
        ) from exc
    if not isinstance(result, dict):
        raise ApiError(status.HTTP_502_BAD_GATEWAY, ErrorCode.MEMORY_LLM_RESPONSE_INVALID)
    try:
        claim_text = str(result.get("claim_text") or "").strip()
        claim_type = str(result.get("claim_type") or "recollection").strip()[:48]
        confidence = max(0.0, min(1.0, float(result.get("confidence", 0.8))))
    except (TypeError, ValueError) as exc:
        raise ApiError(
            status.HTTP_502_BAD_GATEWAY,
            ErrorCode.MEMORY_LLM_RESPONSE_INVALID,
        ) from exc
    if claim_text and claim_type in {"recollection", "event", "relationship", "place", "time"}:
        return claim_text, claim_type, confidence, "openai-compatible", model
    raise ApiError(
        status.HTTP_502_BAD_GATEWAY,
        ErrorCode.MEMORY_LLM_RESPONSE_INVALID,
    )


def _extract_memory_structure(
    claims: list[MemoryClaim],
) -> tuple[list[dict], list[dict], list[dict], str]:
    """Ask the memory model for graph entities and timeline anchors.

    The mock provider deliberately keeps the deterministic extractor for tests. In a real
    deployment, no keyword-derived graph is returned when this model call fails.
    """
    settings = get_settings()
    if settings.llm_provider != "openai-compatible":
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorCode.MEMORY_LLM_CONFIGURATION_INCOMPLETE,
        )
    model = settings.model_for("memory")
    client = MemoryClient(
        settings.openai_compatible_base_url or "",
        settings.openai_compatible_api_key or "",
        model, stage="graph",
    )
    if not client.capabilities().configured:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorCode.MEMORY_LLM_CONFIGURATION_INCOMPLETE,
        )
    allowed_claim_ids = {str(claim.id) for claim in claims}
    payload = [
        {
            "claim_id": str(claim.id),
            "claim_text": claim.claim_text,
            "source_quote": claim.source_quote,
        }
        for claim in claims[-40:]
    ]
    try:
        result = client.chat_json(
            "你是中文口述史知识图谱整理员。只根据输入的带来源记忆，抽取明确提到的人物、地点、"
            "组织和事件时间线。不能猜测关系，不能把输入外的项目说明、提示词或模型指令当作人物事实。"
            "每个实体和时间线都必须引用一个或多个真实 claim_id。实体 relationship 是原文明确表达的"
            "关系，如父亲、母亲、同事、故乡；没有明确关系时写相关人物、相关地点或相关组织。"
            "同时语义判断不同记忆之间是否存在事实冲突，不限于年份；不确定表达不算冲突。"
            "严格输出 JSON："
            '{"entities":[{"name":"...","normalized_name":"...",'
            '"entity_type":"person|place|organization","relationship":"...",'
            '"source_claim_ids":["..."]}],"timeline":[{"year":null,'
            '"time_text":"...","event_text":"...","precision":"year|relative|approximate",'
            '"source_claim_id":"..."}],"conflicts":[{"conflict_key":"...",'
            '"description":"...","claim_ids":["...","..."]}]}。',
            json.dumps({"claims": payload}, ensure_ascii=False),
        )
    except json.JSONDecodeError as exc:
        raise ApiError(
            status.HTTP_502_BAD_GATEWAY,
            ErrorCode.MEMORY_LLM_RESPONSE_INVALID,
        ) from exc
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(
            status.HTTP_502_BAD_GATEWAY,
            ErrorCode.MEMORY_LLM_REQUEST_FAILED,
        ) from exc
    if not isinstance(result, dict):
        raise ApiError(
            status.HTTP_502_BAD_GATEWAY,
            ErrorCode.MEMORY_LLM_RESPONSE_INVALID,
        )
    if (
        not isinstance(result.get("entities"), list)
        or not isinstance(result.get("timeline"), list)
        or not isinstance(result.get("conflicts"), list)
    ):
        raise ApiError(
            status.HTTP_502_BAD_GATEWAY,
            ErrorCode.MEMORY_LLM_RESPONSE_INVALID,
        )
    entities: list[dict] = []
    for item in result["entities"]:
        if not isinstance(item, dict):
            raise ApiError(status.HTTP_502_BAD_GATEWAY, ErrorCode.MEMORY_LLM_RESPONSE_INVALID)
        name = str(item.get("name") or "").strip()[:180]
        normalized_name = str(item.get("normalized_name") or name).strip()[:180]
        entity_type = str(item.get("entity_type") or "").strip()
        relationship = str(item.get("relationship") or "").strip()[:120]
        source_ids = list(
            dict.fromkeys(
                str(value)
                for value in item.get("source_claim_ids", [])
                if str(value) in allowed_claim_ids
            )
        )
        if (
            not name
            or not normalized_name
            or entity_type not in {"person", "place", "organization"}
        ):
            raise ApiError(status.HTTP_502_BAD_GATEWAY, ErrorCode.MEMORY_LLM_RESPONSE_INVALID)
        if not relationship or not source_ids:
            raise ApiError(status.HTTP_502_BAD_GATEWAY, ErrorCode.MEMORY_LLM_RESPONSE_INVALID)
        entities.append(
            {
                "name": name,
                "normalized_name": normalized_name,
                "entity_type": entity_type,
                "relationship": relationship,
                "source_claim_ids": source_ids,
            }
        )
    timeline: list[dict] = []
    for item in result["timeline"]:
        if not isinstance(item, dict):
            raise ApiError(status.HTTP_502_BAD_GATEWAY, ErrorCode.MEMORY_LLM_RESPONSE_INVALID)
        source_claim_id = str(item.get("source_claim_id") or "")
        event_text = str(item.get("event_text") or "").strip()
        time_text = str(item.get("time_text") or "").strip()[:120]
        precision = str(item.get("precision") or "approximate").strip()
        year = item.get("year")
        if source_claim_id not in allowed_claim_ids or not event_text or not time_text:
            raise ApiError(status.HTTP_502_BAD_GATEWAY, ErrorCode.MEMORY_LLM_RESPONSE_INVALID)
        if year is not None and (not isinstance(year, int) or year < 1800 or year > 2200):
            raise ApiError(status.HTTP_502_BAD_GATEWAY, ErrorCode.MEMORY_LLM_RESPONSE_INVALID)
        if precision not in {"year", "relative", "approximate"}:
            raise ApiError(status.HTTP_502_BAD_GATEWAY, ErrorCode.MEMORY_LLM_RESPONSE_INVALID)
        timeline.append(
            {
                "year": year,
                "time_text": time_text,
                "event_text": event_text,
                "precision": precision,
                "source_claim_id": source_claim_id,
            }
        )
    conflicts: list[dict] = []
    for item in result["conflicts"]:
        if not isinstance(item, dict):
            raise ApiError(status.HTTP_502_BAD_GATEWAY, ErrorCode.MEMORY_LLM_RESPONSE_INVALID)
        conflict_key = str(item.get("conflict_key") or "").strip()[:120]
        description = str(item.get("description") or "").strip()[:1000]
        claim_ids = list(
            dict.fromkeys(
                str(value) for value in item.get("claim_ids", []) if str(value) in allowed_claim_ids
            )
        )
        if not conflict_key or not description or len(claim_ids) < 2:
            raise ApiError(status.HTTP_502_BAD_GATEWAY, ErrorCode.MEMORY_LLM_RESPONSE_INVALID)
        conflicts.append(
            {
                "conflict_key": conflict_key,
                "description": description,
                "claim_ids": claim_ids,
            }
        )
    return entities, timeline, conflicts, model


def _generate_biography(claims: list[MemoryClaim]) -> str:
    settings = get_settings()
    if settings.llm_provider == "mock":
        return ""
    if settings.llm_provider != "openai-compatible":
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE, ErrorCode.MEMORY_LLM_CONFIGURATION_INCOMPLETE
        )
    model = settings.model_for("memory")
    client = MemoryClient(
        settings.openai_compatible_base_url or "",
        settings.openai_compatible_api_key or "",
        model, stage="biography",
    )
    if not client.capabilities().configured:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE, ErrorCode.MEMORY_LLM_CONFIGURATION_INCOMPLETE
        )
    try:
        result = client.chat_json(
            "你是中文口述史编辑。请仅根据带来源的记忆，生成一段不超过 260 字的第三人称人物小传。"
            '不得补充事实，不得提及素材、模型、项目或输入格式。只输出 JSON：{"biography":"..."}。',
            json.dumps(
                [
                    {"claim_text": claim.claim_text, "source_quote": claim.source_quote}
                    for claim in claims[-20:]
                ],
                ensure_ascii=False,
            ),
        )
    except json.JSONDecodeError as exc:
        raise ApiError(
            status.HTTP_502_BAD_GATEWAY,
            ErrorCode.MEMORY_LLM_RESPONSE_INVALID,
        ) from exc
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(status.HTTP_502_BAD_GATEWAY, ErrorCode.MEMORY_LLM_REQUEST_FAILED) from exc
    if not isinstance(result, dict):
        raise ApiError(status.HTTP_502_BAD_GATEWAY, ErrorCode.MEMORY_LLM_RESPONSE_INVALID)
    biography = str(result.get("biography") or "").strip()
    if not biography or len(biography) > 260:
        raise ApiError(status.HTTP_502_BAD_GATEWAY, ErrorCode.MEMORY_LLM_RESPONSE_INVALID)
    return biography


def list_claims(db: Session, tenant_id: UUID, subject_id: UUID | None = None) -> list[MemoryClaim]:
    statement = select(MemoryClaim).where(MemoryClaim.tenant_id == tenant_id)
    if subject_id:
        statement = statement.where(MemoryClaim.subject_id == subject_id)
    return list(db.scalars(statement.order_by(MemoryClaim.created_at.desc())))


def _compile_entities_and_timeline_rules(
    db: Session, tenant_id: UUID, claims: list[MemoryClaim]
) -> None:
    subject_ids = {claim.subject_id for claim in claims}
    existing_entities = (
        list(
            db.scalars(
                select(MemoryEntity).where(
                    MemoryEntity.tenant_id == tenant_id,
                    MemoryEntity.subject_id.in_(subject_ids),
                )
            )
        )
        if subject_ids
        else []
    )
    entities_by_key = {
        (entity.subject_id, entity.entity_type, entity.normalized_name): entity
        for entity in existing_entities
    }

    for claim in claims:
        for name, entity_type in ENTITY_WORDS.items():
            if name not in claim.claim_text:
                continue
            entity_key = (claim.subject_id, entity_type, name)
            entity = entities_by_key.get(entity_key)
            if entity is None:
                entity = MemoryEntity(
                    tenant_id=tenant_id,
                    subject_id=claim.subject_id,
                    entity_type=entity_type,
                    name=name,
                    normalized_name=name,
                    relationship=RELATIONSHIP_LABELS.get(
                        name,
                        {
                            "person": "相关人物",
                            "place": "相关地点",
                            "organization": "相关组织",
                        }.get(entity_type, "相关记忆"),
                    ),
                    source_claim_ids=[str(claim.id)],
                )
                db.add(entity)
                entities_by_key[entity_key] = entity
            elif str(claim.id) not in entity.source_claim_ids:
                entity.source_claim_ids = [*entity.source_claim_ids, str(claim.id)]

        existing_anchor = db.scalar(
            select(TimelineAnchor.id).where(TimelineAnchor.claim_id == claim.id)
        )
        if existing_anchor:
            continue
        year_match = YEAR_PATTERN.search(claim.claim_text)
        time_words = [
            word
            for word in ("小时候", "后来", "结婚后", "退休后", "现在")
            if word in claim.claim_text
        ]
        if year_match or time_words:
            time_text = year_match.group(0) if year_match else time_words[0]
            db.add(
                TimelineAnchor(
                    tenant_id=tenant_id,
                    subject_id=claim.subject_id,
                    claim_id=claim.id,
                    year=int(year_match.group(1)) if year_match else None,
                    time_text=time_text,
                    event_text=claim.claim_text,
                    precision="year" if year_match else "relative",
                )
            )


def _compile_entities_and_timeline_ai(
    db: Session,
    tenant_id: UUID,
    claims: list[MemoryClaim],
) -> None:
    entities, timeline, conflicts, _ = _extract_memory_structure(claims)
    subject_ids = {claim.subject_id for claim in claims}
    if len(subject_ids) != 1:
        raise ApiError(
            status.HTTP_502_BAD_GATEWAY,
            ErrorCode.MEMORY_LLM_RESPONSE_INVALID,
        )
    subject_id = next(iter(subject_ids))
    claims_by_id = {str(claim.id): claim for claim in claims}

    # The model returns a complete snapshot for one person. Replacing the old snapshot
    # also removes stale entities and events when later interview turns correct a memory.
    db.execute(
        delete(MemoryEntity).where(
            MemoryEntity.tenant_id == tenant_id,
            MemoryEntity.subject_id == subject_id,
        )
    )
    db.execute(
        delete(TimelineAnchor).where(
            TimelineAnchor.tenant_id == tenant_id,
            TimelineAnchor.subject_id == subject_id,
        )
    )
    db.execute(
        delete(MemoryConflict).where(
            MemoryConflict.tenant_id == tenant_id,
            MemoryConflict.subject_id == subject_id,
        )
    )
    merged_entities: dict[tuple[str, str], dict] = {}
    for item in entities:
        source_claim_ids = item["source_claim_ids"]
        if any(claims_by_id[claim_id].subject_id != subject_id for claim_id in source_claim_ids):
            raise ApiError(
                status.HTTP_502_BAD_GATEWAY,
                ErrorCode.MEMORY_LLM_RESPONSE_INVALID,
            )
        key = (item["entity_type"], item["normalized_name"])
        existing = merged_entities.get(key)
        if existing is not None:
            existing["source_claim_ids"] = list(
                dict.fromkeys(
                    [
                        *existing["source_claim_ids"],
                        *source_claim_ids,
                    ]
                )
            )
            continue
        merged_entities[key] = {**item, "source_claim_ids": source_claim_ids}

    for item in merged_entities.values():
        db.add(
            MemoryEntity(
                tenant_id=tenant_id,
                subject_id=subject_id,
                entity_type=item["entity_type"],
                name=item["name"],
                normalized_name=item["normalized_name"],
                relationship=item["relationship"],
                source_claim_ids=item["source_claim_ids"],
            )
        )

    for item in timeline:
        claim_id = item["source_claim_id"]
        claim = claims_by_id.get(claim_id)
        if claim is None:
            continue
        db.add(
            TimelineAnchor(
                tenant_id=tenant_id,
                subject_id=claim.subject_id,
                claim_id=claim.id,
                year=item["year"],
                time_text=item["time_text"],
                event_text=item["event_text"],
                precision=item["precision"],
            )
        )

    for item in conflicts:
        if any(claims_by_id[claim_id].subject_id != subject_id for claim_id in item["claim_ids"]):
            raise ApiError(
                status.HTTP_502_BAD_GATEWAY,
                ErrorCode.MEMORY_LLM_RESPONSE_INVALID,
            )
        db.add(
            MemoryConflict(
                tenant_id=tenant_id,
                subject_id=subject_id,
                claim_ids=item["claim_ids"],
                conflict_key=item["conflict_key"],
                description=item["description"],
            )
        )


def _detect_year_conflicts(db: Session, tenant_id: UUID, subject_ids: set[UUID]) -> None:
    for subject_id in subject_ids:
        birth_claims = list(
            db.scalars(
                select(MemoryClaim).where(
                    MemoryClaim.tenant_id == tenant_id,
                    MemoryClaim.subject_id == subject_id,
                    MemoryClaim.claim_text.contains("出生"),
                )
            )
        )
        years: dict[int, list[MemoryClaim]] = {}
        for claim in birth_claims:
            for sentence in BIRTH_SENTENCE_SPLIT_PATTERN.split(claim.claim_text):
                if "出生" not in sentence or NON_SUBJECT_BIRTH_PATTERN.search(sentence):
                    continue
                for value in YEAR_PATTERN.findall(sentence):
                    years.setdefault(int(value), []).append(claim)
        existing = db.scalar(
            select(MemoryConflict).where(
                MemoryConflict.tenant_id == tenant_id,
                MemoryConflict.subject_id == subject_id,
                MemoryConflict.conflict_key == "birth_year",
                MemoryConflict.status == "open",
            )
        )
        if len(years) < 2:
            if existing:
                db.delete(existing)
            continue
        claim_ids = [str(claim.id) for items in years.values() for claim in items]
        description = f"采访中出现多个出生年份：{', '.join(map(str, sorted(years)))}"
        if existing:
            existing.claim_ids = claim_ids
            existing.description = description
        else:
            db.add(
                MemoryConflict(
                    tenant_id=tenant_id,
                    subject_id=subject_id,
                    claim_ids=claim_ids,
                    conflict_key="birth_year",
                    description=description,
                )
            )


@track_usage("memory")
def compile_memories(
    db: Session, tenant_id: UUID, payload: MemoryCompileRequest
) -> tuple[int, int, list[MemoryClaim]]:
    session_statement = select(InterviewSession).where(InterviewSession.tenant_id == tenant_id)
    if payload.interview_session_id:
        session_statement = session_statement.where(
            InterviewSession.id == payload.interview_session_id
        )
    if payload.subject_id:
        session_statement = session_statement.where(
            InterviewSession.subject_id == payload.subject_id
        )

    sessions = list(db.scalars(session_statement))
    if payload.interview_session_id and not sessions:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.INTERVIEW_NOT_FOUND)

    session_ids = [item.id for item in sessions]
    rounds = (
        list(
            db.scalars(
                select(InterviewRound)
                .where(
                    InterviewRound.tenant_id == tenant_id,
                    InterviewRound.session_id.in_(session_ids),
                    InterviewRound.answer_text.is_not(None),
                )
                .order_by(InterviewRound.created_at)
            )
        )
        if session_ids
        else []
    )
    round_ids = [item.id for item in rounds]
    existing_round_ids = (
        set(
            db.scalars(
                select(MemoryClaim.source_round_id).where(
                    MemoryClaim.tenant_id == tenant_id,
                    MemoryClaim.source_round_id.in_(round_ids),
                )
            )
        )
        if round_ids
        else set()
    )

    observation_statement = (
        select(EvidenceObservation, SourceAsset)
        .join(SourceAsset, SourceAsset.id == EvidenceObservation.source_asset_id)
        .where(
            EvidenceObservation.tenant_id == tenant_id,
            EvidenceObservation.confidence > 0,
        )
    )
    if payload.interview_session_id:
        observation_statement = observation_statement.where(
            SourceAsset.interview_session_id == payload.interview_session_id
        )
    if payload.subject_id:
        observation_statement = observation_statement.where(
            EvidenceObservation.subject_id == payload.subject_id
        )
    linked_round_asset_ids = {item.source_asset_id for item in rounds if item.source_asset_id}
    latest_observations: dict[UUID, tuple[EvidenceObservation, SourceAsset]] = {}
    for observation, asset in db.execute(observation_statement).all():
        if asset.id in linked_round_asset_ids:
            continue
        current = latest_observations.get(asset.id)
        if current is None or observation.version_number > current[0].version_number:
            latest_observations[asset.id] = (observation, asset)
    observations = list(latest_observations.values())
    observation_ids = [item.id for item, _ in observations]
    existing_observation_ids = (
        set(
            db.scalars(
                select(MemoryClaim.source_observation_id).where(
                    MemoryClaim.tenant_id == tenant_id,
                    MemoryClaim.source_observation_id.in_(observation_ids),
                )
            )
        )
        if observation_ids
        else set()
    )
    sessions_by_id = {item.id: item for item in sessions}
    workflow = recovery.current_workflow(db, tenant_id)
    created = 0
    for round_ in rounds:
        if round_.id in existing_round_ids:
            continue
        source_quote = (round_.answer_text or "").strip()
        if not source_quote:
            continue
        session = sessions_by_id[round_.session_id]
        claim_text, claim_type, confidence, provider, model = _extract_claim(
            source_quote, "interview_round"
        )
        db.add(
            MemoryClaim(
                tenant_id=tenant_id,
                subject_id=session.subject_id,
                interview_session_id=session.id,
                source_round_id=round_.id,
                chapter_id=session.chapter_id,
                source_observation_id=None,
                claim_text=claim_text,
                source_quote=source_quote,
                claim_type=claim_type,
                confidence=confidence,
                review_status="unreviewed",
                extraction_provider=provider,
                extraction_model=model,
            )
        )
        created += 1
        if workflow is not None:
            # A valid source claim is durable even if graph/biography later fails.
            db.commit()

    for observation, asset in observations:
        if observation.id in existing_observation_ids:
            continue
        source_quote = observation.text.strip()
        if not source_quote:
            continue
        linked_session = (
            sessions_by_id.get(asset.interview_session_id) if asset.interview_session_id else None
        )
        if linked_session is None and asset.interview_session_id:
            linked_session = db.get(InterviewSession, asset.interview_session_id)
        claim_text, claim_type, confidence, provider, model = _extract_claim(
            source_quote, observation.analysis_kind
        )
        db.add(
            MemoryClaim(
                tenant_id=tenant_id,
                subject_id=observation.subject_id,
                interview_session_id=asset.interview_session_id,
                source_round_id=None,
                source_observation_id=observation.id,
                chapter_id=linked_session.chapter_id if linked_session else None,
                claim_text=claim_text,
                source_quote=source_quote,
                claim_type=claim_type,
                confidence=confidence,
                review_status="unreviewed",
                extraction_provider=provider,
                extraction_model=model,
            )
        )
        created += 1
        if workflow is not None:
            db.commit()
    db.flush()

    claim_statement = select(MemoryClaim).where(MemoryClaim.tenant_id == tenant_id)
    subject_ids = {item.subject_id for item in sessions}
    if payload.subject_id:
        subject_ids.add(payload.subject_id)
    if subject_ids:
        claim_statement = claim_statement.where(MemoryClaim.subject_id.in_(subject_ids))
    elif payload.interview_session_id:
        claim_statement = claim_statement.where(
            MemoryClaim.interview_session_id == payload.interview_session_id
        )
    compiled = list(db.scalars(claim_statement.order_by(MemoryClaim.created_at)))
    settings = get_settings()
    claims_by_subject = {
        subject_id: [claim for claim in compiled if claim.subject_id == subject_id]
        for subject_id in {claim.subject_id for claim in compiled}
    }
    if settings.llm_provider == "mock":
        _compile_entities_and_timeline_rules(db, tenant_id, compiled)
        _detect_year_conflicts(db, tenant_id, {item.subject_id for item in compiled})
    elif settings.llm_provider == "openai-compatible":
        for subject_id, subject_claims in claims_by_subject.items():
            digest = recovery.fingerprint(subject_claims)
            if not recovery.completed(workflow, subject_id, "graph", digest):
                _compile_entities_and_timeline_ai(db, tenant_id, subject_claims)
                recovery.save(db, workflow, subject_id, "graph", digest)
            subject = db.scalar(
                select(Person).where(
                    Person.id == subject_id,
                    Person.tenant_id == tenant_id,
                )
            )
            if subject is not None and not recovery.completed(
                workflow, subject_id, "biography", digest,
            ):
                subject.biography_note = _generate_biography(subject_claims)
                recovery.save(db, workflow, subject_id, "biography", digest)
    else:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorCode.MEMORY_LLM_CONFIGURATION_INCOMPLETE,
        )
    db.commit()
    source_count = len(rounds) + len(observations)
    return created, source_count - created, compiled


def review_claim(db: Session, tenant_id: UUID, claim_id: UUID, review_status: str) -> MemoryClaim:
    if review_status not in {"unreviewed", "verified", "disputed", "private"}:
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, ErrorCode.MEMORY_REVIEW_STATUS_INVALID)
    claim = db.scalar(
        select(MemoryClaim).where(MemoryClaim.id == claim_id, MemoryClaim.tenant_id == tenant_id)
    )
    if claim is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.MEMORY_CLAIM_NOT_FOUND)
    claim.review_status = review_status
    db.commit()
    db.refresh(claim)
    return claim


def memory_overview(db: Session, tenant_id: UUID, subject_id: UUID) -> MemoryOverview:
    claims = list_claims(db, tenant_id, subject_id)
    covered = sorted({item.chapter_id for item in claims if item.chapter_id})
    entity_count = (
        db.scalar(
            select(func.count(MemoryEntity.id)).where(
                MemoryEntity.tenant_id == tenant_id, MemoryEntity.subject_id == subject_id
            )
        )
        or 0
    )
    timeline_count = (
        db.scalar(
            select(func.count(TimelineAnchor.id)).where(
                TimelineAnchor.tenant_id == tenant_id, TimelineAnchor.subject_id == subject_id
            )
        )
        or 0
    )
    conflict_count = (
        db.scalar(
            select(func.count(MemoryConflict.id)).where(
                MemoryConflict.tenant_id == tenant_id,
                MemoryConflict.subject_id == subject_id,
                MemoryConflict.status == "open",
            )
        )
        or 0
    )
    return MemoryOverview(
        claim_count=len(claims),
        reviewed_count=sum(item.review_status == "verified" for item in claims),
        entity_count=entity_count,
        timeline_count=timeline_count,
        open_conflict_count=conflict_count,
        covered_chapter_ids=covered,
        coverage_ratio=round(len(covered) / 11, 3),
    )


def list_entities(db: Session, tenant_id: UUID, subject_id: UUID) -> list[MemoryEntity]:
    return list(
        db.scalars(
            select(MemoryEntity)
            .where(MemoryEntity.tenant_id == tenant_id, MemoryEntity.subject_id == subject_id)
            .order_by(MemoryEntity.entity_type, MemoryEntity.name)
        )
    )


def list_timeline(db: Session, tenant_id: UUID, subject_id: UUID) -> list[TimelineAnchor]:
    return list(
        db.scalars(
            select(TimelineAnchor)
            .where(TimelineAnchor.tenant_id == tenant_id, TimelineAnchor.subject_id == subject_id)
            .order_by(TimelineAnchor.year, TimelineAnchor.created_at)
        )
    )


def list_conflicts(db: Session, tenant_id: UUID, subject_id: UUID) -> list[MemoryConflict]:
    return list(
        db.scalars(
            select(MemoryConflict)
            .where(MemoryConflict.tenant_id == tenant_id, MemoryConflict.subject_id == subject_id)
            .order_by(MemoryConflict.created_at.desc())
        )
    )


def memory_graph(
    db: Session,
    tenant_id: UUID,
    subject_id: UUID,
) -> MemoryGraphRead:
    subject = db.scalar(
        select(Person).where(Person.id == subject_id, Person.tenant_id == tenant_id)
    )
    if subject is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.SUBJECT_NOT_FOUND)

    claims = {
        str(claim.id): claim
        for claim in list_claims(db, tenant_id, subject_id)
        if claim.review_status not in {"disputed", "private"}
    }
    entities = list_entities(db, tenant_id, subject_id)[:24]
    timeline = list_timeline(db, tenant_id, subject_id)[-12:]
    subject_node_id = f"subject:{subject.id}"
    subject_name = subject.preferred_name or subject.display_name
    subject_description = subject.biography_note or next(
        (claim.claim_text[:500] for claim in claims.values()), None
    )
    nodes = [
        MemoryGraphNode(
            id=subject_node_id,
            kind="subject",
            label=subject_name,
            description=subject_description,
            source_claim_ids=[],
        )
    ]
    edges: list[MemoryGraphEdge] = []

    entity_node_ids: dict[UUID, str] = {}
    for entity in entities:
        source_ids = [claim_id for claim_id in entity.source_claim_ids if claim_id in claims]
        if not source_ids:
            continue
        node_id = f"entity:{entity.id}"
        entity_node_ids[entity.id] = node_id
        description = "\n".join(claims[claim_id].claim_text for claim_id in source_ids[:2])
        nodes.append(
            MemoryGraphNode(
                id=node_id,
                kind=entity.entity_type,
                label=entity.name,
                description=description,
                source_claim_ids=source_ids,
            )
        )
        edges.append(
            MemoryGraphEdge(
                id=f"subject-entity:{entity.id}",
                source_id=subject_node_id,
                target_id=node_id,
                relationship=entity.relationship,
                source_claim_ids=source_ids,
            )
        )

    for anchor in timeline:
        claim_id = str(anchor.claim_id)
        if claim_id not in claims:
            continue
        node_id = f"event:{anchor.id}"
        event_label = anchor.event_text.strip()
        if len(event_label) > 22:
            event_label = f"{event_label[:22]}…"
        nodes.append(
            MemoryGraphNode(
                id=node_id,
                kind="event",
                label=event_label,
                description=anchor.event_text,
                time_text=anchor.time_text,
                source_claim_ids=[claim_id],
            )
        )
        edges.append(
            MemoryGraphEdge(
                id=f"subject-event:{anchor.id}",
                source_id=subject_node_id,
                target_id=node_id,
                relationship="经历",
                source_claim_ids=[claim_id],
            )
        )
        for entity in entities:
            if claim_id not in entity.source_claim_ids or entity.id not in entity_node_ids:
                continue
            edges.append(
                MemoryGraphEdge(
                    id=f"entity-event:{entity.id}:{anchor.id}",
                    source_id=entity_node_ids[entity.id],
                    target_id=node_id,
                    relationship="相关事件",
                    source_claim_ids=[claim_id],
                )
            )

    return MemoryGraphRead(subject_id=subject.id, nodes=nodes, edges=edges)
