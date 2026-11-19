"""Tests for scientific paper fixtures and fixtures manifest."""

import json
from pathlib import Path
import zipfile
import pytest

from tests.fixtures import DOCUMENTS_DIR, MANIFEST_PATH


def test_fixtures_directory_and_manifest_exist():
    """Verify that documents directory and fixtures manifest exist."""
    assert DOCUMENTS_DIR.exists()
    assert DOCUMENTS_DIR.is_dir()
    assert MANIFEST_PATH.exists()
    assert MANIFEST_PATH.is_file()


def test_manifest_structure_and_coverage():
    """Verify manifest schema and that all required feature types are covered."""
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    assert "fixtures" in manifest
    fixtures = manifest["fixtures"]
    assert len(fixtures) == 10

    all_features = set()
    formats = set()

    for item in fixtures:
        assert "fixture_id" in item
        assert "file_name" in item
        assert "format" in item
        assert "title" in item
        assert "primary_features" in item
        assert "expected_sections" in item
        assert "expected_references" in item
        assert "expected_claims" in item
        assert "expected_anomalies" in item

        formats.add(item["format"])
        for feat in item["primary_features"]:
            all_features.add(feat)

        # File must exist on disk
        fixture_file = DOCUMENTS_DIR / item["file_name"]
        assert fixture_file.exists(), f"Missing fixture file: {item['file_name']}"
        assert fixture_file.stat().st_size > 0, f"Empty fixture file: {item['file_name']}"

    # Required formats
    assert "pdf" in formats
    assert "docx" in formats

    # Verify all 8 core feature categories are covered
    required_features = [
        "numeric_citations",
        "author_year_citations",
        "missing_references",
        "duplicate_dois",
        "malformed_references",
        "tables",
        "scientific_notation",
        "scanned_image_only",
    ]
    for rf in required_features:
        assert rf in all_features, f"Required feature '{rf}' missing from corpus coverage"


def test_pdf_fixture_validity():
    """Verify PDF files start with standard %PDF- header and have valid trailers."""
    pdf_files = list(DOCUMENTS_DIR.glob("*.pdf"))
    assert len(pdf_files) == 8

    for pdf_path in pdf_files:
        content = pdf_path.read_bytes()
        assert content.startswith(b"%PDF-"), f"{pdf_path.name} does not start with %PDF-"
        assert b"%%EOF" in content, f"{pdf_path.name} missing %%EOF marker"
        assert b"/Root" in content, f"{pdf_path.name} missing /Root catalog reference"


def test_scanned_image_pdf_structure():
    """Verify the scanned PDF fixture contains an Image XObject and no raw text font streams."""
    scanned_path = DOCUMENTS_DIR / "fixture_08_scanned_image_only.pdf"
    assert scanned_path.exists()
    content = scanned_path.read_bytes()

    assert b"/Subtype /Image" in content
    assert b"/DeviceGray" in content
    # Scanned image fixture must not contain standard text font resources
    assert b"/Font" not in content
    assert b"BT\n" not in content


def test_docx_fixture_validity():
    """Verify DOCX files are valid PKZip archives containing word/document.xml."""
    docx_files = list(DOCUMENTS_DIR.glob("*.docx"))
    assert len(docx_files) == 2

    for docx_path in docx_files:
        assert zipfile.is_zipfile(docx_path), f"{docx_path.name} is not a valid zip archive"
        with zipfile.ZipFile(docx_path, "r") as z:
            names = z.namelist()
            assert "[Content_Types].xml" in names
            assert "_rels/.rels" in names
            assert "word/document.xml" in names

            doc_xml = z.read("word/document.xml").decode("utf-8")
            assert "<w:document" in doc_xml
            assert "</w:document>" in doc_xml


def test_fixture_anomaly_expectations():
    """Verify ground-truth anomalies in manifest for Stage 1-4 pipeline validation."""
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    fixtures_by_id = {f["fixture_id"]: f for f in manifest["fixtures"]}

    # Missing references fixture (FIX-03)
    fix_03 = fixtures_by_id["FIX-03"]
    assert len(fix_03["expected_anomalies"]["missing_references"]) >= 2
    assert "[3]" in fix_03["expected_anomalies"]["missing_references"]

    # Duplicate DOIs fixture (FIX-04)
    fix_04 = fixtures_by_id["FIX-04"]
    assert len(fix_04["expected_anomalies"]["duplicate_dois"]) >= 1
    assert "10.1038/s41586-020-2649-2" in fix_04["expected_anomalies"]["duplicate_dois"]

    # Malformed references fixture (FIX-05)
    fix_05 = fixtures_by_id["FIX-05"]
    assert len(fix_05["expected_anomalies"]["malformed_references"]) >= 2

    # Scanned image fixture (FIX-08)
    fix_08 = fixtures_by_id["FIX-08"]
    assert fix_08["expected_anomalies"]["scanned_image_only"] is True
    assert fix_08["expected_anomalies"]["ocr_required"] is True
