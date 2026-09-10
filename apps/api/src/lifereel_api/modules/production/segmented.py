from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

from sqlalchemy.orm import Session

from lifereel_api.modules.evidence.storage import private_storage
from lifereel_api.modules.production.media import (
    assemble_videos,
    last_frame,
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


def checkpoint(db: Session, run: ProductionRun, manifest: dict) -> None:
    run.output_manifest = copy.deepcopy(manifest)
    db.commit()


def advance(db: Session, run: ProductionRun) -> ProviderOutput | None:
    """Process at most one cloud segment per queue delivery, then assemble on the next."""
    require_media_tools()
    manifest = copy.deepcopy(run.output_manifest or {})
    config = manifest["generation_config"]
    if not manifest.get("plan"):
        manifest["stage"] = "planning"
        checkpoint(db, run, manifest)
        manifest["plan"] = plan_video(manifest["script_snapshot"], manifest.get("subject", {}))
        manifest["segments"] = [
            {**segment, "status": "pending"} for segment in manifest["plan"]["segments"]
        ]
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
                    if index:
                        previous = directory / "previous.mp4"
                        previous.write_bytes(storage.get(segments[index - 1]["storage_key"]))
                        frame = last_frame(previous)
                    prompt = (
                        "连续纪实镜头，家庭传记情景重现。"
                        f"这是本章第{index + 1}/{len(segments)}段，"
                        f"时长{segment['duration_seconds']}秒。"
                        f"统一人物和视觉：{manifest['plan']['continuity']}。"
                        "保持同一人物身份、性别、年龄、服装；参考帧存在时延续其场景和外貌。"
                        f"本段画面：{segment['visual_prompt']}。"
                        f"统一旁白声线：{manifest['plan']['voice']}。"
                        "以下引号内是本段全部普通话旁白，完整清晰读完，不念说明文字、不增删旁白，"
                        "不要重复前段旁白，不要截断最后一句。"
                        f"旁白说：{json.dumps(segment['narration'], ensure_ascii=False)}。"
                        "无背景音乐，低音量自然环境声，旁白优先。不添加字幕或片尾。"
                    )
                    segment["status"] = "submitting"
                    segment["prompt"] = prompt
                    checkpoint(db, run, manifest)
                    try:
                        segment["task_id"] = provider.submit_segment(
                            prompt, segment["duration_seconds"], frame
                        )
                    except VideoProviderError as exc:
                        segment["status"] = (
                            "pending" if exc.provider_status == "rejected" else "submission_unknown"
                        )
                        segment["provider_error_code"] = exc.provider_error_code
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
