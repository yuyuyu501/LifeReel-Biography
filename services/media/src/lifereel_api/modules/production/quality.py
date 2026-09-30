"""Reference locking and review evidence; these do not certify face identity."""

import base64
import hashlib
import subprocess
from difflib import SequenceMatcher

from lifereel_api.modules.production import appearance
from lifereel_api.modules.production.continuation import prepare_original


def shot_review(scenes):
    warnings = []
    for scene in scenes:
        shots = scene.get("shots", [])
        for i in range(1, len(shots)):
            left = "".join(shots[i - 1].get("visual_prompt", "").split())
            right = "".join(shots[i].get("visual_prompt", "").split())
            if left and right and SequenceMatcher(None, left, right).ratio() >= 0.9:
                warnings.append(
                    {"scene_id": scene.get("id"), "shot_index": i, "code": "SIMILAR_ADJACENT_SHOTS"}
                )
    return {"shot_warnings": warnings, "identity_verification": "manual_review_required"}


def identity_inputs(db, run, manifest, provider, storage, index):
    inputs = appearance.inputs(db, run, manifest)
    images = list(inputs.get("reference_images") or [])
    previous = manifest["segments"][index - 1] if index else None
    # Only add an unmodified, verified provider tail as an extra reference image.
    # Never mix first_frame/reference_video roles with reference_images.
    if images and previous and previous.get("official_tail") and len(images) < 9:
        frame, options, _ = prepare_original(provider, storage, run, index - 1, previous)
        if frame:
            images.append(
                "data:" + options["reference_mime"] + ";base64," + base64.b64encode(frame).decode()
            )
    inputs["reference_images"] = images
    return inputs


def collect_review_frames(storage, run, index, clip, duration):
    frames = []
    for position, time in enumerate((max(0.0, duration * 0.15), max(0.0, duration * 0.65))):
        try:
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-ss",
                    str(time),
                    "-i",
                    str(clip),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=240:-2",
                    "-f",
                    "image2pipe",
                    "-vcodec",
                    "mjpeg",
                    "pipe:1",
                ],
                check=True,
                capture_output=True,
                timeout=20,
            )
            content = result.stdout
            if not content.startswith(b"\xff\xd8") or len(content) > 1024 * 1024:
                continue
            key = (f"LifeReel-Biography/generated/{run.tenant_id}/{run.id}/"
                   f"review/{index}-{position}.jpg")
            storage.put(key, content)
            frames.append(
                {
                    "position": position,
                    "at_seconds": round(time, 2),
                    "storage_key": key,
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
        except (OSError, subprocess.SubprocessError):
            # Main video remains usable; missing review frames are explicitly shown.
            continue
    return frames
