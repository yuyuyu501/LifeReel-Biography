from __future__ import annotations

import json
from uuid import UUID

from fastapi import status
from sqlalchemy.orm import Session

from lifereel_api.core.config import get_settings
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.interview.chapter_prompts import get_chapter_prompt_profile
from lifereel_api.modules.interview.models import Chapter, InterviewRound
from lifereel_api.modules.memory.facts import fact_evidence, fact_text
from lifereel_api.modules.memory.models import MemoryClaim
from lifereel_api.providers.openai_compatible import OpenAICompatibleClient


def _rule_missing_topics(
    claims: list[MemoryClaim],
    rounds: list[InterviewRound],
    chapter: Chapter | None,
) -> list[str]:
    text = "\n".join(fact_text(claim) for claim in claims)
    intents = {item.question_intent for item in rounds if item.answer_text}
    generic_checks = [
        ("时间", any(char.isdigit() for char in text) or "timeline" in intents),
        ("地点", any(word in text for word in ("在", "村", "镇", "县", "市", "学校", "家乡"))),
        ("关键人物", any(word in text for word in ("父", "母", "老师", "朋友", "同学", "家人"))),
        ("事情经过", len(text) >= 80 or "event" in intents),
        (
            "当时感受",
            any(word in text for word in ("觉得", "感到", "高兴", "难过", "害怕", "温暖")),
        ),
        ("后来影响", any(word in text for word in ("后来", "影响", "从此", "因此", "直到现在"))),
    ]
    profile = get_chapter_prompt_profile(chapter)
    missing_required = [
        topic
        for topic in profile["required_topics"]
        if not any(keyword in text for keyword in _topic_terms(topic, profile["keywords"]))
    ]
    missing_generic = [topic for topic, covered in generic_checks if not covered]
    return list(dict.fromkeys([*missing_required, *missing_generic]))[:4]


def _validate_assessment(result) -> dict:
    if not isinstance(result, dict):
        raise ValueError("ASSESSMENT_OBJECT_REQUIRED")
    raw_topics = result.get("missing_topics")
    if not isinstance(raw_topics, list) or any(not isinstance(item, str) for item in raw_topics):
        raise ValueError("ASSESSMENT_TOPICS_INVALID")
    topics = list(dict.fromkeys(item.strip() for item in raw_topics if item.strip()))
    if len(topics) > 4 or any(len(item) > 120 for item in topics):
        raise ValueError("ASSESSMENT_TOPICS_LIMIT")
    ready, reason = result.get("ready_for_script"), result.get("reason")
    if type(ready) is not bool:
        raise ValueError("ASSESSMENT_READINESS_INVALID")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("ASSESSMENT_REASON_REQUIRED")
    return {"missing_topics": topics, "ready_for_script": ready, "reason": reason.strip()[:500]}


def assess_chapter(
    db: Session,
    tenant_id: UUID,
    claims: list[MemoryClaim],
    rounds: list[InterviewRound],
    chapter: Chapter | None,
) -> dict:
    settings = get_settings()
    if settings.llm_provider == "mock":
        return {
            "missing_topics": _rule_missing_topics(claims, rounds, chapter),
            "ready_for_script": bool(claims),
            "reason": "mock assessment",
        }
    if settings.llm_provider != "openai-compatible":
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorCode.INTERVIEW_LLM_CONFIGURATION_INCOMPLETE,
        )

    profile = get_chapter_prompt_profile(chapter)
    client = OpenAICompatibleClient(
        settings.openai_compatible_base_url or "",
        settings.openai_compatible_api_key or "",
        settings.model_for("interview"),
    )
    if not client.capabilities().configured:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorCode.INTERVIEW_LLM_CONFIGURATION_INCOMPLETE,
        )
    context = {
        "chapter": profile,
        "claims": [
            fact_evidence(claim)
            for claim in claims[-40:]
        ],
        "answered_rounds": [
            {"question": round_.question_text, "answer": round_.answer_text}
            for round_ in rounds[-12:]
            if round_.answer_text
        ],
    }
    allowed_topics = [
        *profile["required_topics"],
        "时间",
        "地点",
        "关键人物",
        "事情经过",
        "当时感受",
        "后来影响",
    ]
    system = (
        "你是中文口述史采访规划师。请根据当前章节画像、已确认记忆和完整对话，"
        "语义判断当前章节还缺少哪些最重要的信息。只输出 JSON，missing_topics 必须是"
        "字符串数组，最多 4 项，每项不超过120字；allowed_topics仅供参考，允许使用"
        "本章具体缺失细节的自然语言描述，不必逐字匹配词表。不得根据关键词匹配"
        "或字数猜测，不得把其他章节内容当作当前章节缺口。还要语义判断现有证据能否"
        "支撑一段不虚构事实、包含旁白和画面描述的本章短剧本。只提供姓名、问候、"
        "拒绝回答或离题内容时，ready_for_script 为 false，继续采访，不强行编剧。"
        "已有具体生活细节可成稿时可以为 true，不要求所有主题完整，也不按记忆条数判断。"
        "用户要求重写剧本时，应依据已有claims判断是否可生成，不要求用户重复讲述。"
        "评估目标是含剧情、分镜、人物对话（可只有旁白）、场景描述的四部分剧本。"
        "reason 简要说明依据。格式："
        '{"missing_topics":["..."],"ready_for_script":false,"reason":"..."}。'
    )
    issues = []
    for attempt in range(2):
        retry_hint = (
            "\n上次返回未通过格式校验，原因码：" + issues[-1]
            + "。请根据原始资料重新输出完整JSON；信息不足时正常返回false，不要强行编剧。"
            if attempt else ""
        )
        try:
            result = client.chat_json(
                system + retry_hint,
                json.dumps({**context, "allowed_topics": allowed_topics}, ensure_ascii=False),
            )
        except json.JSONDecodeError:
            issues.append("ASSESSMENT_JSON_INVALID")
            continue
        except ApiError:
            raise
        except Exception as exc:
            raise ApiError(502, ErrorCode.INTERVIEW_LLM_REQUEST_FAILED) from exc
        try:
            return _validate_assessment(result)
        except ValueError as exc:
            issues.append(str(exc))
    error = ApiError(502, ErrorCode.INTERVIEW_LLM_RESPONSE_INVALID)
    error.diagnostic = {"stage": "chapter_assessment", "issues": issues}
    raise error


def _topic_terms(topic: str, chapter_keywords: list[str]) -> list[str]:
    terms = [term for term in chapter_keywords if term in topic or topic in term]
    return [topic, *terms]
