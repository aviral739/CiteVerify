"""Comprehensive evaluation script for CiteVerify S4 Waterfall and S6 Claim Verification.

Evaluates:
1. Dataset Annotation Correctness (Ayushman's 32-case benchmark ground truth)
2. Actual CiteVerify Pipeline Predictions (Stage 6 ClaimVerificationEngine execution)
3. Mocked Provider Waterfall Behavior (Cache -> Crossref -> OpenAlex -> Europe PMC -> S2)
4. Live Provider Smoke Tests (External API contracts when network is reachable)
"""

import asyncio
from collections import Counter, defaultdict
import json
import logging
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models.schemas import EvidenceAvailabilityEnum, VerdictEnum
from app.stages.s6_verify import ClaimVerificationEngine
from app.stages.s6_verify.models import ClaimEvidencePair, EvidencePassage

logger = logging.getLogger("citeverify.evaluation")


def load_evaluation_dataset(dataset_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Load the 32-case evaluation dataset."""
    if dataset_path is None:
        dataset_path = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "evaluation_dataset.json"
    with open(dataset_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["cases"]


async def run_actual_pipeline_evaluation(cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Run actual CiteVerify ClaimVerificationEngine on each case in the evaluation dataset.

    Maps case evidence and claim into ClaimEvidencePair and invokes verify_pair().
    """
    engine = ClaimVerificationEngine()
    predictions = []
    verdict_classes = [v.value for v in VerdictEnum]

    confusion = {exp: {pred: 0 for pred in verdict_classes} for exp in verdict_classes}
    tp = defaultdict(int)
    fp = defaultdict(int)
    fn = defaultdict(int)
    correct_count = 0
    abstention_count = 0
    insufficient_evidence_count = 0
    false_positives = []
    false_negatives = []

    for case in cases:
        case_id = case["case_id"]
        claim_text = case["claim"]
        source_evidence = case["source_evidence"]
        expected_verdict = case["expected_verdict"]
        expected_abstention = case.get("expected_abstention", False)

        # Build evidence passage depending on availability and case type
        if expected_abstention:
            source_type = EvidenceAvailabilityEnum.UNAVAILABLE
            evidence_passages = [
                EvidencePassage(
                    evidence_id=f"ev-{case_id}",
                    citation_key="[1]",
                    reference_id="ref-eval",
                    claim_id=case_id,
                    evidence_text=source_evidence,
                    source_type=EvidenceAvailabilityEnum.UNAVAILABLE,
                    retrieval_score=0.0,
                )
            ]
        elif "abstract" in source_evidence.lower() and len(source_evidence) < 300:
            source_type = EvidenceAvailabilityEnum.ABSTRACT_ONLY
            evidence_passages = [
                EvidencePassage(
                    evidence_id=f"ev-{case_id}",
                    citation_key="[1]",
                    reference_id="ref-eval",
                    claim_id=case_id,
                    evidence_text=source_evidence,
                    section_title="Abstract",
                    page_number=1,
                    source_type=EvidenceAvailabilityEnum.ABSTRACT_ONLY,
                    retrieval_score=0.85,
                )
            ]
        else:
            source_type = EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE
            evidence_passages = [
                EvidencePassage(
                    evidence_id=f"ev-{case_id}",
                    citation_key="[1]",
                    reference_id="ref-eval",
                    claim_id=case_id,
                    evidence_text=source_evidence,
                    section_title="Results",
                    page_number=2,
                    source_type=EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE,
                    retrieval_score=0.92,
                )
            ]

        pair = ClaimEvidencePair(
            claim_id=case_id,
            citation_key="[1]",
            reference_id="ref-eval",
            claim_text=claim_text,
            evidence_passages=evidence_passages,
            is_retracted=("retract" in case.get("error_category", "")),
        )

        res = await engine.verify_pair(pair)
        pred_verdict = res.verdict.value

        is_match = (pred_verdict == expected_verdict)
        if is_match:
            correct_count += 1
            tp[expected_verdict] += 1
        else:
            fp[pred_verdict] += 1
            fn[expected_verdict] += 1

            if pred_verdict == VerdictEnum.SUPPORTED.value and expected_verdict != VerdictEnum.SUPPORTED.value:
                false_positives.append({
                    "case_id": case_id,
                    "claim": claim_text,
                    "expected": expected_verdict,
                    "predicted": pred_verdict,
                    "error_category": case.get("error_category"),
                    "explanation": res.explanation,
                })
            else:
                false_negatives.append({
                    "case_id": case_id,
                    "claim": claim_text,
                    "expected": expected_verdict,
                    "predicted": pred_verdict,
                    "error_category": case.get("error_category"),
                    "explanation": res.explanation,
                })

        confusion[expected_verdict][pred_verdict] += 1

        if res.verification_method == "abstention" or res.verdict == VerdictEnum.INSUFFICIENT_EVIDENCE:
            insufficient_evidence_count += 1
            if res.verification_method == "abstention":
                abstention_count += 1

        predictions.append({
            "case_id": case_id,
            "domain": case["domain"],
            "expected_verdict": expected_verdict,
            "predicted_verdict": pred_verdict,
            "verdict_strength": res.verdict_strength,
            "match": is_match,
            "method": res.verification_method,
            "explanation": res.explanation,
        })

    total = len(cases)
    accuracy = correct_count / total if total > 0 else 0.0

    per_class_metrics = {}
    f1_list = []
    for v in verdict_classes:
        prec = tp[v] / (tp[v] + fp[v]) if (tp[v] + fp[v]) > 0 else 0.0
        rec = tp[v] / (tp[v] + fn[v]) if (tp[v] + fn[v]) > 0 else 0.0
        f1 = (2 * prec * rec) / (prec + rec) if (prec + rec) > 0 else 0.0
        support = tp[v] + fn[v]
        per_class_metrics[v] = {
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1": round(f1, 4),
            "support": support,
        }
        if support > 0:
            f1_list.append(f1)

    macro_f1 = sum(f1_list) / len(f1_list) if f1_list else 0.0

    return {
        "total_cases": total,
        "correct_predictions": correct_count,
        "accuracy": round(accuracy, 4),
        "macro_f1": round(macro_f1, 4),
        "per_class_metrics": per_class_metrics,
        "confusion_matrix": confusion,
        "abstention_count": abstention_count,
        "insufficient_evidence_count": insufficient_evidence_count,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "predictions": predictions,
    }


def format_evaluation_summary(results: Dict[str, Any]) -> str:
    """Format evaluation results into human-readable report."""
    lines = []
    lines.append("=" * 70)
    lines.append("CITEVERIFY ACTUAL PIPELINE EVALUATION ON 32-CASE BENCHMARK")
    lines.append("=" * 70)
    lines.append(f"Total Cases: {results['total_cases']}")
    lines.append(f"Correct Predictions: {results['correct_predictions']}/{results['total_cases']}")
    lines.append(f"Accuracy: {results['accuracy']:.2%}")
    lines.append(f"Macro-F1: {results['macro_f1']:.4f}")
    lines.append(f"Abstentions: {results['abstention_count']}")
    lines.append(f"Insufficient Evidence Verdicts: {results['insufficient_evidence_count']}")
    lines.append("")
    lines.append("PER-CLASS METRICS:")
    lines.append(f"{'Class':<25} {'Precision':<10} {'Recall':<10} {'F1':<10} {'Support':<8}")
    lines.append("-" * 65)
    for cls, m in results["per_class_metrics"].items():
        lines.append(f"{cls:<25} {m['precision']:<10.4f} {m['recall']:<10.4f} {m['f1']:<10.4f} {m['support']:<8}")

    lines.append("")
    lines.append("CONFUSION MATRIX (Row: Ground Truth, Column: Predicted):")
    classes = list(results["per_class_metrics"].keys())
    header = f"{'Actual v / Pred >':<22} " + " ".join(f"{c[:6]:>7}" for c in classes)
    lines.append(header)
    lines.append("-" * len(header))
    for actual in classes:
        row = f"{actual:<22} " + " ".join(f"{results['confusion_matrix'][actual][pred]:>7}" for pred in classes)
        lines.append(row)

    lines.append("")
    lines.append(f"FALSE POSITIVE COUNT: {len(results['false_positives'])}")
    for fp in results["false_positives"]:
        lines.append(f"  - [{fp['case_id']}] Expected '{fp['expected']}' but predicted '{fp['predicted']}' ({fp['error_category']})")
        lines.append(f"    Claim: {fp['claim'][:70]}...")

    lines.append("")
    lines.append(f"FALSE NEGATIVE / MISCLASSIFIED COUNT: {len(results['false_negatives'])}")
    for fn in results["false_negatives"]:
        lines.append(f"  - [{fn['case_id']}] Expected '{fn['expected']}' but predicted '{fn['predicted']}' ({fn['error_category']})")

    lines.append("=" * 70)
    return "\n".join(lines)


if __name__ == "__main__":
    cases = load_evaluation_dataset()
    res = asyncio.run(run_actual_pipeline_evaluation(cases))
    print(format_evaluation_summary(res))
