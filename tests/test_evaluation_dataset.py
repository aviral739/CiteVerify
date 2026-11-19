"""Tests for custom verification evaluation dataset and benchmark harness."""

import json
from pathlib import Path
import pytest

from app.models.schemas import VerdictEnum
from tests.fixtures import EVALUATION_DATASET_PATH, VerificationBenchmarkHarness
from tests.fixtures.evaluation_harness import EvaluationPrediction


def test_dataset_file_exists():
    """Verify evaluation dataset JSON file exists and is readable."""
    assert EVALUATION_DATASET_PATH.exists()
    assert EVALUATION_DATASET_PATH.is_file()


def test_dataset_size_and_schema():
    """Verify dataset contains 20-40 cases and conforms to strict schema."""
    with open(EVALUATION_DATASET_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "cases" in data
    cases = data["cases"]
    assert 20 <= len(cases) <= 40, f"Expected 20-40 cases, got {len(cases)}"

    case_ids = set()
    verdicts = set()
    error_categories = set()

    valid_verdicts = {v.value for v in VerdictEnum}

    for c in cases:
        # Check required fields
        assert "case_id" in c and c["case_id"]
        assert "domain" in c and c["domain"]
        assert "claim" in c and c["claim"]
        assert "source_evidence" in c and c["source_evidence"]
        assert "expected_verdict" in c and c["expected_verdict"]
        assert "reasoning" in c and c["reasoning"]
        assert "error_category" in c and c["error_category"]

        assert c["case_id"] not in case_ids, f"Duplicate case_id: {c['case_id']}"
        case_ids.add(c["case_id"])

        assert c["expected_verdict"] in valid_verdicts, f"Invalid verdict: {c['expected_verdict']}"
        verdicts.add(c["expected_verdict"])
        error_categories.add(c["error_category"])

        # Check verdict strength range
        if "verdict_strength_range" in c:
            vsr = c["verdict_strength_range"]
            assert 0.0 <= vsr["min"] <= vsr["max"] <= 1.0


def test_verdict_coverage():
    """Verify all 6 official VerdictEnum classes are represented."""
    with open(EVALUATION_DATASET_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    present_verdicts = {c["expected_verdict"] for c in data["cases"]}
    for v in VerdictEnum:
        assert v.value in present_verdicts, f"Verdict '{v.value}' not represented in evaluation cases"


def test_error_category_coverage():
    """Verify all key error and discrepancy categories are represented."""
    with open(EVALUATION_DATASET_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    categories = {c["error_category"] for c in data["cases"]}

    expected_categories = [
        "none",
        "scope_overgeneralization",
        "numerical_mismatch",
        "citation_mismatch",
        "contradiction",
        "outdated_consensus",
        "unsupported_inference",
        "insufficient_data",
    ]
    for cat in expected_categories:
        assert cat in categories, f"Error category '{cat}' missing from dataset"


def test_abstention_and_warning_expectations():
    """Verify that cases requiring abstention specify warnings."""
    with open(EVALUATION_DATASET_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    abstention_cases = [c for c in data["cases"] if c.get("expected_abstention") is True]
    assert len(abstention_cases) >= 3, "Expected at least 3 abstention cases"

    for ac in abstention_cases:
        assert ac["expected_verdict"] == VerdictEnum.INSUFFICIENT_EVIDENCE.value
        assert ac.get("expected_warning") is not None
        assert "ABSTENTION" in ac["expected_warning"]


def test_benchmark_harness_gold_evaluation():
    """Verify that the evaluation harness computes 100% accuracy and 1.0 macro-F1 on gold predictions."""
    harness = VerificationBenchmarkHarness()
    assert len(harness.cases) >= 20

    gold_predictions = harness.generate_gold_predictions()
    report = harness.evaluate(gold_predictions)

    assert report.total_cases == len(harness.cases)
    assert report.correct_predictions == report.total_cases
    assert report.accuracy == 1.0
    assert report.macro_f1 == 1.0
    assert report.abstention_accuracy == 1.0

    # Every class should have precision and recall of 1.0
    for v, metrics in report.per_class_metrics.items():
        if metrics["support"] > 0:
            assert metrics["precision"] == 1.0
            assert metrics["recall"] == 1.0
            assert metrics["f1"] == 1.0


def test_benchmark_harness_imperfect_evaluation():
    """Verify that the evaluation harness correctly calculates degraded metrics on perturbed predictions."""
    harness = VerificationBenchmarkHarness()
    gold_predictions = harness.generate_gold_predictions()

    # Flip the first 4 predictions to a different verdict
    perturbed = []
    for i, p in enumerate(gold_predictions):
        if i < 4:
            new_v = VerdictEnum.CONTRADICTORY if p.predicted_verdict != VerdictEnum.CONTRADICTORY else VerdictEnum.SUPPORTED
            perturbed.append(EvaluationPrediction(case_id=p.case_id, predicted_verdict=new_v, predicted_strength=0.5))
        else:
            perturbed.append(p)

    report = harness.evaluate(perturbed)
    assert report.correct_predictions == report.total_cases - 4
    assert report.accuracy < 1.0
    assert report.macro_f1 < 1.0
