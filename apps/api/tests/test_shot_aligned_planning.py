from lifereel_api.modules.production import planning
from lifereel_api.modules.script.constraints import (
    NO_IDENTIFIABLE_FACE,
    constraint_prompt,
    user_visual_constraints,
)


def scene(*, durations=(5, 6, 5), constraints=None):
    shots = [
        {
            "id": f"shot-{index}",
            "shot_type": "wide" if index == 0 else "detail",
            "visual_prompt": f"分镜{index + 1}",
            "duration_seconds": duration,
            "visual_constraints": (constraints if index == 0 else None),
        }
        for index, duration in enumerate(durations)
    ]
    narration = "第一句，第二句。第三句，第四句。第五句。"
    return {
        "id": "scene-1",
        "narration": narration,
        "dialogues": [{"kind": "narration", "speaker": "人物", "text": narration}],
        "duration_seconds": sum(durations),
        "visual_constraints": constraints,
        "shots": shots,
    }


def test_explicit_user_face_constraint_is_structured_without_inference():
    no_face = user_visual_constraints("请保留河流和石桥，画面不用出现具体的人脸。")
    unspecified = user_visual_constraints("请保留河流和石桥。")

    assert no_face["face_policy"] == NO_IDENTIFIABLE_FACE
    assert "可辨识正脸" in no_face["forbidden_elements"]
    assert unspecified["face_policy"] == "unspecified"


def test_shot_aligned_plan_uses_each_shot_and_repeats_hard_constraint():
    constraints = user_visual_constraints("不要出现具体的人脸")
    result = planning.shot_aligned_plan(
        [scene(constraints=constraints)], {"display_name": "测试人物"}
    )

    assert [item["duration_seconds"] for item in result["segments"]] == [5, 6, 5]
    assert [item["shot_id"] for item in result["segments"]] == [
        "shot-0", "shot-1", "shot-2",
    ]
    assert all("不得出现可辨识正脸或侧脸" in item["visual_prompt"] for item in result["segments"])
    assert all(item["visual_constraints"]["face_policy"] == NO_IDENTIFIABLE_FACE
               for item in result["segments"])
    assert "不要出现具体的人脸" not in result["segments"][0]["narration"]


def test_short_shots_are_merged_and_long_shots_are_split():
    merged = planning.shot_aligned_plan(
        [scene(durations=(2, 4, 9), constraints=None)], {"display_name": "人物"}
    )
    split = planning.shot_aligned_plan(
        [scene(durations=(20,), constraints=None)], {"display_name": "人物"}
    )

    assert [item["duration_seconds"] for item in merged["segments"]] == [6, 9]
    assert [item["duration_seconds"] for item in split["segments"]] == [10, 10]


def test_constraint_prompt_does_not_invent_face_restriction():
    assert constraint_prompt({"face_policy": "unspecified"}) == ""
