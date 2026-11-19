"""Test fixtures package for CiteVerify test corpus and evaluation infrastructure."""

from pathlib import Path

FIXTURES_DIR = Path(__file__).parent
DOCUMENTS_DIR = FIXTURES_DIR / "documents"
MANIFEST_PATH = FIXTURES_DIR / "fixtures_manifest.json"
EVALUATION_DATASET_PATH = FIXTURES_DIR / "evaluation_dataset.json"

from tests.fixtures.evaluation_harness import (
    EvaluationCase,
    EvaluationPrediction,
    EvaluationReport,
    VerificationBenchmarkHarness,
)

__all__ = [
    "FIXTURES_DIR",
    "DOCUMENTS_DIR",
    "MANIFEST_PATH",
    "EVALUATION_DATASET_PATH",
    "EvaluationCase",
    "EvaluationPrediction",
    "EvaluationReport",
    "VerificationBenchmarkHarness",
]
