"""Current facts for model input; original conversations and quotations stay intact."""


def fact_text(claim):
    return getattr(claim, "current_text", claim.claim_text)


def fact_evidence(claim):
    corrections = getattr(claim, "fact_overrides", None) or []
    return {
        "claim_text": fact_text(claim),
        # Never label an amended summary as a quotation of the original source.
        "source_quote": "" if corrections else claim.source_quote,
        "correction_evidence": [
            {"claim_id": item["correction_claim_id"], "quote": item["evidence_quote"]}
            for item in corrections
        ],
    }


def apply_corrections(claims, corrections):
    """Apply already validated, source-bound patches without dropping unrelated facts."""
    by_id = {str(claim.id): claim for claim in claims}
    for item in corrections:
        target = by_id[item["target_claim_id"]]
        source = by_id[item["correction_claim_id"]]
        patch = {
            "old_text": item["old_text"], "new_text": item["new_text"],
            "correction_claim_id": str(source.id),
            "source_revision": source.source_revision,
            "target_revision": target.source_revision,
            "evidence_quote": item["evidence_quote"],
            "conflict_keys": item["conflict_keys"],
        }
        if patch not in (target.fact_overrides or []):
            target.fact_overrides = [*(target.fact_overrides or []), patch]
