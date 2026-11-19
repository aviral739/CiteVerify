"""Scientific claim feature extraction: entities, numerical values, conditions, and claim types."""

import re
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ClaimCategoryEnum(str, Enum):
    EMPIRICAL = "empirical"
    STATISTICAL = "statistical"
    COMPARATIVE = "comparative"
    CAUSAL = "causal"
    METHODOLOGICAL = "methodological"
    LITERATURE = "literature"
    QUANTITATIVE = "quantitative"
    OTHER = "other"


# Verifiable Claim Trigger Keywords
_STATISTICAL_TRIGGERS = re.compile(
    r'\b(p\s*[<>=]|p-value|ci|confidence interval|f-score|f1|accuracy|auc|roc|std|standard deviation|variance|correlation|r\s*=|regression)\b',
    re.IGNORECASE
)
_QUANTITATIVE_TRIGGERS = re.compile(
    r'\b\d+(?:\.\d+)?\s*(?:-fold|fold|%|percent|times|mg|kg|ml|μm|nm|ms|s|hours|days|weeks|months|years|hz|khz|ghz|gb|mb|tb|k|patients|subjects|participants|samples)(?=\b|\s|[.,;)]|$)',
    re.IGNORECASE
)
_COMPARATIVE_TRIGGERS = re.compile(
    r'\b(outperformed|outperforms|superior to|greater than|higher than|lower than|less than|faster than|slower than|improved by|better than|exceeded|comparable to|versus|vs\.?)\b',
    re.IGNORECASE
)
_CAUSAL_TRIGGERS = re.compile(
    r'\b(leads to|resulted in|results in|causes|caused|induces|induced|promotes|inhibits|triggers|triggered|reduces|reduced|increases|increased|prevented|prevents)\b',
    re.IGNORECASE
)
_METHODOLOGICAL_TRIGGERS = re.compile(
    r'\b(we propose|we introduce|we design|we implement|we develop|we evaluated|architecture consists of|algorithm|pipeline|framework)\b',
    re.IGNORECASE
)
_EMPIRICAL_TRIGGERS = re.compile(
    r'\b(demonstrates|demonstrated|observed|found that|showed that|shows that|revealed|identified|confirmed|indicates that)\b',
    re.IGNORECASE
)

# Non-claim filters: Acknowledgements, pure greetings, generic background filler
_NON_CLAIM_PATTERNS = re.compile(
    r'^(this research was supported by|we thank|the authors declare|conflict of interest|all rights reserved|contents lists available|received \d+|revised \d+|accepted \d+|available online)\b',
    re.IGNORECASE
)


class ExtractedFeatures(BaseModel):
    category: ClaimCategoryEnum = ClaimCategoryEnum.OTHER
    is_scientific_claim: bool = False
    numerical_values: List[str] = Field(default_factory=list)
    entities: List[str] = Field(default_factory=list)
    experimental_conditions: Optional[str] = None
    qualifiers: List[str] = Field(default_factory=list)
    claim_importance_score: float = 0.0


def extract_claim_features(sentence: str, has_citation: bool = False) -> ExtractedFeatures:
    """Extract semantic features, numerical targets, conditions, and classify the statement."""
    clean = sentence.strip()
    features = ExtractedFeatures()

    # 1. Non-claim sentence filter
    if len(clean) < 20 or _NON_CLAIM_PATTERNS.search(clean):
        features.is_scientific_claim = False
        return features

    score = 0.0

    # 2. Extract numerical values and units
    num_matches = _QUANTITATIVE_TRIGGERS.findall(clean)
    if num_matches:
        features.numerical_values = [str(m).strip() for m in num_matches]
        score += 2.5

    # 3. Detect Categories & Triggers
    if _STATISTICAL_TRIGGERS.search(clean):
        features.category = ClaimCategoryEnum.STATISTICAL
        features.is_scientific_claim = True
        score += 3.0
    elif _COMPARATIVE_TRIGGERS.search(clean):
        features.category = ClaimCategoryEnum.COMPARATIVE
        features.is_scientific_claim = True
        score += 2.5
    elif _CAUSAL_TRIGGERS.search(clean):
        features.category = ClaimCategoryEnum.CAUSAL
        features.is_scientific_claim = True
        score += 2.0
    elif _QUANTITATIVE_TRIGGERS.search(clean):
        features.category = ClaimCategoryEnum.QUANTITATIVE
        features.is_scientific_claim = True
        score += 2.5
    elif _EMPIRICAL_TRIGGERS.search(clean):
        features.category = ClaimCategoryEnum.EMPIRICAL
        features.is_scientific_claim = True
        score += 2.0
    elif _METHODOLOGICAL_TRIGGERS.search(clean):
        features.category = ClaimCategoryEnum.METHODOLOGICAL
        features.is_scientific_claim = True
        score += 1.5
    elif has_citation:
        features.category = ClaimCategoryEnum.LITERATURE
        features.is_scientific_claim = True
        score += 1.5
    else:
        # Check if contains assertional verb
        if re.search(r'\b(shows?|finds?|reveals?|suggests?|reports?|proves?|establishes?)\b', clean, re.IGNORECASE):
            features.category = ClaimCategoryEnum.EMPIRICAL
            features.is_scientific_claim = True
            score += 1.0

    if has_citation:
        score += 3.0  # High priority to citation-linked claims

    # 4. Extract Qualifiers and Limitations
    qualifier_matches = re.findall(
        r'\b(typically|substantially|approximately|about|roughly|partially|in small pilot|preliminary|potentially|under specific conditions)\b',
        clean,
        re.IGNORECASE
    )
    if qualifier_matches:
        features.qualifiers = list(set(qualifier_matches))

    # 5. Extract Experimental Conditions
    cond_match = re.search(r'\b(in\s+[a-z0-9\-]+\s+(?:mice|rats|patients|subjects|cohort|monkeys|cells|benchmarks|trials?|models?)|under\s+[a-z0-9\-]+\s+temperature|at\s+\d+\s*K)\b', clean, re.IGNORECASE)
    if cond_match:
        features.experimental_conditions = cond_match.group(0).strip()
        score += 1.0

    # 6. Extract Entities (Capitalized scientific/model terms or acronyms)
    entity_matches = re.findall(r'\b[A-Z][a-zA-Z0-9\-_]{2,}\b', clean)
    common_stops = {"The", "This", "These", "However", "Therefore", "Moreover", "Furthermore", "Figure", "Table", "According", "Recent"}
    features.entities = [e for e in entity_matches if e not in common_stops][:5]

    features.claim_importance_score = score
    return features


def decompose_sentence(sentence: str) -> List[str]:
    """Decompose sentence containing multiple independent clauses if joined by strong conjunctions."""
    clean = sentence.strip()
    # Check for strong causal/contrastive conjunctive splits with distinct subjects
    # e.g., "Model A reduced latency by 30%; whereas Model B increased memory consumption."
    clauses = re.split(r';\s*(?:whereas\s+)?|\s+whereas\s+|\s+while\s+(?=[A-Z])', clean)
    if len(clauses) > 1 and all(len(c.strip()) >= 20 for c in clauses):
        return [c.strip() for c in clauses if c.strip()]
    return [clean]
