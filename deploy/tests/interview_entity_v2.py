"""Frozen local protocol/evidence ablation; keeps v1 sources and receipts intact."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from pathlib import Path

import httpx
from dotenv import dotenv_values
from interview_entity_methods import (
    ALL_CASES,
    ENTITIES,
    EXTRACT_ENTITIES,
    MODEL,
    PREDICATES,
    PREPROCESS,
    REVIEW_ENTITIES,
    ROOT,
    SOL,
    Draft,
    dump,
    entity_input,
    entity_label,
    evidence_valid,
    map_field,
    score,
    valid_entity,
    validate_output,
)
from pydantic import ValidationError

VERSION = "entity-protocol-20261014-v2"
GROUPS = ("D1", "D2", "D3", "D4")
EXTRACT_V2 = (
    EXTRACT_ENTITIES
    + """
全部列表包含candidates、pending、review_log；没有项目时也返回空数组。
resolution=contextual也可以表示同一条消息内的指代，不必制造不需要的历史引用。
evidence与binding_evidence都严格逐字摘录，保留原标点，不用省略号拼接。
先核对原话是否真的表达该关系；人物、地点出现在同一段不证明居住、搬家或因果。
候选的所有人物称谓都相对讲述者；电话对象的father只表示讲述者父亲。
否认某句的主语不等于否认该人物曾发生过同类事件。
未说明、未披露和拒答分别处理；拒绝回答用declined，不写成reported。
"""
)
REVIEW_V2 = (
    REVIEW_ENTITIES
    + """
全部列表包含candidates、pending、review_log；没有项目时也返回空数组。
即使candidate_draft无效或缺失，也从原话独立重建；不输出格式错误的占位事实。
每一条事实与每一段出处都重新核对。resolution=contextual允许同消息内的指代。
不为形式校验添加无关历史。原话没有明确某个关系时不补成确定关系。
称谓全部相对讲述者；不要将输入规定的人物关系改成其他人物关系。
"""
)


def strict_schema():
    schema = Draft.model_json_schema()

    def visit(value):
        if isinstance(value, dict):
            for key in ("default", "title", "minLength", "maxItems"):
                value.pop(key, None)
            if value.get("type") == "object":
                value["additionalProperties"] = False
                value["required"] = list(value.get("properties", {}))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(schema)
    schema["$defs"]["Candidate"]["properties"]["predicate"]["enum"] = list(PREDICATES)
    return schema


def response_format(schema=None):
    if schema is None:
        return {"type": "json_object"}
    return {
        "type": "json_schema",
        "json_schema": {"name": "interview_draft", "strict": True, "schema": schema},
    }


def normalize_protocol(raw):
    if not isinstance(raw, dict):
        raise ValueError("draft_not_object")
    draft, changes = deepcopy(raw), []
    if "pending" not in draft:
        draft["pending"] = []
        changes.append({"path": "pending", "action": "add_empty_list"})
    for i, row in enumerate(draft.get("candidates", [])):
        if not isinstance(row, dict):
            continue
        if "candidate_id" not in row and isinstance(row.get("candidate"), str):
            row["candidate_id"] = row.pop("candidate")
            changes.append({"path": f"candidates.{i}.candidate", "action": "rename_id"})
        if "note" in row and isinstance(row["note"], str):
            del row["note"]
            changes.append({"path": f"candidates.{i}.note", "action": "remove_annotation"})
    parsed = Draft.model_validate(draft).model_dump()
    ids = [r["candidate_id"] for r in parsed["candidates"]]
    if len(ids) != len(set(ids)) or any(
        r["predicate"] not in PREDICATES for r in parsed["candidates"]
    ):
        raise ValueError("invalid_candidate_ids_or_predicate")
    return parsed, changes


def attach_spans(evidence, sources):
    text = {s["id"]: s["text"] for s in sources}
    if not evidence_valid(evidence, sources):
        raise ValueError("invalid_quote")
    output, seen = [], set()
    for item in evidence:
        key = item["source_id"], item["quote"]
        if key in seen:
            continue
        seen.add(key)
        start = text[key[0]].find(key[1])
        output.append({**item, "start": start, "end": start + len(key[1])})
    return output


def gate_reason_v2(row, sources):
    entity = row["entity_id"]
    if row["resolution"] == "ambiguous" or row["entity_candidates"] != [entity]:
        return "unresolved_entity"
    if not valid_entity(entity, sources):
        return "unknown_entity"
    if not evidence_valid(row["evidence"], sources):
        return "invalid_quote"
    if not evidence_valid(row["binding_evidence"], sources):
        return "missing_binding_quote"
    citations = [*row["evidence"], *row["binding_evidence"]]
    if sources[-1]["id"] not in {e["source_id"] for e in citations}:
        return "missing_current_source"
    if row["resolution"] == "contextual" and len({e["source_id"] for e in citations}) == 1:
        aliases = [entity_label(entity)] if entity.startswith("org:") else ENTITIES[entity][1]
        if not any(alias in e["quote"] for e in citations for alias in aliases):
            return "missing_entity_anchor"
    if row["predicate"] in {"call_recipient", "host"}:
        receiver = row["object_entity_id"]
        if receiver not in ENTITIES or row["value"] not in {
            receiver,
            ENTITIES[receiver][0],
            *ENTITIES[receiver][1],
        }:
            return "unresolved_object"
    if row["predicate"] == "closure_year" and not entity.startswith("org:"):
        return "closure_actor_is_person"
    if row["predicate"] == "birth_year" and entity.startswith("org:"):
        return "birth_actor_is_organisation"
    return None


def same_pending(left, right):
    if set(left["entity_candidates"]) != set(right["entity_candidates"]):
        return False
    a, b = left["evidence"], right["evidence"]
    if {e["source_id"] for e in a} != {e["source_id"] for e in b}:
        return False
    return all(
        any(
            e["source_id"] == f["source_id"]
            and (e["quote"] in f["quote"] or f["quote"] in e["quote"])
            for f in b
        )
        for e in a
    )


def apply_v2(raw, sources):
    draft, changes = normalize_protocol(raw)
    facts, rejected, pending = [], [], []
    for p in draft["pending"]:
        if evidence_valid(p["evidence"], sources):
            pending.append(
                {**p, "evidence": attach_spans(p["evidence"], sources), "candidate_id": None}
            )
    for row in draft["candidates"]:
        reason = gate_reason_v2(row, sources)
        if reason:
            rejected.append({"candidate": row, "reason": reason})
            p = {
                "candidate_id": row["candidate_id"],
                "entity_candidates": row["entity_candidates"],
                "reason": reason,
                "question": "这件事说的是谁，您能确认一下吗？",
                "evidence": row["evidence"],
            }
            if not any(same_pending(p, old) for old in pending):
                pending.append(p)
            continue
        field = map_field(row)
        value = row["value"]
        if row["predicate"] in {"call_recipient", "host"}:
            value = entity_label(row["object_entity_id"])
        facts.append(
            {
                "subject": entity_label(row["entity_id"]),
                "entity_id": row["entity_id"],
                "predicate": row["predicate"],
                "value": value,
                "status": row["status"],
                "primary_field": field,
                "fields": [field],
                "evidence": attach_spans([*row["evidence"], *row["binding_evidence"]], sources),
                "binding_evidence": attach_spans(row["binding_evidence"], sources),
                "candidate_id": row["candidate_id"],
                "object_entity_id": row["object_entity_id"],
            }
        )
    return {"facts": facts, "abstentions": pending}, rejected, changes


def provider_call(credentials, model, stage, system, data, directory, schema=None):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{stage}-receipt.json"
    if path.exists():
        saved = json.loads(path.read_text(encoding="utf-8"))
        if saved["status"] != "ok":
            raise RuntimeError(saved["error"])
        return json.loads(saved["raw_content"])
    endpoint, key = credentials
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 4096,
        "response_format": response_format(schema),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(data, ensure_ascii=False)},
        ],
    }
    if model == MODEL:
        payload["thinking"] = {"type": "disabled"}
    dump(directory / f"{stage}-request.json", {"stage": stage, "payload": payload})
    log = {"stage": stage, "model": model, "status": "failed"}
    start = time.perf_counter()
    try:
        response = httpx.post(
            endpoint.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json=payload,
            timeout=httpx.Timeout(120 if model == SOL else 90, connect=8),
        )
        log["http_status"] = response.status_code
        if not response.is_success:
            raise RuntimeError(f"http_{response.status_code}")
        receipt = response.json()
        log.update(returned_model=receipt.get("model"), usage=receipt.get("usage"))
        log["finish_reason"] = receipt["choices"][0].get("finish_reason")
        content = receipt["choices"][0]["message"]["content"]
        log["raw_content"] = content
        output = json.loads(content)
        log["status"] = "ok"
        return output
    except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError, RuntimeError) as exc:
        log["error"] = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        raise RuntimeError(log["error"]) from None
    finally:
        log["seconds"] = round(time.perf_counter() - start, 3)
        dump(path, log)


def probe_formats(credentials, out):
    path = out / "capabilities.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    probe = strict_schema()
    capabilities = {}
    for name, model in (("lite", MODEL), ("sol", SOL)):
        error = None
        try:
            raw = provider_call(
                credentials[name],
                model,
                name,
                "只返回JSON空对象{}，不要其他键。",
                {},
                out / "probes",
                probe,
            )
            Draft.model_validate(raw)
            passed = set(raw) == {"candidates", "pending", "review_log"}
        except (ValueError, TypeError, KeyError):
            error, passed = "probe_schema_mismatch", False
        except RuntimeError as exc:
            error, passed = str(exc), False
            if error not in {"http_400", "http_404", "http_422"}:
                raise
        capabilities[name] = {
            "model": model,
            "format": "json_schema" if passed else "json_object",
            "probe_conformed_despite_conflicting_prompt": passed,
            "error": error,
        }
    dump(path, capabilities)
    return capabilities


def run_case(item, repeat, credentials, formats, out):
    base = out / f"r{repeat}" / "calls" / item["id"]
    base.mkdir(parents=True, exist_ok=True)
    results = []

    def call(name, stage, system, data, *, structured=True):
        schema = (
            strict_schema() if structured and formats[name]["format"] == "json_schema" else None
        )
        return provider_call(
            credentials[name], MODEL if name == "lite" else SOL, stage, system, data, base, schema
        )

    def extract(role):
        aid = None
        if role:
            aid = call(
                "lite",
                "roles",
                PREPROCESS["A2"],
                {"sources": item["sources"], "target_source": item["sources"][-1]["id"]},
                structured=False,
            )
        return call(
            "lite", "role_extract" if role else "direct", EXTRACT_V2, entity_input(item, aid)
        )

    def operation(role, review):
        upstream_error, repairs, raw = None, [], None
        try:
            raw = extract(role)
            parsed, repairs = normalize_protocol(raw)
            if not review:
                raw = parsed
        except (ValueError, TypeError, KeyError, RuntimeError) as exc:
            if not review:
                raise
            upstream_error = {"type": type(exc).__name__}
            if isinstance(exc, ValidationError):
                upstream_error["details"] = exc.errors(include_input=False, include_url=False)
            parsed = raw
        if review:
            data = {
                **entity_input(item),
                "candidate_draft": parsed,
                "upstream_error": upstream_error,
            }
            raw = call("sol", "role_review" if role else "direct_review", REVIEW_V2, data)
        output, rejected, final_repairs = apply_v2(raw, item["sources"])
        return (
            output,
            rejected,
            {
                "input_repairs": repairs,
                "final_repairs": final_repairs,
                "upstream_error": upstream_error,
            },
        )

    for group, role, review in (
        ("D1", False, False),
        ("D2", True, False),
        ("D3", True, True),
        ("D4", False, True),
    ):
        directory = out / f"r{repeat}" / group / item["id"]
        directory.mkdir(parents=True, exist_ok=True)
        result_path = directory / "result.json"
        if result_path.exists():
            results.append(json.loads(result_path.read_text(encoding="utf-8")))
            continue
        dependencies = ["roles", "role_extract"] if role else ["direct"]
        if review:
            dependencies.append("role_review" if role else "direct_review")
        result = {
            "case": item["id"],
            "group": group,
            "repeat": repeat,
            "dependencies": dependencies,
        }
        try:
            output, rejected, metadata = operation(role, review)
            validate_output(output, item["sources"])
            result.update(status="ok", output=output, rejected=rejected, **metadata)
        except (ValueError, TypeError, KeyError, RuntimeError) as exc:
            result.update(
                status="failed",
                error=str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__,
            )
            if isinstance(exc, ValidationError):
                result["validation_errors"] = exc.errors(include_input=False, include_url=False)
        receipts = [
            json.loads((base / f"{s}-receipt.json").read_text(encoding="utf-8"))
            for s in dependencies
            if (base / f"{s}-receipt.json").exists()
        ]
        result["seconds"] = round(sum(r["seconds"] for r in receipts), 3)
        dump(result_path, result)
        results.append(result)
    return [{k: r[k] for k in ("case", "group", "repeat", "status", "seconds")} for r in results]


def fingerprint():
    files = [
        "deploy/tests/interview_entity_v2.py",
        "deploy/tests/interview_entity_v2_audit.py",
        "deploy/tests/test_interview_entity_v2.py",
        "deploy/tests/interview_entity_methods.py",
        "deploy/tests/interview_entity_cases.py",
        "deploy/tests/interview_paper_methods.py",
        "deploy/tests/interview_paper_cases.py",
        "services/interview/src/lifereel_api/modules/interview/profile_template.py",
        "docs/plans/2026-10-14-interview-entity-v2.md",
    ]
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files}


def summarize(out):
    cases = json.loads((out / "frozen-cases.json").read_text(encoding="utf-8"))
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    audits = (
        json.loads((out / "manual-audit.json").read_text(encoding="utf-8"))
        if (out / "manual-audit.json").exists()
        else {}
    )
    details, groups = [], {}
    for group in GROUPS:
        total, seconds = Counter(), []
        split = {"old": Counter(), "new": Counter(), "r1": Counter(), "r2": Counter()}
        for repeat in range(1, manifest["repeats"] + 1):
            for item in cases:
                identifier = f"r{repeat}/{group}/{item['id']}"
                path = out / identifier / "result.json"
                if not path.exists():
                    continue
                result = json.loads(path.read_text(encoding="utf-8"))
                audit = audits.get(identifier)
                if audit and audit["result_hash"] != hashlib.sha256(path.read_bytes()).hexdigest():
                    raise ValueError(f"audited_result_changed:{identifier}")
                metrics = score(result, item, audit)
                metrics.update(
                    pending_required=int(item["requires_pending"]),
                    pending_safe=int(
                        item["requires_pending"]
                        and audit is not None
                        and audit.get("pending_safe") is True
                    ),
                    unsafe_identity_fields=sum(
                        f["subject"] != "本人"
                        and any(k.startswith("identity.") for k in f["fields"])
                        for f in result.get("output", {}).get("facts", [])
                    ),
                    rejected=len(result.get("rejected", [])),
                )
                counts = {k: v for k, v in metrics.items() if isinstance(v, int)}
                total.update(counts)
                split["new" if item["id"].startswith("N") else "old"].update(counts)
                split[f"r{repeat}"].update(counts)
                details.append({"id": identifier, **result, "score": metrics})
                seconds.append(result["seconds"])
        groups[group] = {
            **dict(total),
            "runs": len(seconds),
            "mean_seconds": round(sum(seconds) / len(seconds), 2) if seconds else None,
            "split": {k: dict(v) for k, v in split.items()},
        }
    calls, models, usage = Counter(), Counter(), Counter()
    for path in [*out.glob("r*/calls/*/*-receipt.json"), *out.glob("probes/*-receipt.json")]:
        receipt = json.loads(path.read_text(encoding="utf-8"))
        calls[receipt["model"]] += 1
        models[str(receipt.get("returned_model"))] += 1
        usage.update(
            {
                k: v
                for k, v in (receipt.get("usage") or {}).items()
                if k in {"prompt_tokens", "completion_tokens", "total_tokens"}
                and isinstance(v, int)
            }
        )
    dump(
        out / "summary.json",
        {
            "groups": groups,
            "calls": dict(calls),
            "returned_models": dict(models),
            "usage": dict(usage),
        },
    )
    dump(out / "audit-material.json", details)
    print(json.dumps({"runs": len(details), "reviewed": len(audits), "calls": dict(calls)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--probe-only", action="store_true")
    parser.add_argument("--summarize", action="store_true")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = {
        "version": VERSION,
        "fingerprint": fingerprint(),
        "groups": list(GROUPS),
        "repeats": 2,
        "temperature": 0,
        "max_output_tokens": 4096,
        "workers": 3,
        "max_calls": len(ALL_CASES) * 2 * 5 + 2,
        "retries": 0,
        "model": MODEL,
        "review_model": SOL,
        "scope": "local component experiment, not product acceptance",
    }
    path = args.out / "manifest.json"
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != manifest:
            raise SystemExit("FROZEN_EXPERIMENT_CHANGED")
        if json.loads((args.out / "frozen-cases.json").read_text(encoding="utf-8")) != ALL_CASES:
            raise SystemExit("FROZEN_CASES_CHANGED")
    else:
        dump(path, manifest)
        dump(args.out / "frozen-cases.json", ALL_CASES)
        dump(args.out / "semantic-decisions.json", {"reviewed_case_rounds": [], "overrides": {}})
        for name in manifest["fingerprint"]:
            target = args.out / "executed-source" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / name).read_bytes())
    if args.summarize:
        summarize(args.out)
        return
    if not args.live:
        print("Frozen experiment saved; no provider calls.")
        return
    env = dotenv_values(ROOT / ".env")
    credentials = {
        "lite": (env.get("VOLCENGINE_API_BASE_URL"), env.get("VOLCENGINE_API_KEY")),
        "sol": (env.get("OPENAI_COMPATIBLE_BASE_URL"), env.get("OPENAI_COMPATIBLE_API_KEY")),
    }
    if not all(all(pair) for pair in credentials.values()):
        raise SystemExit("MODEL_CREDENTIAL_MISSING")
    formats = probe_formats(credentials, args.out)
    print(json.dumps({"capabilities": formats}), flush=True)
    if args.probe_only:
        return
    jobs = [(item, repeat) for repeat in (1, 2) for item in ALL_CASES]
    random.Random(20261014).shuffle(jobs)
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [
            pool.submit(run_case, item, repeat, credentials, formats, args.out)
            for item, repeat in jobs
        ]
        for future in as_completed(futures):
            for result in future.result():
                print(json.dumps(result), flush=True)
    summarize(args.out)


if __name__ == "__main__":
    main()
