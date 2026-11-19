"""Deterministic dimensional numerical normalization and consistency checking between claims and evidence.

Handles dimensional unit normalization, ranges, inequalities, fractional ratios,
directional consistency, and prevents cross-dimensional false matches.
"""

import re
from typing import List, Optional, Tuple, Dict, Any
from pydantic import BaseModel, Field


class NumericCheckResult(BaseModel):
    status: str  # "exact_match", "range_containment", "compatible_inequality", "mismatch", "missing_in_source", "indeterminate", "not_applicable"
    details: str
    match_ratio: float = 0.0


# Semantic Unit Dimensional Categories
_UNIT_CATEGORIES: Dict[str, str] = {
    # Proportions
    "%": "proportion",
    "percent": "proportion",
    "pct": "proportion",
    # Multipliers
    "fold": "multiplier",
    "-fold": "multiplier",
    "times": "multiplier",
    "x": "multiplier",
    # Count / Cohort
    "patients": "cohort",
    "subjects": "cohort",
    "participants": "cohort",
    "samples": "cohort",
    "cases": "cohort",
    "individuals": "cohort",
    "cohort": "cohort",
    # Mass
    "mg": "mass",
    "kg": "mass",
    "g": "mass",
    "μg": "mass",
    "ug": "mass",
    "ng": "mass",
    # Volume
    "ml": "volume",
    "l": "volume",
    "μl": "volume",
    "ul": "volume",
    # Length
    "μm": "length",
    "um": "length",
    "nm": "length",
    "mm": "length",
    "cm": "length",
    "m": "length",
    # Time
    "ms": "time",
    "s": "time",
    "seconds": "time",
    "minutes": "time",
    "min": "time",
    "hours": "time",
    "h": "time",
    "days": "time",
    "d": "time",
    "weeks": "time",
    "months": "time",
    "years": "time",
    # Statistical
    "p": "p_value",
    "p-value": "p_value",
}

_DIRECTION_INCREASE = re.compile(r"\b(increase|increased|increasing|higher|elevated|elevation|rise|risen|growth|gain|improved|improvement)\b", re.IGNORECASE)
_DIRECTION_DECREASE = re.compile(r"\b(decrease|decreased|decreasing|lower|lowered|reduced|reduction|drop|dropped|loss|decline|suppressed|inhibition)\b", re.IGNORECASE)


class ParsedQuantity(BaseModel):
    raw: str
    val: Optional[float] = None
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    unit: Optional[str] = None
    unit_category: Optional[str] = None
    inequality: Optional[str] = None  # "<", "<=", ">", ">=", "="
    is_range: bool = False
    is_ratio: bool = False
    numerator: Optional[float] = None
    denominator: Optional[float] = None
    direction: Optional[str] = None  # "increase", "decrease"


_KNOWN_UNITS_REGEX = r'(%|percent|pct|-fold|fold|times|x|patients|subjects|participants|samples|cases|individuals|cohort|mg|kg|g|μg|ug|ng|ml|l|μl|ul|μm|um|nm|mm|cm|m|ms|s|seconds|minutes|min|hours|h|days|d|weeks|months|years|p-value|p)\b'


def normalize_unit_str(raw_unit: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Normalize raw unit string and determine its dimensional category."""
    if not raw_unit:
        return None, None
    u = raw_unit.lower().strip()
    if u in ("%", "percent", "pct"):
        return "%", "proportion"
    if u in ("fold", "-fold"):
        return "fold", "multiplier"
    category = _UNIT_CATEGORIES.get(u)
    if not category:
        return None, None
    return u, category


def parse_quantity_token(text: str) -> Optional[ParsedQuantity]:
    """Parse a numerical token, inequality, range, or ratio with units and direction."""
    text_clean = text.strip()

    # Detect directional words
    direction = None
    if _DIRECTION_INCREASE.search(text_clean):
        direction = "increase"
    elif _DIRECTION_DECREASE.search(text_clean):
        direction = "decrease"

    # 1. Inequality: e.g. "p < 0.05", "<= 10 mg", "> 50%"
    ineq_match = re.search(r'(?:(p)\s*)?([<>]=?|=)\s*([+-]?\d+(?:\.\d+)?)\s*([a-zA-Z%μ]+)?', text_clean, re.IGNORECASE)
    if ineq_match:
        has_p = bool(ineq_match.group(1)) or "p" in text_clean.lower()
        op = ineq_match.group(2)
        val = float(ineq_match.group(3))
        raw_u = ineq_match.group(4)
        norm_u, cat = normalize_unit_str(raw_u)
        if not norm_u and has_p:
            norm_u, cat = "p", "p_value"
        return ParsedQuantity(
            raw=text_clean,
            val=val,
            inequality=op,
            unit=norm_u,
            unit_category=cat,
            direction=direction,
        )

    # 2. Ratio: e.g. "15/20", "15 out of 20"
    ratio_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:/|out\s+of)\s*(\d+(?:\.\d+)?)\s*([a-zA-Z%μ]+)?', text_clean, re.IGNORECASE)
    if ratio_match:
        num = float(ratio_match.group(1))
        denom = float(ratio_match.group(2))
        val = num / denom if denom != 0 else None
        raw_u = ratio_match.group(3)
        norm_u, cat = normalize_unit_str(raw_u)
        return ParsedQuantity(
            raw=text_clean,
            val=val,
            is_ratio=True,
            numerator=num,
            denominator=denom,
            unit=norm_u,
            unit_category="proportion" if cat is None else cat,
            direction=direction,
        )

    # 3. Range: e.g. "10-20%", "10 to 20 mg", "10–20%"
    range_match = re.search(r'([+-]?\d+(?:\.\d+)?)\s*(?:-|–|—|to)\s*([+-]?\d+(?:\.\d+)?)\s*([a-zA-Z%μ]+)?', text_clean, re.IGNORECASE)
    if range_match:
        v1 = float(range_match.group(1))
        v2 = float(range_match.group(2))
        raw_u = range_match.group(3) or ("%" if "%" in text_clean else None)
        norm_u, cat = normalize_unit_str(raw_u)
        return ParsedQuantity(
            raw=text_clean,
            min_val=min(v1, v2),
            max_val=max(v1, v2),
            is_range=True,
            unit=norm_u,
            unit_category=cat,
            direction=direction,
        )

    # 4. Standard scalar with unit: e.g. "41.5%", "100 patients", "3-fold", "0.415"
    scalar_match = re.search(r'([+-]?\d+(?:\.\d+)?)\s*([a-zA-Z%μ-]+)?', text_clean, re.IGNORECASE)
    if scalar_match:
        val = float(scalar_match.group(1))
        raw_u = scalar_match.group(2)
        norm_u, cat = normalize_unit_str(raw_u)
        return ParsedQuantity(
            raw=text_clean,
            val=val,
            unit=norm_u,
            unit_category=cat,
            direction=direction,
        )

    return None


def extract_all_quantities(text: str) -> List[ParsedQuantity]:
    """Extract all recognizable quantities, ranges, inequalities, and ratios from passage."""
    quantities: List[ParsedQuantity] = []

    # Check for direction in sentences containing numbers
    sentences = re.split(r'(?<!\d)\.(?!\d)|\n|;', text)
    for sent in sentences:
        if not re.search(r'\d', sent):
            continue

        dir_in_sent = None
        if _DIRECTION_INCREASE.search(sent):
            dir_in_sent = "increase"
        elif _DIRECTION_DECREASE.search(sent):
            dir_in_sent = "decrease"

        # Ratio matches
        for m in re.finditer(r'\b(\d+(?:\.\d+)?)\s*(?:/|out\s+of)\s*(\d+(?:\.\d+)?)\s*([a-zA-Z%μ]+)?', sent, re.IGNORECASE):
            num = float(m.group(1))
            denom = float(m.group(2))
            val = num / denom if denom != 0 else None
            norm_u, cat = normalize_unit_str(m.group(3))
            quantities.append(ParsedQuantity(
                raw=m.group(0),
                val=val,
                is_ratio=True,
                numerator=num,
                denominator=denom,
                unit=norm_u,
                unit_category="proportion" if cat is None else cat,
                direction=dir_in_sent,
            ))

        # Range matches
        for m in re.finditer(r'\b([+-]?\d+(?:\.\d+)?)\s*(?:-|–|—|to)\s*([+-]?\d+(?:\.\d+)?)\s*([a-zA-Z%μ]+)?', sent, re.IGNORECASE):
            v1 = float(m.group(1))
            v2 = float(m.group(2))
            norm_u, cat = normalize_unit_str(m.group(3))
            quantities.append(ParsedQuantity(
                raw=m.group(0),
                min_val=min(v1, v2),
                max_val=max(v1, v2),
                is_range=True,
                unit=norm_u,
                unit_category=cat,
                direction=dir_in_sent,
            ))

        # Inequality matches (e.g. p < 0.05, > 50%)
        for m in re.finditer(r'(?:(p)\s*)?([<>]=?|=)\s*([+-]?\d+(?:\.\d+)?)\s*([a-zA-Z%μ]+)?', sent, re.IGNORECASE):
            has_p = bool(m.group(1)) or bool(re.search(r'\bp\s*[<>=]', m.group(0), re.IGNORECASE))
            op = m.group(2)
            val = float(m.group(3))
            raw_u = m.group(4)
            norm_u, cat = normalize_unit_str(raw_u)
            if not norm_u and has_p:
                norm_u, cat = "p", "p_value"
            quantities.append(ParsedQuantity(
                raw=m.group(0),
                val=val,
                inequality=op,
                unit=norm_u,
                unit_category=cat,
                direction=dir_in_sent,
            ))

        # Scalar tokens with optional units (allowing demographic modifiers like 'human', 'male', 'adult')
        for m in re.finditer(r'([+-]?\b\d+(?:\.\d+)?)\s*(?:(?:human|male|female|adult|pediatric|consecutive|treated|control|randomized|baseline)\s+)?([a-zA-Z%μ-]+)?(?=\b|\s|[.,;)]|$)', sent):
            raw_u = m.group(2)
            val = float(m.group(1))
            norm_u, cat = normalize_unit_str(raw_u)
            quantities.append(ParsedQuantity(
                raw=m.group(0),
                val=val,
                unit=norm_u,
                unit_category=cat,
                direction=dir_in_sent,
            ))

    return quantities


def check_quantity_compatibility(
    claim_q: ParsedQuantity,
    evidence_q: ParsedQuantity,
) -> Tuple[bool, Optional[str], str]:
    """Evaluate whether claim quantity is corroborated by, consistent with, or contradicts evidence quantity.

    Returns: (is_match, status_name, explanation)
    """
    # 1. Dimensional Incompatibility Check
    # Handle percentage to decimal proportion equivalence before dimensional incompatibility
    if claim_q.val is not None and evidence_q.val is not None:
        c_val = claim_q.val
        e_val = evidence_q.val

        # Proportions: 41.5% and 0.415
        if (claim_q.unit == "%" and (evidence_q.unit is None or evidence_q.unit == "%")) or (evidence_q.unit == "%" and (claim_q.unit is None or claim_q.unit == "%")):
            if abs(c_val / 100.0 - e_val) < 0.001:
                return True, "exact_match", f"Percentage {c_val}% is equivalent to decimal proportion {e_val}."
            if abs(e_val / 100.0 - c_val) < 0.001:
                return True, "exact_match", f"Decimal proportion {c_val} is equivalent to percentage {e_val}%."

    # Multiplier vs Proportion: e.g. fold changes vs percentage changes
    if (claim_q.unit_category == "multiplier" and evidence_q.unit_category == "proportion") or (claim_q.unit_category == "proportion" and evidence_q.unit_category == "multiplier"):
        return False, "incompatible_units", f"Incompatible dimensions: multiplier ('{claim_q.unit}') cannot be equated with percentage ('{evidence_q.unit}') without baseline context."

    # If both have categories and they differ -> INCOMPATIBLE if values are equal or near
    if claim_q.unit_category and evidence_q.unit_category:
        if claim_q.unit_category != evidence_q.unit_category:
            c_v = claim_q.val if claim_q.val is not None else (claim_q.min_val or 0.0)
            e_v = evidence_q.val if evidence_q.val is not None else (evidence_q.min_val or 0.0)
            if abs(c_v - e_v) < 0.001:
                return False, "incompatible_units", f"Incompatible dimensions: claim unit '{claim_q.unit}' ({claim_q.unit_category}) vs evidence unit '{evidence_q.unit}' ({evidence_q.unit_category})"
            else:
                return False, "unrelated", f"Different values and units: '{claim_q.raw}' vs '{evidence_q.raw}'"
    elif claim_q.unit_category and not evidence_q.unit_category:
        c_v = claim_q.val if claim_q.val is not None else (claim_q.min_val or 0.0)
        e_v = evidence_q.val if evidence_q.val is not None else (evidence_q.min_val or 0.0)
        if abs(c_v - e_v) < 0.001:
            return False, "indeterminate", f"Claim specifies dimensional unit '{claim_q.unit}', but cited number is dimensionless."
        else:
            return False, "unrelated", f"Different values and units: '{claim_q.raw}' vs '{evidence_q.raw}'"
    elif not claim_q.unit_category and evidence_q.unit_category:
        c_v = claim_q.val if claim_q.val is not None else (claim_q.min_val or 0.0)
        e_v = evidence_q.val if evidence_q.val is not None else (evidence_q.min_val or 0.0)
        if abs(c_v - e_v) < 0.001:
            return False, "indeterminate", f"Cited evidence specifies unit '{evidence_q.unit}', but claim has no unit."
        else:
            return False, "unrelated", f"Different values and units: '{claim_q.raw}' vs '{evidence_q.raw}'"

    # 2. Directional Conflict Check
    if claim_q.direction and evidence_q.direction:
        if claim_q.direction != evidence_q.direction:
            return False, "mismatch", f"Directional conflict: claim asserts {claim_q.direction} but evidence reports {evidence_q.direction}."

    # 3. Range Containment
    if claim_q.is_range and not evidence_q.is_range and evidence_q.val is not None:
        if claim_q.min_val is not None and claim_q.max_val is not None:
            # Check percentage/decimal scaling if one is % and other decimal
            ev_val = evidence_q.val
            if claim_q.unit == "%" and evidence_q.unit != "%" and ev_val <= 1.0:
                ev_val = ev_val * 100.0
            if claim_q.min_val - 0.001 <= ev_val <= claim_q.max_val + 0.001:
                return True, "range_containment", f"Reported value {evidence_q.val} falls within claimed range [{claim_q.min_val}, {claim_q.max_val}]."
            else:
                return False, "mismatch", f"Reported value {evidence_q.val} falls outside claimed range [{claim_q.min_val}, {claim_q.max_val}]."

    # 4. Inequality Evaluation
    if claim_q.inequality and evidence_q.val is not None:
        c_val = claim_q.val or 0.0
        e_val = evidence_q.val
        # Decimal to % normalization
        if claim_q.unit == "%" and evidence_q.unit != "%" and e_val <= 1.0:
            e_val = e_val * 100.0
        elif claim_q.unit != "%" and evidence_q.unit == "%" and c_val <= 1.0:
            c_val = c_val * 100.0

        op = claim_q.inequality
        satisfied = False
        if op == "<" and e_val < c_val + 0.001:
            satisfied = True
        elif op == "<=" and e_val <= c_val + 0.001:
            satisfied = True
        elif op == ">" and e_val > c_val - 0.001:
            satisfied = True
        elif op == ">=" and e_val >= c_val - 0.001:
            satisfied = True
        elif op == "=" and abs(e_val - c_val) < 0.001:
            satisfied = True

        if satisfied:
            return True, "compatible_inequality", f"Reported value {evidence_q.val} satisfies claimed inequality ({op} {claim_q.val})."
        else:
            return False, "mismatch", f"Reported value {evidence_q.val} conflicts with claimed inequality ({op} {claim_q.val})."

    # 5. Scalar and Proportion Comparison
    if claim_q.val is not None and evidence_q.val is not None:
        c_val = claim_q.val
        e_val = evidence_q.val

        # Exact scalar equality
        if abs(c_val - e_val) < 0.001:
            return True, "exact_match", f"Numerical value {c_val} matches exactly."

        # Proportion percentage-to-decimal equivalence (41.5% and 0.415)
        if claim_q.unit_category == "proportion" or evidence_q.unit_category == "proportion":
            if abs(c_val / 100.0 - e_val) < 0.001:
                return True, "exact_match", f"Percentage {c_val}% is equivalent to decimal proportion {e_val}."
            if abs(e_val / 100.0 - c_val) < 0.001:
                return True, "exact_match", f"Decimal proportion {c_val} is equivalent to percentage {e_val}%."

        # If numbers are different
        return False, "mismatch", f"Claim asserts '{claim_q.raw}', but cited text reports '{evidence_q.raw}'."

    return False, "indeterminate", "Ambiguous numerical comparison."


def check_numerical_consistency(
    claim_numbers: List[str],
    evidence_text: str,
    evidence_completeness: str = "full_text_available"
) -> NumericCheckResult:
    """Compare numerical quantities in claim against retrieved source text with full dimensional safety."""
    if not claim_numbers:
        return NumericCheckResult(
            status="not_applicable",
            details="No numerical claims present.",
            match_ratio=1.0,
        )

    if not evidence_text or not evidence_text.strip():
        if evidence_completeness == "abstract_only":
            return NumericCheckResult(
                status="missing_in_source",
                details="Numerical values not found in abstract (full text not checked).",
                match_ratio=0.0,
            )
        return NumericCheckResult(
            status="missing_in_source",
            details="Source text empty or unavailable.",
            match_ratio=0.0,
        )

    evidence_quantities = extract_all_quantities(evidence_text)

    matches = 0
    mismatches = 0
    missing = 0
    incompatible = 0
    statuses_seen = set()
    details_log = []

    for c_raw in claim_numbers:
        c_q = parse_quantity_token(c_raw)
        if not c_q:
            continue

        best_status = None
        best_detail = None
        matched_this_claim = False

        # First look for compatible exact matches, range containments, or inequality matches
        for e_q in evidence_quantities:
            is_match, status_name, expl = check_quantity_compatibility(c_q, e_q)
            if is_match:
                matched_this_claim = True
                best_status = status_name
                best_detail = expl
                break

        if matched_this_claim and best_status:
            matches += 1
            statuses_seen.add(best_status)
            details_log.append(best_detail or "")
        else:
            # Check if there is an explicit dimensional incompatibility or numerical conflict
            found_conflict = False
            for e_q in evidence_quantities:
                is_match, status_name, expl = check_quantity_compatibility(c_q, e_q)
                if status_name == "mismatch":
                    mismatches += 1
                    statuses_seen.add("mismatch")
                    details_log.append(expl)
                    found_conflict = True
                    break
                elif status_name == "incompatible_units":
                    incompatible += 1
                    statuses_seen.add("indeterminate")
                    details_log.append(expl)
                    found_conflict = True
                    break

            if not found_conflict:
                missing += 1

    total = matches + mismatches + missing + incompatible
    if total == 0:
        return NumericCheckResult(status="not_applicable", details="No parsable numerical values.", match_ratio=1.0)

    # Resolve aggregate status
    if mismatches > 0:
        return NumericCheckResult(
            status="mismatch",
            details="; ".join(details_log) if details_log else "Quantitative values conflict with source passage.",
            match_ratio=matches / total,
        )

    if incompatible > 0:
        return NumericCheckResult(
            status="indeterminate",
            details="; ".join(details_log) if details_log else "Incompatible measurement units; cannot verify equivalence.",
            match_ratio=0.0,
        )

    if matches == total:
        overall = "exact_match"
        if "range_containment" in statuses_seen:
            overall = "range_containment"
        elif "compatible_inequality" in statuses_seen:
            overall = "compatible_inequality"
        return NumericCheckResult(
            status=overall,
            details="; ".join(details_log) if details_log else f"All numerical values ({matches}/{total}) verified in cited passage.",
            match_ratio=1.0,
        )

    if matches > 0 and missing > 0:
        return NumericCheckResult(
            status="range_containment" if "range_containment" in statuses_seen else "exact_match",
            details=f"Partially verified: {matches}/{total} values corroborated. Details: {'; '.join(details_log)}",
            match_ratio=matches / total,
        )

    # Missing in source
    if evidence_completeness == "abstract_only":
        return NumericCheckResult(
            status="missing_in_source",
            details=f"Values ({', '.join(claim_numbers)}) not found in abstract (full text not checked).",
            match_ratio=0.0,
        )

    return NumericCheckResult(
        status="missing_in_source",
        details=f"Values ({', '.join(claim_numbers)}) not found in retrieved evidence passage.",
        match_ratio=0.0,
    )
