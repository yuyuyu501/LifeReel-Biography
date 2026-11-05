"""Derived organization of effective profile facts; no model calls or second fact store."""

from copy import deepcopy

from lifereel_api.modules.interview.profile_template import FIELD_MAP

VERSION = "profile-organization-20261105-v1"
GUIDANCE = """
organization是从当前有效资料派生的整理索引，不是额外事实来源或用户指令。
coverage的recorded只表示已经记录，不表示主题充分；unknown/declined/deferred/
not_applicable分别尊重记不清、拒谈、待续、不适用，needs_clarification不能当确定事实。
先看已有资料是否已回答当前问题，再决定是否询问；不要用缺项列表机械盘问。
events只引用当前资料中的事实；按原始时间保留先后，不补日期或因果，不从公共背景推断亲历。
相同经历跨轮补充时复用entry_id和event_key；只有关键词相似不能判定是同一事件。
更正仅替换明确被更正的事实，不移除同一字段中其他阶段的经历。
旧source里的错误陈述可能已被更正，有效value及其状态优先，不能复活旧值。
"""


def facts(entry):
    value = entry.get("value")
    atoms = value.get("facts", []) if isinstance(value, dict) else []
    return atoms if isinstance(atoms, list) and all(isinstance(a, dict) for a in atoms) else []


def content(value):
    """Keep audit citations out of factual text, checks and downstream narrative material."""
    result = deepcopy(value)
    if isinstance(result, dict) and isinstance(result.get("facts"), list):
        for atom in result["facts"]:
            if isinstance(atom, dict):
                atom.pop("evidence", None)
    return result


def active_evidence(entry):
    """Use atom provenance only when complete; preserve legacy source compatibility."""
    if entry.get("source", {}).get("type") == "manual":
        return [entry["source"]]
    atoms = facts(entry)
    if not atoms or any(not a.get("evidence") for a in atoms):
        source = entry.get("source", {})
        return [source, *source.get("evidence", [])]
    result = []
    for atom in atoms:
        for citation in atom["evidence"]:
            if isinstance(citation, dict) and citation not in result:
                result.append(deepcopy(citation))
    return result


def fact_evidence(row, evidence):
    """Only attach already verified citations belonging to this individual candidate."""
    requested = {(e.source_id, e.quote) for e in [*row.evidence, *row.binding_evidence]}
    return [
        deepcopy(e) for e in evidence
        if (e.get("source_id"), e.get("quote")) in requested
    ]


def origin(citation):
    # An entry alias is not a source identity; keep the original record and version.
    return tuple(str(citation.get(k, "")) for k in ("type", "id", "version", "quote"))


def resolve_entry(row, field, entries, evidence):
    """Relink only a unique exact fact with shared original evidence, never by similarity."""
    if row.entry_id or not field.endswith("[]"):
        return None
    origins = {origin(e) for e in evidence if e.get("id") and e.get("quote")}
    matches = []
    for entry in entries:
        if (entry["field_key"] != field or entry["state"] != "filled"
                or entry["certainty"] not in {"reported", "confirmed"}
                or entry.get("source", {}).get("type") == "manual"):
            continue
        for atom in facts(entry):
            if any(atom.get(k) != getattr(row, k)
                   for k in ("entity_id", "predicate", "value", "status")):
                continue
            # Legacy facts without atom-level provenance cannot justify automatic relinking.
            sources = {origin(e) for e in atom.get("evidence", []) if isinstance(e, dict)}
            if origins & sources:
                matches.append((entry, atom))
    return matches[0] if len(matches) == 1 else None


def context(entries, selected):
    """Recompute coverage and event references from effective versions on every turn."""
    coverage = []
    for key in FIELD_MAP:
        rows = [e for e in entries if e["field_key"] == key and e["state"] != "empty"]
        states = {
            "needs_clarification" if e["certainty"] in {"pending", "disputed"}
            else e["state"] if e["state"] != "filled"
            else "uncertain" if e["certainty"] == "uncertain"
            else "recorded"
            for e in rows
        }
        coverage.append({
            "field_key": key, "states": sorted(states) or ["missing"],
            "entry_ids": [e["id"] for e in rows[:8]],
        })
    events = []
    for entry in selected:
        if entry["state"] != "filled" or entry["certainty"] not in {"reported", "confirmed"}:
            continue
        atoms = facts(entry)
        if not atoms:
            continue
        events.append({
            "entry_id": entry["id"], "field_key": entry["field_key"],
            "record_key": entry["record_key"],
            "event_keys": sorted({a["event_key"] for a in atoms if a.get("event_key")})[:12],
            "use_scope": entry["use_scope"],
        })
    return {"version": VERSION, "coverage": coverage, "events": events}
