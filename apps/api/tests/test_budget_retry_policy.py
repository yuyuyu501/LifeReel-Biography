from datetime import UTC, datetime
from io import BytesIO
from uuid import UUID

import pytest

from lifereel_api.core.config import get_settings
from lifereel_api.core.database import SessionLocal
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.interview.models import InterviewTurnWorkflow
from lifereel_api.modules.jobs import service as jobs
from lifereel_api.modules.memory import recovery
from lifereel_api.modules.orchestration import service

BUDGET_ERRORS = [
    ErrorCode.EVIDENCE_TEXT_TOO_LARGE, ErrorCode.MEMORY_INPUT_TOO_LARGE,
    ErrorCode.SCRIPT_INPUT_TOO_LARGE, ErrorCode.SCRIPT_MOCK_OUTPUT_TOO_LARGE,
]


@pytest.mark.parametrize("code", BUDGET_ERRORS)
@pytest.mark.parametrize("with_policy", [False, True])
def test_budget_failure_policy_and_workflow_property_agree(code, with_policy):
    workflow = InterviewTurnWorkflow(status="failed", error_code=code.value, script_brief={})
    if with_policy:
        workflow.script_brief = {"memory_recovery": {
            "version": recovery.VERSION, "runs": 1,
            "failed_at": datetime.now(UTC).isoformat(),
        }}
    assert not recovery.allowed(workflow)
    assert not workflow.retry_allowed
    assert workflow.retry_after_seconds == 0
    with pytest.raises(ApiError) as exc:
        recovery.begin(None, workflow)
    assert exc.value.code == ErrorCode.JOB_RETRY_NOT_ALLOWED


def _start(client):
    person = client.post("/v1/persons", json={"display_name": "Budget recovery"}).json()
    session = client.post("/v1/interviews", json={"subject_id": person["id"]}).json()
    return person, session


def _assert_no_retry(client, monkeypatch, session, code):
    workspace = client.get(f"/v1/interviews/{session['id']}/workspace").json()
    failed = workspace["latest_workflow"]
    assert failed["status"] == "failed"
    assert failed["error_code"] == code.value
    assert failed["retry_allowed"] is False
    assert failed["retry_after_seconds"] == 0
    job_before = client.get(f"/v1/jobs/{failed['job_id']}").json()
    wallet_before = client.get("/v1/wallet").json()
    monkeypatch.setattr(jobs, "enqueue", lambda *args: pytest.fail("budget failure was enqueued"))
    for _ in range(2):
        for path in (f"/v1/jobs/{failed['job_id']}/retry",
                     f"/v1/internal/interview-turns/{failed['id']}/execute"):
            rejected = client.post(path)
            assert rejected.status_code == 409
            assert rejected.json()["error"]["code"] == "JOB_RETRY_NOT_ALLOWED"
    assert client.get(f"/v1/jobs/{failed['job_id']}").json() == job_before
    assert client.get("/v1/wallet").json() == wallet_before
    unchanged = client.get(f"/v1/interviews/{session['id']}/workspace").json()["latest_workflow"]
    assert unchanged == failed
    return failed


@pytest.mark.parametrize("code", BUDGET_ERRORS)
def test_budget_retry_endpoints_preserve_attempts_and_allow_a_new_submission(client, monkeypatch,
                                                                          code):
    _, session = _start(client)
    assess = service._assess_chapter

    def fail(*args, **kwargs):
        raise ApiError(413, code)

    monkeypatch.setattr(service, "_assess_chapter", fail)
    rejected = client.post(
        f"/v1/interviews/{session['id']}/turns",
        json={"answer_text": "母亲在家教我读书。", "idempotency_key": "budget-original"},
    )
    assert rejected.status_code == 413
    failed = _assert_no_retry(client, monkeypatch, session, code)
    monkeypatch.setattr(service, "_assess_chapter", assess)
    submitted = client.post(
        f"/v1/interviews/{session['id']}/turns",
        json={"answer_text": "后来我上学了。", "idempotency_key": "budget-smaller"},
    )
    assert submitted.status_code == 202
    assert submitted.json()["status"] == "completed"
    assert submitted.json()["id"] != failed["id"]
    with SessionLocal() as db:
        original = db.get(InterviewTurnWorkflow, UUID(failed["id"]))
        assert original.error_code == code.value
        assert recovery.policy(original)["runs"] == 1


def test_smaller_document_does_not_automatically_resubmit_rejected_original(client, monkeypatch,
                                                                         tmp_path):
    monkeypatch.setattr(get_settings(), "local_storage_path", str(tmp_path / "storage"))
    person, session = _start(client)

    def upload(text, name):
        response = client.post(
            "/v1/evidence/assets",
            data={"subject_id": person["id"], "interview_session_id": session["id"],
                  "kind": "document"},
            files={"file": (name, BytesIO(text.encode()), "text/plain")},
        )
        assert response.status_code == 201
        return response.json()

    original_text = "家" * 20_001
    large = upload(original_text, "large.txt")
    rejected = client.post(
        f"/v1/interviews/{session['id']}/turns",
        json={"asset_ids": [large["id"]], "idempotency_key": "large-document"},
    )
    assert rejected.status_code == 413
    failed = _assert_no_retry(client, monkeypatch, session, ErrorCode.EVIDENCE_TEXT_TOO_LARGE)
    small = upload("小时候母亲在家教我读书。", "small.txt")
    continued = client.post(
        f"/v1/interviews/{session['id']}/turns",
        json={"asset_ids": [small["id"]], "idempotency_key": "small-document"},
    )
    assert continued.status_code == 202
    assert continued.json()["status"] == "completed"
    assert continued.json()["asset_ids"] == [small["id"]]
    assert continued.json()["id"] != failed["id"]
    workspace = client.get(f"/v1/interviews/{session['id']}/workspace").json()
    assert {asset["id"] for asset in workspace["assets"]} == {large["id"], small["id"]}
    downloaded = client.get(f"/v1/evidence/assets/{large['id']}/content")
    assert downloaded.content == original_text.encode()
