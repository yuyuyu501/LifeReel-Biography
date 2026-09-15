"""Opt-in check against the disposable PostgreSQL container, never production."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4

import httpx
from alembic.config import Config
from sqlalchemy import select, text

from alembic import command

os.environ.update(
    {
        "APP_ENV": "test",
        "DATABASE_URL": "postgresql+psycopg://postgres:lifereel-disposable-test@"
        "127.0.0.1:55439/lifereel_token_check",
        "BILLING_TEXT_MODE": "tokens",
        "AUTO_CREATE_SCHEMA": "false",
        "PGOPTIONS": "-c statement_timeout=15000 -c lock_timeout=10000",
    }
)

from lifereel_api.core.config import get_settings  # noqa: E402
from lifereel_api.core.database import SessionLocal  # noqa: E402
from lifereel_api.core.errors import ApiError  # noqa: E402
from lifereel_api.main import app  # noqa: E402,F401
from lifereel_api.modules.billing import service, tokens  # noqa: E402
from lifereel_api.modules.billing.models import UsageEvent  # noqa: E402
from lifereel_api.modules.billing.usage import track_usage  # noqa: E402
from lifereel_api.modules.identity.models import Person, Tenant  # noqa: E402
from lifereel_api.modules.interview.models import (  # noqa: E402
    Chapter,
    InterviewRound,
    InterviewSession,
    InterviewTurnWorkflow,
)
from lifereel_api.modules.orchestration.service import execute_turn  # noqa: E402
from lifereel_api.providers.openai_compatible import OpenAICompatibleClient  # noqa: E402


@track_usage("script")
def call(db, tenant_id, receipt):
    return OpenAICompatibleClient(
        "https://ark.cn-beijing.volces.com/api/v3",
        "synthetic",
        tokens.MODEL,
    ).chat("synthetic", receipt)


def response(*args, **kwargs):
    return httpx.Response(
        200,
        request=httpx.Request("POST", "https://synthetic.test"),
        json={
            "id": kwargs["json"]["messages"][-1]["content"],
            "usage": {"prompt_tokens": 10000, "completion_tokens": 1000},
            "choices": [{"message": {"content": "synthetic"}}],
        },
    )


def workflow_checks(tenant_id):
    settings = get_settings()
    settings.llm_provider = "openai-compatible"
    settings.openai_compatible_base_url = "https://ark.cn-beijing.volces.com/api/v3"
    settings.openai_compatible_api_key = "synthetic"
    settings.interview_llm_model = settings.memory_llm_model = settings.script_llm_model = (
        tokens.MODEL
    )
    with SessionLocal() as db:
        person = Person(tenant_id=tenant_id, display_name="Synthetic workflow")
        chapter = Chapter(tenant_id=tenant_id, title="童年", order_index=1)
        db.add_all([person, chapter])
        db.flush()
        session = InterviewSession(
            tenant_id=tenant_id, subject_id=person.id, chapter_id=chapter.id, round_count=1
        )
        db.add(session)
        db.flush()
        round_ = InterviewRound(
            tenant_id=tenant_id,
            session_id=session.id,
            round_index=1,
            question_text="如何称呼您？",
            answer_text="叫我小林。",
        )
        db.add(round_)
        db.flush()
        workflow = InterviewTurnWorkflow(
            tenant_id=tenant_id,
            session_id=session.id,
            round_id=round_.id,
            chapter_id=chapter.id,
            idempotency_key=str(uuid4()),
        )
        db.add(workflow)
        db.commit()

    state = {"ready": False, "fail_question": False}
    calls = []

    def generated(*args, **kwargs):
        messages = kwargs["json"]["messages"]
        system, user = messages[0]["content"], json.loads(messages[1]["content"])
        if "证据整理员" in system:
            result = {
                "claim_text": user["source_text"],
                "claim_type": "recollection",
                "confidence": 0.9,
            }
        elif "知识图谱整理员" in system:
            result = {"entities": [], "timeline": [], "conflicts": []}
        elif "口述史编辑" in system:
            result = {"biography": "他叫小林。"}
        elif "采访规划师" in system:
            result = {
                "missing_topics": ["地点"],
                "ready_for_script": state["ready"],
                "reason": "synthetic assessment",
            }
        elif "短视频编剧" in system:
            ids = [user["evidence_pack"][0]["claim_id"]]
            result = {
                "chapter": {
                    "heading": "童年",
                    "narration": "我在家乡长大。",
                    "plot": "回忆家乡。",
                    "dialogues": [{"kind": "narration", "speaker": "主人公",
                                   "text": "我在家乡长大。"}],
                    "visual_prompt": "家乡",
                    "duration_seconds": 18,
                    "source_claim_ids": ids,
                    "shots": [
                        {"visual_prompt": "家乡", "duration_seconds": 6, "source_claim_ids": ids}
                    ],
                }
            }
        elif "采访者" in system:
            if state["fail_question"]:
                state["fail_question"] = False
                return httpx.Response(
                    429,
                    request=httpx.Request("POST", "https://synthetic.test"),
                    json={"error": {"message": "synthetic rate limit"}},
                )
            result = {"next_question": "您小时候在哪里生活？", "intent": "place"}
        else:
            raise AssertionError("Unexpected model call")
        calls.append(system)
        return httpx.Response(
            200,
            request=httpx.Request("POST", "https://synthetic.test"),
            json={
                "id": str(uuid4()),
                "usage": {"prompt_tokens": 10000, "completion_tokens": 1000},
                "choices": [{"message": {"content": json.dumps(result, ensure_ascii=False)}}],
            },
        )

    with patch.object(httpx, "post", generated):
        with SessionLocal() as db:
            done = execute_turn(db, tenant_id, workflow.id)
            assert done.status == "completed" and done.script_project_id is None
            assert done.next_question and len(calls) == 5
        with SessionLocal() as db:
            next_round = db.scalar(
                select(InterviewRound).where(
                    InterviewRound.session_id == session.id,
                    InterviewRound.round_index == 2,
                )
            )
            next_round.answer_text = "小时候我和母亲住在泉州。"
            later = InterviewTurnWorkflow(
                tenant_id=tenant_id,
                session_id=session.id,
                round_id=next_round.id,
                chapter_id=chapter.id,
                idempotency_key=str(uuid4()),
            )
            db.add(later)
            db.commit()
        state.update(ready=True, fail_question=True)
        with SessionLocal() as db:
            try:
                execute_turn(db, tenant_id, later.id)
            except ApiError as exc:
                assert exc.code.value == "INTERVIEW_LLM_REQUEST_FAILED"
            else:
                raise AssertionError("Synthetic follow-up should fail")
        with SessionLocal() as db:
            done = execute_turn(db, tenant_id, later.id)
            assert done.status == "completed" and done.script_project_id
            assert sum("短视频编剧" in item for item in calls) == 1
            wallet = service.lock_wallet(db, tenant_id)
            assert wallet.frozen_bonus_cents == 0
            assert service.available(wallet) == 1997 - (len(calls) * 15 // 10)
            rows = list(
                db.scalars(
                    select(UsageEvent).where(
                        UsageEvent.tenant_id == tenant_id,
                        UsageEvent.reference.in_([str(workflow.id), str(later.id)]),
                    )
                )
            )
            assert len(rows) == len(calls) + 1
            assert all(row.metering["status"] in {"settled", "released"} for row in rows)
    print("PASS: not-ready follow-up and saved-script retry, all receipts attributed and settled")


def main():
    command.upgrade(Config("alembic.ini"), "head")
    tenant_id = uuid4()
    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="Synthetic token test", slug=str(tenant_id)))
        db.commit()
        service.lock_wallet(db, tenant_id)
        db.commit()
    with patch.object(httpx, "post", response):
        with SessionLocal() as business:
            business.add(Person(tenant_id=tenant_id, display_name="Synthetic uncommitted person"))
            business.flush()
            # A FK lock held by the business transaction must not block settlement.
            call(business, tenant_id, f"fk-{tenant_id}")
            business.rollback()

        def concurrent(index):
            with SessionLocal() as db:
                return call(db, tenant_id, f"duplicate-{tenant_id}")

        with ThreadPoolExecutor(max_workers=6) as pool:
            assert len(list(pool.map(concurrent, range(6)))) == 6
    with SessionLocal() as db:
        wallet = service.lock_wallet(db, tenant_id)
        assert service.available(wallet) == 1997
        assert wallet.token_remainder_nano == 0
        assert wallet.frozen_bonus_cents == 0
        assert (
            db.scalar(text("SELECT count(*) FROM persons WHERE tenant_id=:id"), {"id": tenant_id})
            == 0
        )
        assert get_settings().billing_text_mode == "tokens"
    print("PASS: migration, FK transaction isolation, six concurrent receipts, exact wallet debit")
    workflow_checks(tenant_id)


if __name__ == "__main__":
    main()
