from __future__ import annotations

import copy
import hashlib
import json
import tempfile
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from lifereel_api.modules.evidence.storage import private_storage
from lifereel_api.modules.production.continuation import prepare_original, save_tail
from lifereel_api.modules.production.media import (
    assemble_videos,
    probe_video,
    require_media_tools,
)
from lifereel_api.modules.production.models import ProductionRun
from lifereel_api.modules.production.planning import plan_video
from lifereel_api.modules.production.providers import (
    ProviderOutput,
    VideoProviderError,
    VolcengineSeedanceProvider,
)
from lifereel_api.modules.production.recovery import (
    assert_retry_allowed,
    moderation_code,
    reference_asset,
)
from lifereel_api.modules.production.references import initial_photo_reference


def checkpoint(db: Session, run: ProductionRun, manifest: dict) -> None:
    run.output_manifest = copy.deepcopy(manifest)
    db.commit()


def advance(db: Session, run: ProductionRun) -> ProviderOutput | None:
    """Process at most one cloud segment per queue delivery, then assemble on the next."""
    require_media_tools()
    assert_retry_allowed(run)
    manifest = copy.deepcopy(run.output_manifest or {})
    config = manifest["generation_config"]
    if not manifest.get("plan"):
        photo = initial_photo_reference(db, run)
        manifest["stage"] = "planning"
        manifest["planning_diagnostics"] = []
        checkpoint(db, run, manifest)
        diagnostic_id = uuid4().hex

        def record_failure(diagnostic: dict, response: object) -> None:
            # Raw model content stays private, outside manifests returned by public APIs.
            key = (
                f"LifeReel-Biography/diagnostics/{run.tenant_id}/{run.id}/"
                f"{diagnostic_id}/attempt-{diagnostic['attempt']}.json"
            )
            text = json.dumps(response, ensure_ascii=False)
            payload = {
                **diagnostic, "response": text[:64000], "truncated": len(text) > 64000,
            }
            try:
                private_storage().put(key, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            except Exception:
                raise VideoProviderError("VIDEO_PLAN_FAILED") from None
            manifest["planning_diagnostics"] = [
                *manifest["planning_diagnostics"],
                {**diagnostic, "diagnostic_id": diagnostic_id},
            ][-3:]
            checkpoint(db, run, manifest)

        manifest["plan"] = plan_video(
            manifest["script_snapshot"], manifest.get("subject", {}), on_failure=record_failure,
            has_portrait=photo is not None,
        )
        manifest["segments"] = [
            {**segment, "status": "pending"} for segment in manifest["plan"]["segments"]
        ]
        if photo is not None:
            manifest["segments"][0]["reference_asset_id"] = str(photo.id)
        manifest["target_duration_seconds"] = sum(
            segment["duration_seconds"] for segment in manifest["segments"]
        )
        manifest["stage"] = "generating"
        checkpoint(db, run, manifest)
    segments = manifest["segments"]
    storage = private_storage()
    with tempfile.TemporaryDirectory(prefix="lifereel-chapter-") as temporary:
        directory = Path(temporary)
        pending = next(
            ((index, item) for index, item in enumerate(segments) if item["status"] != "completed"),
            None,
        )
        if pending:
            index, segment = pending
            if segment["status"] in {"submitting", "submission_unknown"} and not segment.get(
                "task_id"
            ):
                raise VideoProviderError("VIDEO_SUBMISSION_UNCERTAIN")
            provider = VolcengineSeedanceProvider(options=config)
            try:
                if not segment.get("task_id"):
                    frame = None
                    reference_options = {}
                    # Also cover queued runs whose plan predates automatic photo binding.
                    if index == 0 and not segment.get("reference_asset_id"):
                        photo = initial_photo_reference(db, run)
                        if photo is not None:
                            segment["reference_asset_id"] = str(photo.id)
                    if segment.get("reference_asset_id"):
                        asset = reference_asset(db, run, UUID(segment["reference_asset_id"]))
                        frame = storage.get(asset.storage_key)
                        if not frame or hashlib.sha256(frame).hexdigest() != asset.sha256:
                            raise VideoProviderError("VIDEO_REFERENCE_INVALID")
                        reference_options["reference_mime"] = asset.mime_type
                        segment["reference_kind"] = "uploaded_image"
                    elif index:
                        frame, reference_options, source = prepare_original(
                            provider, storage, run, index - 1, segments[index - 1],
                        )
                        segment.update({
                            "reference_kind": source["kind"],
                            "reference_sha256": source["sha256"],
                            "reference_source_task_id": source["source_task_id"],
                        })
                    if frame:
                        segment["reference_sha256"] = hashlib.sha256(frame).hexdigest()
                    prompt = (
                        "连续纪实镜头，家庭传记情景重现。"
                        f"这是本章第{index + 1}/{len(segments)}段，"
                        f"时长{segment['duration_seconds']}秒。"
                        f"统一人物和视觉：{manifest['plan']['continuity']}。"
                        "保持同一人物身份、性别、年龄、服装；参考帧存在时延续其场景和外貌。"
                        f"本段画面：{segment['visual_prompt']}。"
                        f"统一旁白声线：{manifest['plan']['voice']}。"
                        "以下引号内是本段全部普通话口播（旁白与人物对话），按角色分配完整清晰读完，"
                        "未指定角色的使用旁白。不要念说明文字，不增删口播，不重复前段，不截断最后一句。"
                        f"口播全文：{json.dumps(segment['narration'], ensure_ascii=False)}。"
                        "无背景音乐，低音量自然环境声，口播优先。不添加字幕或片尾。"
                    )
                    if reference_options.get("reference_video_url"):
                        prompt = (
                            f"将视频1向后延长{segment['duration_seconds']}秒，"
                            "从视频1的结尾继续，只输出新增内容，不回放或重复原视频。"
                            "保持原视频的人物、场景、动作方向和旁白音色。" + prompt
                        )
                    if segment.get("dialogues"):
                        prompt += (
                            "本段口播角色分配如下，kind为narration的作为画外旁白，kind为dialogue的"
                            "由对应人物说出；角色标签是说明，不朗读。上文所列口播全文仅朗读一次，"
                            "以下分配不增加或重复台词，不克隆真人声音："
                            + json.dumps(segment["dialogues"], ensure_ascii=False)
                        )
                    segment["status"] = "submitting"
                    segment["prompt"] = prompt
                    checkpoint(db, run, manifest)
                    try:
                        segment["task_id"] = provider.submit_segment(
                            prompt, segment["duration_seconds"], frame, **reference_options
                        )
                    except VideoProviderError as exc:
                        segment["status"] = (
                            "pending" if exc.provider_status == "rejected" else "submission_unknown"
                        )
                        segment["provider_error_code"] = exc.provider_error_code
                        if moderation_code(exc.provider_error_code) and segment.get(
                            "reference_sha256"
                        ):
                            segment.setdefault("rejected_reference_hashes", []).append(
                                segment["reference_sha256"]
                            )
                        checkpoint(db, run, manifest)
                        if segment["status"] == "submission_unknown":
                            raise VideoProviderError("VIDEO_SUBMISSION_UNCERTAIN") from exc
                        raise
                    segment["status"] = "submitted"
                    checkpoint(db, run, manifest)
                try:
                    output = provider.fetch_segment(segment["task_id"], segment["duration_seconds"])
                except VideoProviderError as exc:
                    if exc.provider_status in {"failed", "expired", "cancelled", "canceled"}:
                        segment.setdefault("previous_task_ids", []).append(segment.pop("task_id"))
                        segment["status"] = "pending"
                    segment["provider_error_code"] = exc.provider_error_code
                    if moderation_code(exc.provider_error_code) and segment.get("reference_sha256"):
                        segment.setdefault("rejected_reference_hashes", []).append(
                            segment["reference_sha256"]
                        )
                    checkpoint(db, run, manifest)
                    raise
                clip = directory / "clip.mp4"
                clip.write_bytes(output.content)
                info = probe_video(clip, config["generate_audio"])
                if abs(info["duration_seconds"] - segment["duration_seconds"]) > 1:
                    raise VideoProviderError("VIDEO_DURATION_MISMATCH")
                key = (
                    f"LifeReel-Biography/generated/{run.tenant_id}/{run.id}/"
                    f"segment-{index}.mp4"
                )
                storage.put(key, output.content)
                if output.last_frame:
                    save_tail(
                        storage, run, index, segment, output.last_frame,
                        output.parameters["last_frame_mime"],
                    )
                segment.update(
                    {
                        "status": "completed",
                        "storage_key": key,
                        "media": info,
                        "parameters": output.parameters,
                    }
                )
                manifest["completed_segments"] = index + 1
                manifest["stage"] = "assembling" if index + 1 == len(segments) else "generating"
                checkpoint(db, run, manifest)
                return None
            finally:
                provider.client.close()
        paths = []
        for index, segment in enumerate(segments):
            path = directory / f"segment-{index}.mp4"
            path.write_bytes(storage.get(segment["storage_key"]))
            paths.append(path)
        content, info = assemble_videos(paths, directory, config)
        if abs(info["duration_seconds"] - manifest["target_duration_seconds"]) > len(paths):
            raise VideoProviderError("VIDEO_DURATION_MISMATCH")
        manifest["stage"] = "completed"
        checkpoint(db, run, manifest)
        return ProviderOutput(
            content=content,
            mime_type="video/mp4",
            extension="mp4",
            parameters={
                **config,
                **info,
                "segment_count": len(paths),
                "target_duration_seconds": manifest["target_duration_seconds"],
                "provider_job_ids": [item["task_id"] for item in segments],
            },
        )
