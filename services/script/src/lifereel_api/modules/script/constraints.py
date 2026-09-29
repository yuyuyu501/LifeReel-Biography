from __future__ import annotations

import re
from typing import Any

NO_IDENTIFIABLE_FACE = "no_identifiable_faces"
UNSPECIFIED_FACE = "unspecified"
FACES_ALLOWED = "faces_allowed"

_NO_FACE_PATTERNS = (
    r"不出现具体的人脸",
    r"不用出现具体的人脸",
    r"不要出现具体的人脸",
    r"无具体人脸",
    r"不出现可辨识的人脸",
    r"不要露脸",
    r"不露脸",
    r"避免正脸",
)


def empty_constraints() -> dict[str, Any]:
    return {
        "face_policy": UNSPECIFIED_FACE,
        "required_elements": [],
        "forbidden_elements": [],
        "notes": None,
    }


def user_visual_constraints(*texts: str | None) -> dict[str, Any]:
    """Extract only explicit user restrictions; never infer a face policy."""
    joined = "\n".join(text or "" for text in texts)
    result = empty_constraints()
    if any(re.search(pattern, joined) for pattern in _NO_FACE_PATTERNS):
        result["face_policy"] = NO_IDENTIFIABLE_FACE
        result["forbidden_elements"] = ["可辨识正脸", "可辨识侧脸"]
        result["notes"] = "使用空镜、背影、手部特写或遮挡构图，避免可辨识面部。"
    return result


def normalize_constraints(
    value: object | None,
    *,
    inherited: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = dict(inherited or empty_constraints())
    if not isinstance(value, dict):
        return base
    policy = value.get("face_policy")
    if policy in {UNSPECIFIED_FACE, NO_IDENTIFIABLE_FACE, FACES_ALLOWED}:
        # A child shot may tighten a restriction but never relax an inherited
        # user restriction.
        if base.get("face_policy") == NO_IDENTIFIABLE_FACE and policy != NO_IDENTIFIABLE_FACE:
            policy = NO_IDENTIFIABLE_FACE
        base["face_policy"] = policy
    for key in ("required_elements", "forbidden_elements"):
        items = value.get(key)
        if isinstance(items, list):
            cleaned = [str(item).strip() for item in items if str(item).strip()]
            base[key] = list(dict.fromkeys(cleaned))[:16]
    notes = value.get("notes")
    if isinstance(notes, str) and notes.strip():
        base["notes"] = notes.strip()[:500]
    if base.get("face_policy") == NO_IDENTIFIABLE_FACE:
        base["forbidden_elements"] = list(dict.fromkeys([
            *base.get("forbidden_elements", []), "可辨识正脸", "可辨识侧脸",
        ]))[:16]
        if not base.get("notes"):
            base["notes"] = "使用空镜、背影、手部特写或遮挡构图，避免可辨识面部。"
    return base


def constraint_prompt(value: object | None) -> str:
    constraints = normalize_constraints(value)
    policy = constraints["face_policy"]
    parts: list[str] = []
    if policy == NO_IDENTIFIABLE_FACE:
        parts.append("硬约束：不得出现可辨识正脸或侧脸；使用空镜、背影、手部特写或遮挡构图")
    elif policy == FACES_ALLOWED:
        parts.append("人物面部可以出现，但不得凭空还原现实人物未提供的肖像")
    if constraints["required_elements"]:
        parts.append("必须保留：" + "、".join(constraints["required_elements"]))
    if constraints["forbidden_elements"]:
        parts.append("禁止出现：" + "、".join(constraints["forbidden_elements"]))
    if constraints.get("notes"):
        parts.append(constraints["notes"])
    return "；".join(parts)


def merge_constraints(*values: object | None) -> dict[str, Any]:
    result = empty_constraints()
    for value in values:
        result = normalize_constraints(value, inherited=result)
    return result
