from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.billing.models import Charge
from lifereel_api.modules.memory.models import MemoryClaim
from lifereel_api.modules.script import service
from lifereel_api.modules.script.models import ScriptProject
from lifereel_api.modules.script.schemas import ScriptGenerateRequest


def test_source_changed_during_generation_rejects_stale_draft_and_releases_reserve(
    client, monkeypatch,
):
    person = client.post("/v1/persons", json={"display_name": "版本保护"}).json()
    chapter = client.get("/v1/chapters").json()[0]
    tenant, subject_id, chapter_id = (
        get_settings().default_tenant_id, UUID(person["id"]), UUID(chapter["id"]),
    )
    with SessionLocal() as db:
        claim = MemoryClaim(tenant_id=tenant, subject_id=subject_id, chapter_id=chapter_id,
                            claim_text="1970年和母亲过桥", source_quote="1970年和母亲过桥")
        db.add(claim)
        db.commit()
    original = service._rule_scenes

    def generate(*args):
        output = original(*args)
        with SessionLocal() as writer:
            writer.add(MemoryClaim(
                tenant_id=tenant, subject_id=subject_id, chapter_id=chapter_id,
                claim_text="更正：不是1970年，是1971年。", source_quote="更正为1971年。",
            ))
            writer.commit()
        return output

    monkeypatch.setattr(service, "_rule_scenes", generate)
    with SessionLocal() as db:
        with pytest.raises(ApiError) as failure:
            service.generate_draft(db, tenant, ScriptGenerateRequest(
                subject_id=subject_id, chapter_id=chapter_id, idempotency_key=uuid4(),
            ))
        assert failure.value.code == ErrorCode.SCRIPT_EDIT_CONFLICT
        assert db.scalar(select(ScriptProject)) is None
        assert all(c.status != "reserved" for c in db.scalars(select(Charge)))
        assert len(list(db.scalars(select(MemoryClaim)))) == 2
