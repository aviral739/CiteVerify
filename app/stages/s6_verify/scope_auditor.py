"""Scope auditing for scientific claims against retrieved evidence passages.

Detects overgeneralization, population mismatches (e.g. animal/in vitro to human),
causal overreach from correlational evidence, and removal of scientific hedging.
"""

import re
from typing import List, Optional
from pydantic import BaseModel, Field


class ScopeAuditResult(BaseModel):
    """Result of scientific scope and qualifier auditing."""
    status: str = "consistent"  # "consistent", "overgeneralized", "hedged", "context_mismatch"
    details: str
    hedges_in_evidence: List[str] = Field(default_factory=list)
    hedges_in_claim: List[str] = Field(default_factory=list)
    conditions_in_evidence: List[str] = Field(default_factory=list)
    conditions_in_claim: List[str] = Field(default_factory=list)


# Animal and in-vitro model indicators
_PRECLINICAL_MODELS = [
    r"\bmice\b", r"\bmouse\b", r"\bmurine\b", r"\brats?\b", r"\brodents?\b",
    r"\bin\s+vitro\b", r"\bcell\s+culture\b", r"\bcell\s+lines?\b",
    r"\borganoids?\b", r"\bzebrafish\b", r"\bdrosophila\b", r"\bnon-human\s+primates?\b",
    r"\bcanine\b", r"\bporcine\b", r"\bex\s+vivo\b"
]

# Human clinical indicators
_HUMAN_CLINICAL = [
    r"\bhumans?\b", r"\bpatients?\b", r"\bclinical\s+trials?\b",
    r"\bparticipants?\b", r"\bcohort\b", r"\bmen\b", r"\bwomen\b",
    r"\bchildren\b", r"\badults?\b", r"\bin\s+vivo\s+human\b"
]

# Correlational / associative terms
_CORRELATION_TERMS = [
    r"\bassociated\s+with\b", r"\bcorrelated\s+with\b", r"\blinked\s+to\b",
    r"\bco-occur(?:red|ring)?\b", r"\bpositive\s+correlation\b",
    r"\bnegative\s+correlation\b", r"\brelationship\s+between\b"
]

# Direct causal terms
_CAUSAL_TERMS = [
    r"\bcauses?\b", r"\bcaused\b", r"\bcausing\b",
    r"\bleads?\s+to\b", r"\bled\s+to\b",
    r"\binduces?\b", r"\binduced\b",
    r"\bprevents?\b", r"\bprevented\b",
    r"\bcures?\b", r"\bcured\b",
    r"\bdrives?\b", r"\bdriven\s+by\b"
]

# Hedging and uncertainty terms
_HEDGE_TERMS = [
    r"\bmay\b", r"\bmight\b", r"\bcould\b",
    r"\bsuggests?\b", r"\bsuggested\b",
    r"\bindicates?\s+that\b", r"\bpreliminary\b",
    r"\bpilot\s+study\b", r"\bexploratory\b",
    r"\bpotential(?:ly)?\b", r"\bhypothesized\b",
    r"\btentative(?:ly)?\b", r"\bpartially\b"
]

# Definitive certainty terms
_DEFINITIVE_TERMS = [
    r"\bproves?\b", r"\bproven\b",
    r"\bdemonstrates?\s+conclusively\b",
    r"\bestablishes?\s+beyond\s+doubt\b",
    r"\balways\b", r"\binvariably\b",
    r"\bdefinitive(?:ly)?\b", r"\birrefutable\b"
]


def _find_matches(patterns: List[str], text: str) -> List[str]:
    """Find all matching pattern strings in text."""
    found = []
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            found.append(m.group(0).lower())
    return found


def audit_scope(
    claim_text: str,
    evidence_text: str,
    claim_qualifiers: Optional[List[str]] = None,
    claim_conditions: Optional[str] = None
) -> ScopeAuditResult:
    """Audit whether a claim preserves the scope, population, and hedging of evidence."""
    if not evidence_text or not evidence_text.strip():
        return ScopeAuditResult(
            status="consistent",
            details="No evidence passage available to evaluate scope."
        )

    full_claim_ctx = f"{claim_text} {claim_conditions or ''} {' '.join(claim_qualifiers or [])}"

    # Extract preclinical vs human indicators
    preclinical_in_ev = _find_matches(_PRECLINICAL_MODELS, evidence_text)
    preclinical_in_claim = _find_matches(_PRECLINICAL_MODELS, full_claim_ctx)
    human_in_claim = _find_matches(_HUMAN_CLINICAL, full_claim_ctx)
    human_in_ev = _find_matches(_HUMAN_CLINICAL, evidence_text)

    # 1. Animal / In-vitro to Human / General Overgeneralization
    if preclinical_in_ev and not human_in_ev:
        # Evidence was conducted solely in preclinical models
        if human_in_claim and not preclinical_in_claim:
            return ScopeAuditResult(
                status="overgeneralized",
                details=(
                    f"Claim asserts clinical/human effect ({', '.join(human_in_claim)}), "
                    f"but cited evidence is restricted to preclinical/in vitro models ({', '.join(preclinical_in_ev)})."
                ),
                conditions_in_evidence=preclinical_in_ev,
                conditions_in_claim=human_in_claim
            )
        elif not preclinical_in_claim:
            # Broad general assertion without acknowledging preclinical constraint
            # Check if claim states an unqualified broad biological law or therapy
            is_broad = bool(re.search(r"\b(in\s+patients|treatment\s+for|effective\s+against|cures|prevents)\b", full_claim_ctx, re.IGNORECASE))
            if is_broad:
                return ScopeAuditResult(
                    status="overgeneralized",
                    details=(
                        f"Claim generalizes findings without stating that evidence was conducted in "
                        f"preclinical models ({', '.join(preclinical_in_ev)})."
                    ),
                    conditions_in_evidence=preclinical_in_ev,
                    conditions_in_claim=preclinical_in_claim
                )

    # 2. In Vitro vs In Vivo Context Mismatch
    in_vitro_in_ev = [m for m in preclinical_in_ev if "vitro" in m or "culture" in m or "line" in m]
    if in_vitro_in_ev and not any("vivo" in p for p in preclinical_in_ev):
        if re.search(r"\bin\s+vivo\b", full_claim_ctx, re.IGNORECASE):
            return ScopeAuditResult(
                status="context_mismatch",
                details=(
                    f"Claim asserts in vivo efficacy, but cited evidence is strictly "
                    f"in vitro ({', '.join(in_vitro_in_ev)})."
                ),
                conditions_in_evidence=in_vitro_in_ev,
                conditions_in_claim=["in vivo"]
            )

    # 3. Correlation vs Causation Overreach
    correl_in_ev = _find_matches(_CORRELATION_TERMS, evidence_text)
    causal_in_ev = _find_matches(_CAUSAL_TERMS, evidence_text)
    causal_in_claim = _find_matches(_CAUSAL_TERMS, full_claim_ctx)
    correl_in_claim = _find_matches(_CORRELATION_TERMS, full_claim_ctx)

    if correl_in_ev and not causal_in_ev:
        if causal_in_claim and not correl_in_claim:
            return ScopeAuditResult(
                status="overgeneralized",
                details=(
                    f"Claim asserts direct causation ({', '.join(causal_in_claim)}), "
                    f"whereas cited evidence only established correlation/association ({', '.join(correl_in_ev)})."
                ),
                conditions_in_evidence=correl_in_ev,
                conditions_in_claim=causal_in_claim
            )

    # 4. Hedging vs Certainty
    hedges_in_ev = _find_matches(_HEDGE_TERMS, evidence_text)
    hedges_in_claim = _find_matches(_HEDGE_TERMS, full_claim_ctx)
    definitive_in_claim = _find_matches(_DEFINITIVE_TERMS, full_claim_ctx)

    if hedges_in_ev and definitive_in_claim:
        return ScopeAuditResult(
            status="overgeneralized",
            details=(
                f"Claim asserts definitive certainty ({', '.join(definitive_in_claim)}), "
                f"removing scientific hedging present in evidence ({', '.join(hedges_in_ev)})."
            ),
            hedges_in_evidence=hedges_in_ev,
            hedges_in_claim=definitive_in_claim
        )

    # 5. Appropriately hedged claim
    if hedges_in_ev and hedges_in_claim:
        return ScopeAuditResult(
            status="hedged",
            details=f"Claim preserves scientific qualifiers and hedging ({', '.join(hedges_in_claim)}) consistent with evidence.",
            hedges_in_evidence=hedges_in_ev,
            hedges_in_claim=hedges_in_claim
        )

    return ScopeAuditResult(
        status="consistent",
        details="Scope, population context, and degree of certainty are consistent between claim and evidence.",
        hedges_in_evidence=hedges_in_ev,
        hedges_in_claim=hedges_in_claim,
        conditions_in_evidence=preclinical_in_ev,
        conditions_in_claim=preclinical_in_claim
    )
