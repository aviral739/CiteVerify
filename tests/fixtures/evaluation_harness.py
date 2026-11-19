"""Evaluation harness for CiteVerify claim-evidence verification benchmarks.

Provides offline evaluation metrics, confusion matrix computation, and validation
tools for Stage 6 (Claim Verification) models against the manually reviewed ground truth.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.models.schemas import VerdictEnum


@dataclass
class EvaluationCase:
    case_id: str
    domain: str
    claim: str
    source_evidence: str
    source_citation: Dict[str, Any]
    expected_verdict: VerdictEnum
    reasoning: str
    error_category: str
    expected_abstention: bool
    expected_warning: Optional[str]
    verdict_strength_range: Dict[str, float]


@dataclass
class EvaluationPrediction:
    case_id: str
    predicted_verdict: VerdictEnum
    predicted_strength: float
    abstained: bool = False
    warning: Optional[str] = None


@dataclass
class EvaluationReport:
    total_cases: int
    correct_predictions: int
    accuracy: float
    macro_f1: float
    per_class_metrics: Dict[str, Dict[str, float]]
    confusion_matrix: Dict[str, Dict[str, int]]
    abstention_accuracy: float
    error_category_breakdown: Dict[str, int]


class VerificationBenchmarkHarness:
    """Harness to evaluate automated verification systems against CiteVerify evaluation dataset."""

    def __init__(self, dataset_path: Optional[Path] = None):
        if dataset_path is None:
            dataset_path = Path(__file__).parent / "evaluation_dataset.json"
        self.dataset_path = dataset_path
        self.cases: List[EvaluationCase] = self._load_cases()

    def _load_cases(self) -> List[EvaluationCase]:
        with open(self.dataset_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        cases = []
        for c in data["cases"]:
            cases.append(
                EvaluationCase(
                    case_id=c["case_id"],
                    domain=c["domain"],
                    claim=c["claim"],
                    source_evidence=c["source_evidence"],
                    source_citation=c.get("source_citation", {}),
                    expected_verdict=VerdictEnum(c["expected_verdict"]),
                    reasoning=c["reasoning"],
                    error_category=c["error_category"],
                    expected_abstention=bool(c.get("expected_abstention", False)),
                    expected_warning=c.get("expected_warning"),
                    verdict_strength_range=c.get("verdict_strength_range", {"min": 0.0, "max": 1.0}),
                )
            )
        return cases

    def get_case(self, case_id: str) -> Optional[EvaluationCase]:
        for c in self.cases:
            if c.case_id == case_id:
                return c
        return None

    def evaluate(self, predictions: List[EvaluationPrediction]) -> EvaluationReport:
        """Compute evaluation metrics given a list of predictions."""
        pred_map = {p.case_id: p for p in predictions}
        verdict_classes = [v.value for v in VerdictEnum]

        confusion: Dict[str, Dict[str, int]] = {
            exp: {pred: 0 for pred in verdict_classes} for exp in verdict_classes
        }

        correct = 0
        abstention_correct = 0
        error_cats = Counter()

        tp = defaultdict(int)
        fp = defaultdict(int)
        fn = defaultdict(int)

        for case in self.cases:
            error_cats[case.error_category] += 1
            pred = pred_map.get(case.case_id)
            if not pred:
                continue

            exp_v = case.expected_verdict.value
            pred_v = pred.predicted_verdict.value

            confusion[exp_v][pred_v] += 1

            if exp_v == pred_v:
                correct += 1
                tp[exp_v] += 1
            else:
                fp[pred_v] += 1
                fn[exp_v] += 1

            if case.expected_abstention == pred.abstained:
                abstention_correct += 1

        total = len(self.cases)
        accuracy = (correct / total) if total > 0 else 0.0
        abstention_acc = (abstention_correct / total) if total > 0 else 0.0

        per_class: Dict[str, Dict[str, float]] = {}
        f1_scores = []

        for v in verdict_classes:
            prec = tp[v] / (tp[v] + fp[v]) if (tp[v] + fp[v]) > 0 else 0.0
            rec = tp[v] / (tp[v] + fn[v]) if (tp[v] + fn[v]) > 0 else 0.0
            f1 = (2 * prec * rec) / (prec + rec) if (prec + rec) > 0 else 0.0
            per_class[v] = {
                "precision": round(prec, 4),
                "recall": round(rec, 4),
                "f1": round(f1, 4),
                "support": tp[v] + fn[v],
            }
            if (tp[v] + fn[v]) > 0:
                f1_scores.append(f1)

        macro_f1 = (sum(f1_scores) / len(f1_scores)) if f1_scores else 0.0

        return EvaluationReport(
            total_cases=total,
            correct_predictions=correct,
            accuracy=round(accuracy, 4),
            macro_f1=round(macro_f1, 4),
            per_class_metrics=per_class,
            confusion_matrix=confusion,
            abstention_accuracy=round(abstention_acc, 4),
            error_category_breakdown=dict(error_cats),
        )

    def generate_gold_predictions(self) -> List[EvaluationPrediction]:
        """Generate perfect baseline predictions matching ground truth for validation tests."""
        return [
            EvaluationPrediction(
                case_id=c.case_id,
                predicted_verdict=c.expected_verdict,
                predicted_strength=(c.verdict_strength_range.get("min", 0.8) + c.verdict_strength_range.get("max", 1.0)) / 2,
                abstained=c.expected_abstention,
                warning=c.expected_warning,
            )
            for c in self.cases
        ]
