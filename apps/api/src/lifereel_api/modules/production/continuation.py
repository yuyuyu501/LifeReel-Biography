"""Preserve provider originals: locally extracted/re-encoded frames are not trusted inputs."""

import hashlib
import time

from lifereel_api.modules.production.providers import VideoProviderError

TRUST_SECONDS = 30 * 24 * 60 * 60


def segment_key(run, index):
    return f"LifeReel-Biography/generated/{run.tenant_id}/{run.id}/segment-{index}.mp4"


def save_tail(storage, run, index, segment, frame, mime):
    digest = hashlib.sha256(frame).hexdigest()
    key = f"LifeReel-Biography/generated/{run.tenant_id}/{run.id}/originals/{index}-{digest}"
    storage.put(key, frame)
    segment["official_tail"] = {"storage_key": key, "sha256": digest, "mime_type": mime}


def is_current(original):
    created = original.get("created_at")
    return (
        type(created) in {int, float}
        and 0 <= time.time() - created < TRUST_SECONDS
        and str(original.get("model", "")).startswith("doubao-seedance-2-")
    )


def prepare_original(provider, storage, run, index, previous):
    """Return an unmodified tail, or an original video reference for legacy tasks."""
    expected = segment_key(run, index)
    if previous.get("status") != "completed" or previous.get("storage_key") != expected:
        raise VideoProviderError("VIDEO_CONTINUATION_UNAVAILABLE")
    original = (previous.get("parameters") or {}).get("original") or {}
    result = None
    if not original or original.get("scope") != provider.source_scope:
        task = previous.get("task_id")
        if not task:
            raise VideoProviderError("VIDEO_CONTINUATION_UNAVAILABLE")
        result = provider._request_json(
            "GET", f"{provider.base_url}/contents/generations/tasks/{task}"
        )
        if result.get("id") != task or result.get("status") != "succeeded":
            raise VideoProviderError("VIDEO_CONTINUATION_UNAVAILABLE")
        url = provider._video_url(result)
        if not url:
            raise VideoProviderError("VIDEO_CONTINUATION_UNAVAILABLE")
        content, _ = provider._download_video(url, task)
        if content != storage.get(expected):
            raise VideoProviderError("VIDEO_CONTINUATION_UNAVAILABLE")
        original = provider.original_metadata(result, content)
        if not is_current(original):
            raise VideoProviderError("VIDEO_CONTINUATION_UNAVAILABLE")
        previous.setdefault("parameters", {})["original"] = original
        frame, mime = provider.download_last_frame(result)
        if frame:
            save_tail(storage, run, index, previous, frame, mime)
    if not is_current(original) or original.get("task_id") != previous.get("task_id"):
        raise VideoProviderError("VIDEO_CONTINUATION_UNAVAILABLE")
    tail = previous.get("official_tail")
    if tail:
        expected_tail = (
            f"LifeReel-Biography/generated/{run.tenant_id}/{run.id}/originals/"
            f"{index}-{tail['sha256']}"
        )
        if tail.get("storage_key") != expected_tail:
            raise VideoProviderError("VIDEO_CONTINUATION_UNAVAILABLE")
        frame = storage.get(expected_tail)
        if hashlib.sha256(frame).hexdigest() != tail["sha256"]:
            raise VideoProviderError("VIDEO_CONTINUATION_UNAVAILABLE")
        return (
            frame,
            {"reference_mime": tail["mime_type"]},
            {
                "kind": "official_tail",
                "sha256": tail["sha256"],
                "source_task_id": previous["task_id"],
            },
        )
    content = storage.get(expected)
    if hashlib.sha256(content).hexdigest() != original.get("sha256"):
        raise VideoProviderError("VIDEO_CONTINUATION_UNAVAILABLE")
    # Signed URLs only live in the outbound request, never in the public run manifest.
    url = storage.signed_url(expected)
    if not url:
        if result is None:
            result = provider._request_json(
                "GET", f"{provider.base_url}/contents/generations/tasks/{previous['task_id']}"
            )
        url = provider._video_url(result)
    if not url:
        raise VideoProviderError("VIDEO_CONTINUATION_UNAVAILABLE")
    return (
        None,
        {"reference_video_url": url},
        {
            "kind": "original_video",
            "sha256": original["sha256"],
            "source_task_id": previous["task_id"],
        },
    )
