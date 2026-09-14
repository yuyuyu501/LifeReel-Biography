import copy

import pytest
from test_video_plan_repair import example, fake_client

from lifereel_api.modules.production import planning


def test_missing_comma_regression_uses_source_slices_not_ai_narration(monkeypatch):
    original = (
        "小时候住山脚土坯房，常和隔壁堂哥摸螺蛳、做竹弓箭，"
        "傍晚跟小伙伴在晒谷场玩，那时候快乐都是跑出来的"
    )
    scenes = [{"id": "s1", "narration": original, "duration_seconds": 22}]
    _, plan = example()
    plan["segments"][0]["end_offset"] = 25
    plan["segments"][1]["end_offset"] = len(original)
    requests = fake_client(monkeypatch, [plan])
    result = planning.plan_video(scenes, {})
    assert result["segments"][0]["narration"].endswith("竹弓箭，")
    assert result["segments"][1]["narration"].startswith("傍晚")
    assert "".join(part["narration"] for part in result["segments"]) == original
    assert [part["duration_seconds"] for part in result["segments"]] == [11, 11]
    assert len(requests) == 1
    schema = requests[0]["response_schema"]["$defs"]["BoundarySegment"]["properties"]
    assert "narration" not in schema
    assert "duration_seconds" not in schema


@pytest.mark.parametrize("original", [
    '她说：“回来吧。”\r\n 我回来了！',
    "  A, B!\n C?  ",
    "老家🏠，一起回去👨‍👩‍👧。",
    "没有标点也必须保留完整文字不能遗漏任何一个字符",
    "甲乙",
])
def test_exact_roundtrip_including_whitespace_quotes_unicode(original):
    candidates = planning.boundary_candidates(original, 2)
    end = next(item["end_offset"] for item in candidates
               if original[:item["end_offset"]].strip()
               and original[item["end_offset"]:].strip())
    _, raw = example()
    raw["segments"][0]["end_offset"] = end
    raw["segments"][1]["end_offset"] = len(original)
    scenes = [{"id": "s1", "narration": original, "duration_seconds": 22}]
    result = planning.materialize_plan(raw, scenes)
    assert "".join(part["narration"] for part in result["segments"]) == original


@pytest.mark.parametrize("ends", [[4, 4], [8, 4], [4, 100], [4, 7], [3, 8]])
def test_rejects_repeated_reversed_out_of_bounds_incomplete_and_unknown_positions(ends):
    scenes, raw = example()
    for part, end in zip(raw["segments"], ends, strict=True):
        part["end_offset"] = end
    with pytest.raises(planning.PlanValidationError) as caught:
        planning.materialize_plan(raw, scenes)
    assert caught.value.issue["code"] == "PLAN_BOUNDARY_INVALID"


@pytest.mark.parametrize("end", [True, 4.0, "4", 0, -1])
def test_requires_positive_strict_integer_boundaries(end):
    scenes, raw = example()
    raw["segments"][0]["end_offset"] = end
    with pytest.raises(ValueError):
        planning.materialize_plan(raw, scenes)


def test_rejects_ai_authored_narration_instead_of_silently_ignoring_it():
    scenes, raw = example()
    raw["segments"][0]["narration"] = "invented"
    with pytest.raises(ValueError):
        planning.materialize_plan(raw, scenes)


def test_multiple_chapters_restart_at_zero_and_duration_is_program_owned():
    scenes, raw = example()
    scenes.append({"id": "s2", "narration": "第二章。", "duration_seconds": 10})
    raw["segments"].append({"scene_id": "s2", "end_offset": 4, "visual_prompt": "下一章"})
    result = planning.materialize_plan(raw, scenes)
    assert [part["narration"] for part in result["segments"]] == [
        "第一句。", "第二句。", "第二章。",
    ]
    assert [part["duration_seconds"] for part in result["segments"]] == [11, 11, 10]
    swapped = copy.deepcopy(raw)
    swapped["segments"][0]["scene_id"] = "s2"
    with pytest.raises(planning.PlanValidationError, match="PLAN_CHAPTER_MISMATCH"):
        planning.materialize_plan(swapped, scenes)


def test_existing_saved_plans_remain_valid():
    scenes, raw = example()
    existing = planning.materialize_plan(raw, scenes)
    assert planning.validate_plan(existing, scenes) == existing


def test_empty_narration_cannot_create_fake_spoken_content():
    scenes, raw = example()
    scenes[0]["narration"] = ""
    with pytest.raises(planning.PlanValidationError, match="PLAN_BOUNDARY_INVALID"):
        planning.materialize_plan(raw, scenes)
