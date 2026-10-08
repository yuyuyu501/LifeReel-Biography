from datetime import UTC, datetime
from uuid import UUID, uuid5

from sqlalchemy import select

from lifereel_api.modules.evidence import service as evidence
from lifereel_api.modules.evidence.models import EvidenceObservation, SourceAsset
from lifereel_api.modules.interview import planning
from lifereel_api.modules.interview.models import InterviewRound
from lifereel_api.modules.interview.profile_extraction import process
from lifereel_api.modules.orchestration.progress import record_stage


def execute_profile_turn(db, tenant, workflow, session):
    from lifereel_api.modules.orchestration.service import _complete_turn_follow_up

    record_stage(db, workflow, "analyzing_materials")
    for asset_id in workflow.asset_ids:
        asset_uuid = UUID(asset_id)
        prior = db.scalar(
            select(EvidenceObservation.id).where(
                EvidenceObservation.tenant_id == tenant,
                EvidenceObservation.source_asset_id == asset_uuid,
            )
        )
        if not prior:
            evidence.analyze_asset(db, tenant, asset_uuid)
    round_ = db.get(InterviewRound, workflow.round_id)
    text = round_.answer_text or ""
    if not text:
        observation = db.scalar(
            select(EvidenceObservation)
            .join(SourceAsset)
            .where(
                EvidenceObservation.tenant_id == tenant,
                EvidenceObservation.source_asset_id.in_([UUID(i) for i in workflow.asset_ids]),
                SourceAsset.kind.in_(["audio", "video"]),
                EvidenceObservation.confidence > 0,
            )
            .order_by(EvidenceObservation.created_at.desc())
        )
        if observation:
            text = observation.text
            round_.answer_text = text
            round_.source_asset_id = observation.source_asset_id
            round_.answered_at = datetime.now(UTC)
            round_.transcript_status = "done"
            db.commit()
    if workflow.asset_ids:
        from lifereel_api.modules.interview import profile_service
        from lifereel_api.modules.interview.profile_models import LifeProfileRevision
        from lifereel_api.modules.interview.profile_schemas import EntryChange, ProfilePatch

        attachment_request = uuid5(workflow.id, "attachments")
        if not db.scalar(
            select(LifeProfileRevision.id).where(
                LifeProfileRevision.profile_id == session.profile_id,
                LifeProfileRevision.request_id == attachment_request,
            )
        ):
            changes = []
            for asset_id in workflow.asset_ids:
                asset = db.get(SourceAsset, UUID(asset_id))
                observations = list(
                    db.scalars(
                        select(EvidenceObservation).where(
                            EvidenceObservation.source_asset_id == asset.id,
                            EvidenceObservation.tenant_id == tenant,
                        )
                    )
                )
                changes.append(
                    EntryChange(
                        field_key="materials.assets[]",
                        record_key=asset_id,
                        value={
                            "title": asset.original_filename,
                            "asset_id": asset_id,
                            "kind": asset.kind,
                            "description": "\n".join(o.text for o in observations)[:3000],
                        },
                        certainty="pending",
                        use_scope="internal",
                    )
                )
            current = profile_service.read(db, tenant, session.profile_id)
            profile_service.patch(
                db,
                tenant,
                session.profile_id,
                ProfilePatch(
                    expected_version=current["version_number"],
                    request_id=attachment_request,
                    changes=changes,
                ),
                actor="attachment",
                source={"type": "source_asset", "workflow_id": str(workflow.id)},
            )
    command = planning.control(text)
    if command == "continue":
        record_stage(db, workflow, "organizing_profile")
        result = process(
            db,
            tenant,
            session.profile_id,
            text,
            {"type": "interview_round", "id": str(round_.id), "version": round_.answer_version},
            workflow.id,
            workflow=workflow,
        )
        reply = result["next_question"]
        readiness = result["profile"]["readiness"]
    else:
        from lifereel_api.modules.interview.profile_service import read

        readiness = read(db, tenant, session.profile_id)["readiness"]
        reply = (
            "好的，资料已经保存，您可以稍后继续。"
            if command == "pause"
            else "好的，您想接着讲哪段经历？"
        )
    if readiness["status"] != "not_ready":
        reply = readiness["message"] + "\n" + reply
    workflow.script_project_id = None
    workflow.script_scene_ids = []
    workflow.missing_topics = [m["label"] for m in readiness["missing_fields"][:8]]
    workflow.profile_result = {
        "profile_id": str(session.profile_id),
        "profile_version": readiness["profile_version"],
        "readiness": readiness,
        "next_question": reply,
    }
    workflow.script_brief = {
        **workflow.script_brief,
        "assessment": {"ready_for_script": False, "script_updated": False, "missing_topics": []},
        "followup_ready": True,
    }
    db.commit()
    return _complete_turn_follow_up(db, tenant, workflow)
