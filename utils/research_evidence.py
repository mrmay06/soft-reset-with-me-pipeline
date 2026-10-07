"""Honest evidence labels for topic generation without source retrieval."""

import re


_FACTUAL_MARKERS = re.compile(
    r"\b(?:research|studies|science)\s+(?:shows?|proves?|says?|confirms?)\b"
    r"|\b\d+(?:\.\d+)?\s*(?:%|percent\b)"
    r"|\b(?:dopamine|cortisol|oxytocin)\b"
    r"|\bnervous system\b.{0,80}\b(?:learned|trained|rewired|regulat\w*)\b",
    re.IGNORECASE,
)


def normalize_research_basis(result: dict) -> dict:
    # This pipeline does not fetch papers or validate cited claims. A model's
    # confidence, organization name, or URL must not manufacture verification.
    result = dict(result)
    suggested_url = result.get("source_url")
    if suggested_url:
        result["suggested_source_url"] = suggested_url
    result["source_url"] = ""
    result["fact_year"] = None
    result["confidence_level"] = "observational"
    basis = result.get("content_basis", "emotional_observation")
    # Conservative tripwire, not a verifier or an exhaustive claim classifier.
    text = " ".join(str(result.get(key, "")) for key in
                    ("topic", "core_claim", "editorial_seed", "hook_seed", "retention_hook", "source_fact"))
    if _FACTUAL_MARKERS.search(text):
        basis = "factual_claim"
        result["evidence_warning"] = "Explicit empirical or biological wording needs verification or an emotional reframe"
    result["content_basis"] = basis if basis in {"emotional_observation", "factual_claim"} else "factual_claim"
    result["evidence_status"] = "not_required" if result["content_basis"] == "emotional_observation" else "unverified"
    return result
