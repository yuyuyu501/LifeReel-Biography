"""Bounded real-provider recording comparison; synthetic profiles and private receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path
from uuid import UUID, uuid4

from interview_grounding_experiment import (
    CALL_DIRECTORY,
    FILES,
    ROOT,
    bootstrap,
    dump,
    receipt_transport,
)

GROUPS = ("baseline", "combined")
CASES = [
    {
        "id": "V01", "name": "贺秋禾",
        "answers": [
            "书里叫我贺秋禾。我1968年出生，在衡阳长大。1989年进了一家印刷厂工作。"
            "沈师傅教我装订旧书，我每天负责裁纸和装订。",
            "那家印刷厂的全名是衡阳长风印刷厂。跟沈师傅学装订这件事没变。",
        ],
        "targets": [
            ["书中称呼贺秋禾", ["identity.preferred_name"]],
            ["本人1968年出生", ["identity.birth_time"]],
            ["本人在衡阳长大", ["identity.birth_place"]],
            ["本人1989年入职", ["work.records[]"]],
            ["该单位完整名称衡阳长风印刷厂", ["work.records[]"]],
            ["沈师傅教本人装订旧书", ["learning.teachers[]"]],
            ["本人负责裁纸", ["work.responsibilities"]],
            ["本人负责装订", ["work.responsibilities"]],
        ],
        "checks": ["名称细化不变disputed", "老师不进家人", "重申不重复", "职责不漏记"],
    },
    {
        "id": "V02", "name": "唐素清",
        "answers": [
            "家里有张1998年春节的纸质合影，还没上传。现在我做事喜欢先列个小清单。"
            "我以前工作的荣新织布厂2006年停产，但我早在2002年就离开了。",
        ],
        "targets": [
            ["有纸质合影", ["legacy.open_threads", "materials.captions"]],
            ["该合影是1998年春节的", ["legacy.open_threads", "materials.captions"]],
            ["该合影未上传", ["legacy.open_threads"]],
            ["当前做事习惯先列小清单", ["present.daily_life"]],
            ["本人以前在荣新织布厂工作", ["work.records[]"]],
            ["荣新织布厂2006年停产", ["work.records[]"]],
            ["本人2002年已经离职", ["work.records[]"]],
        ],
        "checks": ["单位不是家人", "照片和习惯不是工作", "停产与离职年份分开", "无虚构上传资产"],
    },
    {
        "id": "V03", "name": "姚慧宁",
        "answers": [
            "女儿叫小岚，2012年搬到芜湖，住在我弟弟家。",
            "她现在是否还住在芜湖，我不知道。晚上通常是她给我打电话，不是我给她打。",
        ],
        "targets": [
            ["女儿叫小岚", ["family.members[]"]],
            ["女儿2012年搬迁", ["family.members[]"]],
            ["女儿迁往芜湖", ["family.members[]"]],
            ["女儿住在讲述者弟弟家", ["family.members[]"]],
            ["女儿目前是否仍住芜湖未知", ["present.relationships"]],
            ["通常晚上通话", ["present.relationships", "present.daily_life"]],
            ["通常女儿打给本人", ["present.relationships"]],
            ["否定本人通常主动打给女儿", ["present.relationships", "present.daily_life"]],
        ],
        "checks": ["指代引文保留女儿前因", "不把历史居住当当前", "电话方向不反转"],
    },
    {
        "id": "V04", "name": "程冬梅",
        "answers": [
            "我2004年欠过债，原因不想讲。欠债这段只留内部资料，不写进书。",
            "原因还是不愿谈。我家有本1979年的手写菜谱，现在还没上传，下次可以聊它。",
            "把刚才欠债年份更正为2005年，其他不用改。今天先聊到这里。",
        ],
        "targets": [
            ["欠债年份有效值2005年", ["turning.hardships[]"]],
            ["欠债原因拒答", ["turning.hardships[]"]],
            ["欠债不写进作品的限制", ["preferences.exclusions"]],
            ["有手写菜谱", ["legacy.open_threads", "materials.captions"]],
            ["菜谱是1979年的", ["legacy.open_threads", "materials.captions"]],
            ["菜谱未上传", ["legacy.open_threads"]],
            ["下次可聊菜谱", ["legacy.open_threads"]],
        ],
        "checks": ["拒答去重且不追问原因", "欠债保持internal", "更正不丢原因状态和隐私",
                   "结束后不追问", "素材不假称已上传"],
    },
    {
        "id": "V05", "name": "陆知安",
        "answers": ["我1991年进了青禾修理厂。", "我1992年进的青禾修理厂。"],
        "targets": [],
        "checks": ["年份差异待澄清", "保留两次陈述出处", "不借细化或重申偷偷改年"],
    },
]


def freeze(out):
    sources = list(dict.fromkeys([*FILES,
        "deploy/tests/interview_verification_experiment.py",
        "services/model-gateway/src/lifereel_api/providers/openai_compatible.py",
        "services/model-gateway/src/lifereel_api/providers/internal.py",
        "services/interview/src/lifereel_api/modules/interview/profile_updates.py",
        "services/interview/src/lifereel_api/modules/interview/profile_template.py",
        "services/interview/src/lifereel_api/modules/interview/companion.py",
        "docs/plans/2026-10-14-d4-verification.md", "docs/interview-acceptance.md",
    ]))
    manifest = {
        "version": "verification-20261014-v1", "groups": GROUPS, "cases": CASES,
        "hashes": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in sources},
        "limits": {"max_provider_calls": 40, "automatic_retries": 0,
                   "consecutive_failure_stop": 2, "enhanced_review_output_tokens": 8192,
                   "other_output_tokens": 4096},
    }
    path = out / "frozen.json"
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != json.loads(json.dumps(manifest)):
            raise ValueError("sources_changed_use_new_directory")
    else:
        dump(path, manifest)
        with zipfile.ZipFile(out / "frozen-runtime.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            for p in sources:
                archive.write(ROOT / p, p)
            archive.write(path, "frozen.json")


def run(case, group, out):
    from fastapi.testclient import TestClient

    from lifereel_api.core.config import get_settings
    from lifereel_api.core.database import Base, SessionLocal, engine
    from lifereel_api.core.errors import ApiError
    from lifereel_api.main import app
    from lifereel_api.modules.interview import profile_service
    from lifereel_api.modules.interview.models import InterviewRound, InterviewTurnWorkflow
    from lifereel_api.modules.interview.profile_extraction import process

    directory = out / "recording" / group / case["id"]
    if (directory / "result.json").exists():
        return
    if list(directory.glob("turn-*/*-request.json")):
        raise RuntimeError("unfinished_paid_sequence_requires_inspection")
    settings = get_settings()
    settings.interview_d4_enhancement = group
    records, failures = [], 0
    Base.metadata.drop_all(bind=engine)
    with TestClient(app) as client:
        person = client.post("/v1/persons", json={"display_name": "核查合成人物"})
        person.raise_for_status()
        response = client.post("/v1/interviews", json={"subject_id": person.json()["id"]})
        response.raise_for_status()
        session = response.json()
        question = "您愿意先讲哪段经历？"
        for turn, answer in enumerate(case["answers"], 1):
            turn_dir = directory / f"turn-{turn:02d}"
            token = CALL_DIRECTORY.set(turn_dir)
            try:
                with SessionLocal() as db:
                    row = InterviewRound(tenant_id=settings.default_tenant_id,
                        session_id=UUID(session["id"]), round_index=turn + 1,
                        question_text=question, answer_text=answer, answer_version=1)
                    db.add(row)
                    db.commit()
                    request_id = uuid4()
                    workflow = InterviewTurnWorkflow(tenant_id=settings.default_tenant_id,
                        session_id=UUID(session["id"]), round_id=row.id,
                        idempotency_key=str(request_id), status="running", profile_result={})
                    db.add(workflow)
                    db.commit()
                    try:
                        result = process(
                            db, settings.default_tenant_id, UUID(session["profile_id"]), answer,
                            {"type": "interview_round", "id": str(row.id), "version": 1},
                            request_id, workflow=workflow,
                        )
                        workflow.status = "completed"
                    except ApiError as exc:
                        result = {"profile": profile_service.read(db, settings.default_tenant_id,
                            UUID(session["profile_id"])), "audit": workflow.profile_result.get(
                                "audit", {}), "next_question": "这轮记录未完成，待核对。",
                            "error": exc.code.value}
                        workflow.status = "failed"
                    db.commit()
                record = {"turn": turn, "answer": answer, "question": question, "result": result,
                          "tester_initiated": True}
                dump(turn_dir / "result.json", record)
                records.append(record)
                refreshed = client.get(f"/v1/life-profiles/{session['profile_id']}")
                refreshed.raise_for_status()
                assert refreshed.json()["entries"] == result["profile"]["entries"]
                question = result["next_question"]
                verdict = result["audit"].get("verdict")
                print(json.dumps({"case": case["id"], "group": group, "turn": turn,
                                  "verdict": verdict}, ensure_ascii=True), flush=True)
                failures = failures + 1 if verdict != "pass" else 0
                if failures >= 2:
                    break
            finally:
                CALL_DIRECTORY.reset(token)
    dump(directory / "result.json", {"case": case["id"], "group": group, "turns": records,
        "planned_turns": len(case["answers"]), "completed_turns": len(records),
        "profile": records[-1]["result"]["profile"]})


def inspect(out):
    for path in sorted(out.glob("recording/*/*/result.json")):
        result = json.loads(path.read_text(encoding="utf-8"))
        print(json.dumps({"id": f"{result['group']}/{result['case']}", "turns": [
            {"turn": r["turn"], "verdict": r["result"]["audit"].get("verdict"),
             "question": r["result"]["next_question"],
             "rejected": r["result"]["audit"].get("rejected_candidates", [])}
            for r in result["turns"]], "entries": [
                {k: e[k] for k in (
                    "field_key", "value", "state", "certainty", "use_scope", "source"
                )}
                for e in result["profile"]["entries"] if e["source"].get("type") != "person"
            ]}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--cases", nargs="*", choices=[c["id"] for c in CASES])
    parser.add_argument("--groups", nargs="*", choices=GROUPS)
    args = parser.parse_args()
    out = args.out.resolve()
    if not out.is_relative_to(ROOT / "tmp"):
        raise ValueError("receipts_must_stay_in_ignored_tmp")
    if args.inspect:
        inspect(out)
        return
    freeze(out)
    if not args.live:
        print("Frozen. Real-provider requests require --live.")
        return
    _, isolated = bootstrap()
    receipt_transport()
    try:
        selected_cases = [c for c in CASES if not args.cases or c["id"] in args.cases]
        selected_groups = tuple(args.groups or GROUPS)
        # Reverse group order on alternating cases to reduce a systematic order effect.
        for i, case in enumerate(selected_cases):
            order = selected_groups if i % 2 == 0 else tuple(reversed(selected_groups))
            for group in order:
                run(case, group, out)
    finally:
        isolated.pytest_sessionfinish()


if __name__ == "__main__":
    main()
