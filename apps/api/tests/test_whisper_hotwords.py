from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.modules.evidence import service
from lifereel_api.modules.evidence.models import SourceAsset
from lifereel_api.modules.evidence.schemas import TranscriptRevisionCreate
from lifereel_api.modules.identity.models import Person, Tenant
from lifereel_api.modules.memory.models import MemoryClaim
from lifereel_api.providers import whisper

RAW_TEXT = "我出生在慈禧，做过修传功。"


@pytest.fixture(autouse=True)
def decoder(monkeypatch, tmp_path):
    """Never load/download Whisper or decode audio; exercise the real call boundary."""
    calls = []

    class Model:
        def transcribe(self, source, **kwargs):
            assert Path(source).is_file()
            calls.append(kwargs)
            return iter([SimpleNamespace(text=RAW_TEXT)]), None

    model = Model()  # Reuse one model just like the production model cache.
    monkeypatch.setattr(whisper, "_load_model", lambda *args: model)
    monkeypatch.setattr(get_settings(), "asr_provider", "faster-whisper")
    monkeypatch.setattr(get_settings(), "asr_model", "small")
    source = tmp_path / "stub.wav"
    source.write_bytes(b"stub-only")

    @contextmanager
    def private_file(*args):
        yield source

    monkeypatch.setattr(service, "private_file", private_file)
    return calls


@pytest.fixture
def context():
    with SessionLocal() as db:
        tenant = Tenant(name="Current tenant", slug="current")
        foreign_tenant = Tenant(name="Other tenant", slug="other")
        db.add_all([tenant, foreign_tenant])
        db.flush()
        subject = Person(
            tenant_id=tenant.id, display_name="陈海生", preferred_name="陈伯",
            birthplace="慈溪", biography_note="模型猜测：造船工程师，在舟山长大。",
        )
        other = Person(
            tenant_id=tenant.id, display_name="同租户他人", preferred_name="他人称呼",
            birthplace="宁波",
        )
        foreign = Person(
            tenant_id=foreign_tenant.id, display_name="跨租户人物", birthplace="上海",
        )
        db.add_all([subject, other, foreign])
        db.commit()
        yield SimpleNamespace(
            db=db, tenant=tenant, foreign_tenant=foreign_tenant,
            subject=subject, other=other, foreign=foreign,
        )


def add_claim(context, *, person=None, tenant=None, review_status="verified",
              text="我曾是修船工。"):
    person = person if person is not None else context.subject
    tenant_id = tenant.id if tenant is not None else person.tenant_id
    claim = MemoryClaim(
        tenant_id=tenant_id, subject_id=person.id,
        claim_text=text, source_quote="我曾是修传功。",
        review_status=review_status, confidence=1.0, extraction_provider="model",
    )
    context.db.add(claim)
    context.db.commit()
    return claim


def transcribe(context, person=None, tenant=None):
    person = person if person is not None else context.subject
    tenant_id = tenant.id if tenant is not None else person.tenant_id
    asset = SourceAsset(
        tenant_id=tenant_id, subject_id=person.id, kind="audio",
        original_filename="stub.wav", mime_type="audio/wav", byte_size=9,
        sha256=uuid4().hex, storage_key=f"stub/{uuid4()}",
    )
    context.db.add(asset)
    context.db.commit()
    return service.transcribe_asset(context.db, tenant_id, asset.id)


@pytest.mark.parametrize("as_path", [False, True])
def test_provider_optional_hints_keep_transcribe_signature(decoder, tmp_path, as_path):
    content = b"stub-only"
    if as_path:
        content = tmp_path / "provider.wav"
        content.write_bytes(b"stub-only")
    client = whisper.FasterWhisperClient(
        "small", "cpu", "int8", hotwords=" 慈溪、陈伯 ",
    )
    assert client.transcribe("answer.wav", content, "audio/wav") == RAW_TEXT
    assert decoder == [{
        "language": "zh", "vad_filter": True, "beam_size": 5,
        "hotwords": "慈溪、陈伯",
    }]


@pytest.mark.parametrize("hints", [{}, {"hotwords": None}, {"hotwords": " \n"}])
def test_empty_hints_are_omitted_and_never_leak_from_cached_model(decoder, hints):
    whisper.FasterWhisperClient("small", hotwords="他人资料").transcribe(
        "first.wav", b"stub", "audio/wav",
    )
    whisper.FasterWhisperClient("small", **hints).transcribe("empty.wav", b"stub", "audio/wav")
    assert decoder[-1] == {"language": "zh", "vad_filter": True, "beam_size": 5}


def test_only_current_person_profile_is_used_across_tenants_and_people(context, decoder):
    add_claim(context)
    add_claim(context, text="模型声称是造船工程师，出生在舟山。")
    transcribe(context)
    assert decoder[-1]["hotwords"] == "陈海生、陈伯、慈溪"
    assert "initial_prompt" not in decoder[-1]

    # A second request uses the same decoder model, but its own person's profile.
    transcribe(context, context.other)
    assert decoder[-1]["hotwords"] == "同租户他人、他人称呼、宁波"
    transcribe(context, context.foreign)
    assert decoder[-1]["hotwords"] == "跨租户人物、上海"


@pytest.mark.parametrize("review_status", ["verified", "unreviewed", "disputed", "private"])
def test_claims_are_not_hints_even_when_verified(context, decoder, review_status):
    add_claim(context, review_status=review_status)
    transcribe(context)
    assert decoder[-1]["hotwords"] == "陈海生、陈伯、慈溪"


def test_blank_profile_has_no_prompt_and_no_global_confusion_dictionary(context, decoder):
    context.subject.display_name = " \n"
    context.subject.preferred_name = "\t"
    context.subject.birthplace = None
    add_claim(context, review_status="unreviewed")
    add_claim(context, person=context.other)
    transcribe(context)
    assert decoder[-1] == {"language": "zh", "vad_filter": True, "beam_size": 5}


def test_subject_from_another_tenant_cannot_supply_profile_or_terms(context, decoder):
    add_claim(context, person=context.foreign, tenant=context.tenant)
    transcribe(context, context.foreign, context.tenant)
    assert decoder[-1] == {"language": "zh", "vad_filter": True, "beam_size": 5}


def test_hints_are_deduplicated_and_long_fields_are_not_truncated_into_names(context, decoder):
    context.subject.display_name = " 陈伯 "
    context.subject.preferred_name = "陈伯"
    context.subject.birthplace = "地" * 65
    transcribe(context)
    assert decoder[-1]["hotwords"] == "陈伯"

    context.subject.display_name = "甲" * 64
    context.subject.preferred_name = "乙" * 64
    context.subject.birthplace = "丙" * 64
    add_claim(context)
    transcribe(context)
    assert decoder[-1]["hotwords"] == "甲" * 64 + "、" + "乙" * 64
    assert len(decoder[-1]["hotwords"]) <= 160


def test_raw_provider_text_and_manual_versions_survive_hints_and_retranscription(context, decoder):
    claim = add_claim(context)
    transcript = transcribe(context)
    corrected = "我出生在慈溪，做过修船工。"
    service.revise_transcript(
        context.db, context.tenant.id, transcript.id,
        TranscriptRevisionCreate(text=corrected, edit_reason="人工听录音校对"),
    )
    service.transcribe_asset(context.db, context.tenant.id, transcript.source_asset_id)
    _, versions = service.get_transcript_payload(context.db, context.tenant.id, transcript.id)
    assert [(version.source, version.text) for version, _ in versions] == [
        ("provider_asr", RAW_TEXT), ("manual", corrected), ("provider_asr", RAW_TEXT),
    ]
    assert [segments[0].text for _, segments in versions] == [RAW_TEXT, corrected, RAW_TEXT]
    assert len(decoder) == 2
    assert all(call["hotwords"] == "陈海生、陈伯、慈溪" for call in decoder)
    context.db.refresh(context.subject)
    context.db.refresh(claim)
    assert context.subject.birthplace == "慈溪"
    assert context.subject.biography_note == "模型猜测：造船工程师，在舟山长大。"
    assert (claim.claim_text, claim.source_quote, claim.review_status) == (
        "我曾是修船工。", "我曾是修传功。", "verified",
    )
    assert context.db.scalar(select(func.count()).select_from(MemoryClaim)) == 1
