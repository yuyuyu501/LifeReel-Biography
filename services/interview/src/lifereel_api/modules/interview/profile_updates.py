"""Preserve sourced detail before AI candidates undergo independent review."""

import json
import re
from copy import deepcopy

NARRATIVE_KEYS = frozenset(
    {
        "what",
        "story",
        "action",
        "result",
        "impact",
        "feelings",
        "description",
    }
)
CORRECTION = re.compile(
    r"更正|记错|改成|修正|修改(?:资料|记录|年份|时间|地点)|"
    r"不是[^。！？!?；;\n]{1,30}(?:而是|应该是)|"
    r"(?:刚才|之前|先前)[^。！？!?；;\n]{0,15}应该是"
)


def correction(quote):
    return bool(CORRECTION.search(quote))


def narrative(old, new):
    def normalized(value):
        return re.sub(r"[\s，。；,.;]", "", value)

    if normalized(new) in normalized(old):
        return old
    if normalized(old) in normalized(new):
        return new
    pieces = old.split("\n")
    for part in new.split("\n"):
        if normalized(part) and not any(normalized(part) in normalized(p) for p in pieces):
            pieces.append(part)
    return "\n".join(pieces)


def merge(old, new, *, corrected=False, narrative_field=False):
    if isinstance(old, list) and isinstance(new, dict):
        return merge(old, [new], corrected=corrected, narrative_field=narrative_field)
    if isinstance(old, dict) and isinstance(new, list):
        return merge([old], new, corrected=corrected, narrative_field=narrative_field)
    if isinstance(old, dict) and isinstance(new, dict):
        result = deepcopy(old)
        for key, value in new.items():
            result[key] = (
                merge(old[key], value, corrected=corrected, narrative_field=key in NARRATIVE_KEYS)
                if key in old
                else deepcopy(value)
            )
        return result
    if isinstance(old, list) and isinstance(new, list):
        if corrected and not all(isinstance(item, dict) for item in old + new):
            return deepcopy(new)
        result = deepcopy(old)
        for value in new:
            matches = []
            if isinstance(value, dict):
                for key in ("id", "person", "name", "title"):
                    if value.get(key):
                        matches = [
                            i
                            for i, item in enumerate(result)
                            if isinstance(item, dict) and item.get(key) == value[key]
                        ]
                        if matches:
                            break
            if len(matches) == 1:
                position = matches[0]
                result[position] = merge(result[position], value, corrected=corrected)
            elif value not in result:
                result.append(deepcopy(value))
        return result
    if isinstance(old, str) and isinstance(new, str) and narrative_field and not corrected:
        return narrative(old, new)
    if narrative_field and not corrected and type(old) is not type(new):
        return merge(
            old if isinstance(old, list) else [old], new if isinstance(new, list) else [new]
        )
    return deepcopy(new)


def retain(output, material, narrative_fields):
    retained = []
    for index, change in enumerate(output["changes"]):
        if change["state"] != "filled":
            continue
        current = next(
            (
                e
                for e in material["current_entries"]
                if (
                    e["field_key"] == change["field_key"]
                    and e.get("record_key", "single") == change.get("record_key", "single")
                    and e["state"] == "filled"
                    and e["certainty"] in {"reported", "confirmed"}
                )
            ),
            None,
        )
        if not current:
            continue
        corrected = correction(change["quote"])
        old = deepcopy(current["value"])
        dates = re.search(
            r"不是\s*(\d{4})年?[^。！？!?]{0,15}?(?:应该是|而是|改成)\s*(\d{4})年?",
            change["quote"],
        )
        if corrected and dates and dates[1] in json.dumps(old, ensure_ascii=False):

            def replace_date(value, old_year=dates[1], new_year=dates[2]):
                if isinstance(value, str):
                    return re.sub(rf"(?<!\d){old_year}(?!\d)", new_year, value)
                if isinstance(value, dict):
                    return {k: replace_date(v) for k, v in value.items()}
                if isinstance(value, list):
                    return [replace_date(v) for v in value]
                return value

            old = replace_date(old)
        merged = merge(
            old,
            change["value"],
            corrected=corrected,
            narrative_field=change["field_key"] in narrative_fields,
        )
        if len(json.dumps(merged, ensure_ascii=False)) > 12000:
            raise ValueError("profile_value_too_large")
        if merged != change["value"]:
            change["value"] = merged
            retained.append(index)
    return retained


def evidence(previous, current, *, corrected=False, retained_keys=()):
    # A correction retires the old effective evidence; revision history keeps it.
    preserve = not corrected or bool(retained_keys)
    items = list(previous.get("evidence", [])) if preserve else []
    if corrected and retained_keys:
        items = [{**item, "retained_keys": list(retained_keys)} for item in items]
    for source in ([previous] if preserve else []) + [current]:
        item = {k: v for k, v in source.items() if k in {"type", "id", "version", "quote", "actor"}}
        if corrected and retained_keys and source is previous:
            item["retained_keys"] = list(retained_keys)
        if item and item not in items:
            items.append(item)
    return items


def requested_name(change):
    if change["field_key"] != "identity.preferred_name" or not isinstance(change["value"], str):
        return False
    match = re.search(
        r"(?:书(?:中|里|上)(?:就)?(?:叫|称呼)(?:我|为)?|叫我|称呼我|名字用|称呼用)"
        r"\s*([^，。；;！？!?\n]{1,100})",
        change["quote"],
    )
    return bool(
        match and re.sub(r"(?:就行|就好|即可)$", "", match[1]).strip() == change["value"].strip()
    )


def normalize_candidates(raw, answer, narrative_fields):
    if not isinstance(raw, dict) or not isinstance(raw.get("changes"), list):
        return raw, 0
    normalized, repaired = [], 0
    for item in raw["changes"]:
        if not isinstance(item, dict):
            normalized.append(item)
            continue
        # Storage metadata sometimes gets echoed; it must never authorize a source.
        change = {
            k: v for k, v in item.items() if k not in {"source", "source_id", "version_number"}
        }
        quote = change.get("quote")
        if (
            not change.get("value")
            and isinstance(quote, str)
            and quote in answer
            and change.get("state", "filled") == "filled"
        ):
            if change.get("field_key") == "identity.preferred_name":
                match = re.fullmatch(
                    r"(?:书(?:中|里|上)(?:就)?(?:叫|称呼)(?:我|为)?|叫我|称呼我)"
                    r"\s*([^，。；;！？!?\n]{1,100})[。.]?",
                    quote,
                )
                if match:
                    change["value"] = re.sub(r"(?:就行|就好|即可)$", "", match[1]).strip()
            elif change.get("field_key") in narrative_fields:
                change["value"] = quote
        repaired += change != item
        normalized.append(change)
    return {**raw, "changes": normalized}, repaired


def coalesce(output, answer, narrative_fields):
    combined, indices = [], {}
    for change in output["changes"]:
        key = (change["field_key"], change["record_key"])
        eligible = key[1] == "single" and key[0] in narrative_fields | {"legacy.open_threads"}
        if not eligible or key not in indices:
            indices[key] = len(combined)
            combined.append(change)
            continue
        prior = combined[indices[key]]
        if any(prior[k] != change[k] for k in ("state", "certainty", "use_scope", "pseudonyms")):
            raise ValueError("incompatible_duplicate_changes")
        starts = [answer.find(c["quote"]) for c in (prior, change)]
        if min(starts) < 0:
            raise ValueError("unsupported_quote")
        stop = max(
            start + len(c["quote"]) for start, c in zip(starts, (prior, change), strict=True)
        )
        quote = answer[min(starts) : stop]
        if len(quote) > 3000:
            raise ValueError("profile_quote_too_large")
        if isinstance(prior["value"], str) and isinstance(change["value"], str):
            value = narrative(prior["value"], change["value"])
        else:
            values = prior["value"] if isinstance(prior["value"], list) else [prior["value"]]
            value = values + ([change["value"]] if change["value"] not in values else [])
        combined[indices[key]] = {**prior, "value": value, "quote": quote}
    output["changes"] = combined
    return output
