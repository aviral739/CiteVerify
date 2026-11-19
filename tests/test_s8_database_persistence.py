"""Comprehensive test suite for S8 Database and Persistence Foundation.

Covers:
1. Fresh schema initialization.
2. Legacy database upgrade (ALTER TABLE without data loss).
3. SQLite foreign-key enforcement and cascades.
4. ClaimReference many-to-many relationships.
5. Evidence claim linkage.
6. Assessment persistence (S7 synthesis reports).
7. AI-generated Result and human Review separation.
8. Transaction atomicity and rollback.
9. Concurrent database operations with WAL/busy timeout.
10. S4 PersistentSQLiteCache compatibility.
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.db import Base, configure_sqlite_engine
from app.core.migration import run_migrations, SCHEMA_VERSION
from app.models.tables import (
    Assessment,
    AuditLog,
    Claim,
    ClaimReference,
    Document,
    Evidence,
    Job,
    Reference,
    Result,
    Review,
)
from app.repositories import (
    AssessmentRepository,
    AuditLogRepository,
    ClaimRepository,
    DocumentRepository,
    EvidenceRepository,
    JobRepository,
    ReferenceRepository,
    ReportRepository,
    ResultRepository,
    ReviewRepository,
)
from app.stages.s4_resolve.cache import PersistentSQLiteCache


# ---------------- Fixtures ----------------

@pytest_asyncio.fixture
async def sqlite_file_db(tmp_path: Path):
    """Provide a real disk-backed SQLite database with WAL and foreign keys enabled."""
    db_file = tmp_path / "test_s8.db"
    db_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    engine = create_async_engine(
        db_url,
        connect_args={"check_same_thread": False, "timeout": 30.0},
    )
    configure_sqlite_engine(engine, busy_timeout_ms=30000, enable_wal=True)

    session_factory = async_sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        class_=AsyncSession,
    )

    # Initialize schema
    async with engine.begin() as conn:
        await run_migrations(conn)

    yield session_factory, engine

    await engine.dispose()


# ---------------- 1. Schema Initialization ----------------

@pytest.mark.asyncio
async def test_fresh_schema_initialization(sqlite_file_db):
    """Verify fresh database initializes with all tables, columns, and schema_version."""
    session_factory, engine = sqlite_file_db

    async with session_factory() as session:
        # Check schema version
        res = await session.execute(text("SELECT version FROM schema_version"))
        version = res.scalar()
        assert version == SCHEMA_VERSION

        # Verify tables exist
        tables_res = await session.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        tables = {row[0] for row in tables_res.fetchall()}
        expected_tables = {
            "documents", "jobs", "events", "references", "claims",
            "claim_references", "evidences", "results", "reviews",
            "audit_logs", "cache_entries", "assessments", "schema_version"
        }
        for table in expected_tables:
            assert table in tables, f"Table '{table}' missing from database!"


# ---------------- 2. Existing Database Upgrade ----------------

@pytest.mark.asyncio
async def test_existing_database_upgrade_without_data_loss(tmp_path: Path):
    """Simulate an old database without new columns, verify upgrade preserves data."""
    db_file = tmp_path / "legacy.db"

    # Create raw legacy SQLite database with only original columns
    raw_conn = sqlite3.connect(db_file)
    raw_cur = raw_conn.cursor()
    raw_cur.execute("""
        CREATE TABLE documents (
            id VARCHAR(36) PRIMARY KEY,
            title VARCHAR(512) NOT NULL,
            doi VARCHAR(128),
            authors TEXT,
            file_path VARCHAR(1024),
            file_hash VARCHAR(64),
            status VARCHAR(64),
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        )
    """)
    raw_cur.execute("""
        CREATE TABLE cache_entries (
            id VARCHAR(36) PRIMARY KEY,
            cache_key VARCHAR(256) UNIQUE NOT NULL,
            service VARCHAR(64) NOT NULL,
            value TEXT NOT NULL,
            expires_at TIMESTAMP,
            created_at TIMESTAMP
        )
    """)
    # Insert existing data
    raw_cur.execute(
        "INSERT INTO documents (id, title, status) VALUES (?, ?, ?)",
        ("legacy-doc-123", "Legacy Pre-existing Manuscript", "completed")
    )
    raw_cur.execute(
        "INSERT INTO cache_entries (id, cache_key, service, value) VALUES (?, ?, ?, ?)",
        ("cache-1", "crossref:doi:10.1000/1", "crossref", '{"title": "Cached Data"}')
    )
    raw_conn.commit()
    raw_conn.close()

    # Now run migrations via CiteVerify engine
    db_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    engine = create_async_engine(db_url, connect_args={"check_same_thread": False})
    configure_sqlite_engine(engine, enable_wal=True)

    async with engine.begin() as conn:
        await run_migrations(conn)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession)
    async with session_factory() as session:
        # Verify legacy row is preserved
        doc_res = await session.execute(select(Document).where(Document.id == "legacy-doc-123"))
        doc = doc_res.scalar_one_or_none()
        assert doc is not None
        assert doc.title == "Legacy Pre-existing Manuscript"
        assert doc.status == "completed"
        # Check newly added columns have default values
        assert doc.file_size_bytes == 0
        assert doc.page_count == 1

        # Verify cache_entries preserved
        cache_res = await session.execute(text("SELECT value FROM cache_entries WHERE cache_key='crossref:doi:10.1000/1'"))
        cache_val = cache_res.scalar()
        assert cache_val == '{"title": "Cached Data"}'

        # Verify new tables were added
        res = await session.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='assessments'"))
        assert res.scalar() == "assessments"

    await engine.dispose()


# ---------------- 3. Foreign Key Cascades ----------------

@pytest.mark.asyncio
async def test_foreign_key_cascades(sqlite_file_db):
    """Verify deleting a Document cascades to References, Claims, Evidences, Results, and Assessments."""
    session_factory, _ = sqlite_file_db

    async with session_factory() as session:
        doc_repo = DocumentRepository(session)
        ref_repo = ReferenceRepository(session)
        claim_repo = ClaimRepository(session)
        ev_repo = EvidenceRepository(session)
        res_repo = ResultRepository(session)
        ass_repo = AssessmentRepository(session)

        # Create document hierarchy
        doc = await doc_repo.create(title="Cascade Test Paper", document_id="doc-cascade")
        ref = await ref_repo.create(document_id=doc.id, raw_citation="Ref 1", reference_id="ref-cascade")
        claim = await claim_repo.create(document_id=doc.id, claim_text="Claim 1", claim_id="claim-cascade", reference_id=ref.id)
        ev = await ev_repo.create(reference_id=ref.id, evidence_text="Evidence 1", evidence_id="ev-cascade", claim_id=claim.id)
        res = await res_repo.create(claim_id=claim.id, verdict="supported", result_id="res-cascade", evidence_id=ev.id, reference_id=ref.id)
        ass = await ass_repo.save_assessment(document_id=doc.id, overall_health_score=92.5, assessment_verdict="robust_support")

        await session.commit()

    # In a new session, delete the Document
    async with session_factory() as session:
        doc_repo = DocumentRepository(session)
        doc = await doc_repo.get_by_id("doc-cascade")
        assert doc is not None
        await doc_repo.delete(doc)
        await session.commit()

    # In another session, verify all children were cascade deleted
    async with session_factory() as session:
        ref_res = await session.execute(select(Reference).where(Reference.id == "ref-cascade"))
        assert ref_res.scalar_one_or_none() is None

        claim_res = await session.execute(select(Claim).where(Claim.id == "claim-cascade"))
        assert claim_res.scalar_one_or_none() is None

        ev_res = await session.execute(select(Evidence).where(Evidence.id == "ev-cascade"))
        assert ev_res.scalar_one_or_none() is None

        res_res = await session.execute(select(Result).where(Result.id == "res-cascade"))
        assert res_res.scalar_one_or_none() is None

        ass_res = await session.execute(select(Assessment).where(Assessment.document_id == "doc-cascade"))
        assert ass_res.scalar_one_or_none() is None


# ---------------- 4. ClaimReference Many-to-Many ----------------

@pytest.mark.asyncio
async def test_claim_reference_many_to_many(sqlite_file_db):
    """Verify claims citing multiple references via ClaimReference."""
    session_factory, _ = sqlite_file_db

    async with session_factory() as session:
        doc_repo = DocumentRepository(session)
        ref_repo = ReferenceRepository(session)
        claim_repo = ClaimRepository(session)

        doc = await doc_repo.create(title="M2M Citation Paper", document_id="doc-m2m")
        ref1 = await ref_repo.create(document_id=doc.id, raw_citation="Vaswani et al. 2017", citation_key="[1]")
        ref2 = await ref_repo.create(document_id=doc.id, raw_citation="Devlin et al. 2018", citation_key="[2]")

        claim = await claim_repo.create(
            document_id=doc.id,
            claim_text="Transformers and BERT revolutionized NLP [1, 2].",
            citation_key="[1, 2]",
        )

        # Link both references to this single claim
        await claim_repo.link_reference(claim_id=claim.id, reference_id=ref1.id, citation_key="[1]")
        await claim_repo.link_reference(claim_id=claim.id, reference_id=ref2.id, citation_key="[2]")
        await session.commit()

        # Query associations
        loaded_claim = await claim_repo.get_with_associations(claim.id)
        assert loaded_claim is not None
        assert len(loaded_claim.claim_references) == 2
        ref_ids = {cr.reference_id for cr in loaded_claim.claim_references}
        assert ref1.id in ref_ids
        assert ref2.id in ref_ids


# ---------------- 5. Evidence Claim Linkage ----------------

@pytest.mark.asyncio
async def test_evidence_claim_linkage(sqlite_file_db):
    """Verify evidence passages retain claim ownership and can be queried by claim."""
    session_factory, _ = sqlite_file_db

    async with session_factory() as session:
        doc_repo = DocumentRepository(session)
        ref_repo = ReferenceRepository(session)
        claim_repo = ClaimRepository(session)
        ev_repo = EvidenceRepository(session)

        doc = await doc_repo.create(title="Evidence Linkage Paper", document_id="doc-ev")
        ref = await ref_repo.create(document_id=doc.id, raw_citation="Reference A")
        claim = await claim_repo.create(document_id=doc.id, claim_text="Empirical finding 1")

        ev1 = await ev_repo.create(
            reference_id=ref.id,
            claim_id=claim.id,
            evidence_text="Methods passage for claim 1",
            section_title="Methods",
            retrieval_score=0.88,
        )
        ev2 = await ev_repo.create(
            reference_id=ref.id,
            claim_id=claim.id,
            evidence_text="Results passage for claim 1",
            section_title="Results",
            retrieval_score=0.94,
        )
        await session.commit()

        # Query by claim
        passages = await ev_repo.get_by_claim(claim.id)
        assert len(passages) == 2
        assert {p.section_title for p in passages} == {"Methods", "Results"}


# ---------------- 6. Assessment Persistence ----------------

@pytest.mark.asyncio
async def test_assessment_persistence_and_upsert(sqlite_file_db):
    """Verify saving complete S7 synthesis report and updating via upsert."""
    session_factory, _ = sqlite_file_db

    async with session_factory() as session:
        doc_repo = DocumentRepository(session)
        ass_repo = AssessmentRepository(session)

        doc = await doc_repo.create(title="Assessment Target Paper", document_id="doc-ass")

        s7_summary = {"supported": 8, "unsupported": 1, "contradictory": 0}
        s7_completeness = {"full_text_count": 7, "abstract_only_count": 2, "unavailable_count": 0}
        s7_factors = [{"category": "strength", "title": "High full text coverage", "impact_level": "positive"}]

        # 1. Create assessment
        ass = await ass_repo.save_assessment(
            document_id=doc.id,
            overall_health_score=85.0,
            confidence_score=0.90,
            assessment_verdict="robust_support",
            verdicts_summary=s7_summary,
            evidence_completeness=s7_completeness,
            factors=s7_factors,
            executive_summary="The manuscript displays strong evidentiary support.",
        )
        await session.commit()
        assert ass.overall_health_score == 85.0

        # 2. Update existing assessment (upsert)
        ass_updated = await ass_repo.save_assessment(
            document_id=doc.id,
            overall_health_score=89.5,
            confidence_score=0.95,
            assessment_verdict="robust_support",
            executive_summary="Updated assessment after human confirmation.",
        )
        await session.commit()
        assert ass_updated.id == ass.id
        assert ass_updated.overall_health_score == 89.5
        assert "Updated" in ass_updated.executive_summary


# ---------------- 7. Result and Review Separation ----------------

@pytest.mark.asyncio
async def test_result_and_review_separation(sqlite_file_db):
    """Verify AI-generated verdicts in Result remain untouched by human Reviews."""
    session_factory, _ = sqlite_file_db

    async with session_factory() as session:
        doc_repo = DocumentRepository(session)
        claim_repo = ClaimRepository(session)
        res_repo = ResultRepository(session)
        rev_repo = ReviewRepository(session)

        doc = await doc_repo.create(title="Review Separation Paper")
        claim = await claim_repo.create(document_id=doc.id, claim_text="AI evaluated claim")

        # Automated AI result
        res = await res_repo.create(
            claim_id=claim.id,
            verdict="partially_supported",
            verdict_strength=0.72,
            explanation="Automated LLM NLI found hedge in source.",
            numerical_consistency="exact_match",
            scope_audit="hedged",
        )
        await session.commit()

        # Human override review
        review = await rev_repo.create(
            result_id=res.id,
            reviewer_id="expert_reviewer_1",
            human_decision="overridden",
            human_verdict="supported",
            notes="Source methodology supports the claim unconditionally upon re-reading.",
        )
        await session.commit()

        # Query result with reviews
        loaded_res = await res_repo.get_with_reviews(res.id)
        assert loaded_res is not None
        # AI verdict is unchanged
        assert loaded_res.verdict == "partially_supported"
        assert loaded_res.numerical_consistency == "exact_match"
        # Human review is preserved separately
        assert len(loaded_res.reviews) == 1
        assert loaded_res.reviews[0].human_decision == "overridden"
        assert loaded_res.reviews[0].human_verdict == "supported"


# ---------------- 8. Transaction Rollback ----------------

@pytest.mark.asyncio
async def test_transaction_rollback_on_error(sqlite_file_db):
    """Verify that errors within a transaction rollback all staged operations."""
    session_factory, _ = sqlite_file_db

    async with session_factory() as session:
        doc_repo = DocumentRepository(session)
        claim_repo = ClaimRepository(session)

        doc = await doc_repo.create(title="Rollback Test Paper", document_id="doc-rollback")
        await session.commit()

    # Attempt transaction that fails mid-way
    try:
        async with session_factory() as session:
            claim_repo = ClaimRepository(session)
            await claim_repo.create(document_id="doc-rollback", claim_text="Uncommitted Claim", claim_id="claim-temp")
            # Force failure: insert claim with non-existent foreign key (violates foreign key constraint)
            bad_claim = Claim(
                id="claim-bad-fk",
                document_id="non-existent-doc-id-xyz",
                claim_text="Invalid FK Claim",
            )
            session.add(bad_claim)
            await session.commit()
    except Exception:
        # Expected constraint failure
        pass

    # Verify claim-temp was rolled back and does not exist
    async with session_factory() as session:
        claim_res = await session.execute(select(Claim).where(Claim.id == "claim-temp"))
        assert claim_res.scalar_one_or_none() is None


# ---------------- 9. Concurrent Database Access ----------------

@pytest.mark.asyncio
async def test_concurrent_database_access(sqlite_file_db):
    """Verify multiple concurrent tasks can write and read without database locked errors."""
    session_factory, _ = sqlite_file_db

    async def worker_write(index: int):
        async with session_factory() as session:
            doc_repo = DocumentRepository(session)
            doc = await doc_repo.create(
                title=f"Concurrent Paper {index}",
                document_id=f"doc-conc-{index}",
                page_count=index + 1,
            )
            await session.commit()
            return doc.id

    # Run 10 concurrent writes
    results = await asyncio.gather(*(worker_write(i) for i in range(10)))
    assert len(results) == 10

    # Read back all documents
    async with session_factory() as session:
        doc_repo = DocumentRepository(session)
        docs = await doc_repo.list_documents(limit=50)
        assert len(docs) >= 10


# ---------------- 10. S4 Cache Compatibility ----------------

@pytest.mark.asyncio
async def test_s4_cache_compatibility_on_shared_db(sqlite_file_db):
    """Verify S4 PersistentSQLiteCache works seamlessly on the hardened database."""
    session_factory, _ = sqlite_file_db

    cache = PersistentSQLiteCache(session_factory=session_factory)

    # Set positive cache
    success = await cache.set("crossref", "doi:10.1000/182", {"title": "Sample Paper", "year": 2021})
    assert success is True

    # Get positive cache hit
    is_hit, val = await cache.get("crossref", "doi:10.1000/182")
    assert is_hit is True
    assert val["title"] == "Sample Paper"

    # Set negative cache (404)
    await cache.set("openalex", "doi:10.9999/not_found", None)
    is_hit_neg, val_neg = await cache.get("openalex", "doi:10.9999/not_found")
    assert is_hit_neg is True
    assert val_neg is None

    # Delete cache key
    deleted = await cache.delete("crossref", "doi:10.1000/182")
    assert deleted is True
    is_hit_after, _ = await cache.get("crossref", "doi:10.1000/182")
    assert is_hit_after is False


# ---------------- 11. Report Repository Aggregation ----------------

@pytest.mark.asyncio
async def test_full_report_repository_retrieval(sqlite_file_db):
    """Verify ReportRepository aggregates Document, Assessment, Claims, References, and Results."""
    session_factory, _ = sqlite_file_db

    async with session_factory() as session:
        doc_repo = DocumentRepository(session)
        ref_repo = ReferenceRepository(session)
        claim_repo = ClaimRepository(session)
        ev_repo = EvidenceRepository(session)
        res_repo = ResultRepository(session)
        ass_repo = AssessmentRepository(session)
        rep_repo = ReportRepository(session)

        # 1. Create document
        doc = await doc_repo.create(
            title="Complete Report Synthesis Paper",
            doi="10.1038/s41586-020-0001-x",
            authors="Alice Smith, Bob Jones",
            file_type="pdf",
            page_count=12,
            status="completed",
        )

        # 2. Create references
        ref1 = await ref_repo.create(
            document_id=doc.id,
            raw_citation="Reference 1",
            citation_key="[1]",
            resolved_title="Foundational Paper",
            resolved_doi="10.1000/1",
        )

        # 3. Create claims
        claim1 = await claim_repo.create(
            document_id=doc.id,
            claim_text="Transformers exceed RNN efficiency.",
            citation_key="[1]",
            category="finding",
            is_key_claim=True,
            numerical_values=["2.5x"],
        )
        await claim_repo.link_reference(claim_id=claim1.id, reference_id=ref1.id, citation_key="[1]")

        # 4. Create evidence
        ev1 = await ev_repo.create(
            reference_id=ref1.id,
            claim_id=claim1.id,
            evidence_text="Transformers demonstrated 2.5x faster training speed.",
            section_title="Results",
            retrieval_score=0.96,
        )

        # 5. Create results
        await res_repo.create(
            claim_id=claim1.id,
            evidence_id=ev1.id,
            reference_id=ref1.id,
            verdict="supported",
            verdict_strength=0.95,
            quote_verified=True,
            numerical_consistency="exact_match",
            scope_audit="consistent",
        )

        # 6. Create assessment
        await ass_repo.save_assessment(
            document_id=doc.id,
            overall_health_score=94.0,
            confidence_score=0.92,
            assessment_verdict="robust_support",
            verdicts_summary={"supported": 1, "unsupported": 0},
            evidence_completeness={"full_text_count": 1},
            executive_summary="Solid evidentiary support across claims.",
            limitations_disclaimer="Assessed with automated NLI pipeline.",
        )

        await session.commit()

        # Retrieve aggregated report
        report = await rep_repo.get_full_report(doc.id)
        assert report is not None
        assert report["document"].title == "Complete Report Synthesis Paper"
        assert report["total_references"] == 1
        assert report["total_claims"] == 1
        assert report["total_results"] == 1
        assert report["results_summary"]["supported"] == 1
        assert report["assessment"] is not None
        assert report["assessment"]["overall_health_score"] == 94.0
        assert report["assessment"]["assessment_verdict"] == "robust_support"
        assert report["assessment"]["limitations_disclaimer"] == "Assessed with automated NLI pipeline."


# ---------------- 12. S1–S7 Rich Metadata Preservation ----------------

@pytest.mark.asyncio
async def test_rich_metadata_preservation_s1_through_s7(sqlite_file_db):
    """Verify all rich metadata fields from S1 through S7 are fully stored and retrieved."""
    session_factory, _ = sqlite_file_db

    async with session_factory() as session:
        doc_repo = DocumentRepository(session)
        ref_repo = ReferenceRepository(session)
        claim_repo = ClaimRepository(session)
        res_repo = ResultRepository(session)
        ass_repo = AssessmentRepository(session)

        # S1: Document with file_type and page_count
        doc = await doc_repo.create(
            title="Rich Metadata Paper",
            file_type="docx",
            page_count=25,
            file_size_bytes=524288,
        )

        # S4: Reference with PMCID, retraction notice, and mismatch
        ref = await ref_repo.create(
            document_id=doc.id,
            raw_citation="Retracted Study in PMC",
            citation_key="[1]",
            resolved_doi="10.1000/retracted",
            pmcid="PMC9999999",
            is_retracted=True,
            retraction_notice="Retraction notice published due to fabricated results.",
            doi_title_mismatch=True,
            availability_state="full_text_available",
            resolution_source="europe_pmc",
        )

        # S3: Claim with category, numerical values, and key-claim status
        claim = await claim_repo.create(
            document_id=doc.id,
            claim_text="Enzyme reaction rate was 0.42 s^-1.",
            category="numerical_result",
            is_key_claim=True,
            numerical_values=["0.42 s^-1"],
            entities=["Cas9", "endonuclease"],
            qualifiers=["in vitro"],
            importance_score=0.85,
        )

        # S6: Result with quote verification, scope audit, and numerical consistency
        res = await res_repo.create(
            claim_id=claim.id,
            reference_id=ref.id,
            verdict="contradictory",
            verdict_strength=0.91,
            quote_verified=True,
            numerical_consistency="mismatch",
            numerical_details="Claim states 0.42 s^-1, source reports 0.24 s^-1.",
            scope_audit="overgeneralized",
            scope_details="Claim generalizes to all mammals, paper tested in vitro only.",
            is_retracted_source=True,
            retraction_warning="Source paper retracted.",
            needs_human_review=True,
        )

        # S7: Assessment with discrepancies, factors, and limitations disclaimer
        ass = await ass_repo.save_assessment(
            document_id=doc.id,
            overall_health_score=42.0,
            confidence_score=0.88,
            assessment_verdict="high_concerns",
            discrepancies={"numerical_mismatch_count": 1, "retracted_source_count": 1},
            factors=[{"category": "risk", "title": "Retracted source cited", "impact_level": "critical"}],
            methodology_notes="Deterministic verification with lexical retrieval.",
            limitations_disclaimer="Heuristic index; human audit advised for high-stakes decisions.",
        )

        await session.commit()

    # Query back in a clean session and assert all rich metadata fields
    async with session_factory() as session:
        # 1. Document
        doc_q = await session.execute(select(Document).where(Document.id == doc.id))
        saved_doc = doc_q.scalar_one()
        assert saved_doc.file_type == "docx"
        assert saved_doc.page_count == 25
        assert saved_doc.file_size_bytes == 524288

        # 2. Reference
        ref_q = await session.execute(select(Reference).where(Reference.id == ref.id))
        saved_ref = ref_q.scalar_one()
        assert saved_ref.pmcid == "PMC9999999"
        assert saved_ref.is_retracted is True
        assert "fabricated results" in (saved_ref.retraction_notice or "")
        assert saved_ref.doi_title_mismatch is True
        assert saved_ref.availability_state == "full_text_available"
        assert saved_ref.resolution_source == "europe_pmc"

        # 3. Claim
        claim_q = await session.execute(select(Claim).where(Claim.id == claim.id))
        saved_claim = claim_q.scalar_one()
        assert saved_claim.category == "numerical_result"
        assert saved_claim.is_key_claim is True
        assert "0.42 s^-1" in (saved_claim.numerical_values or "")
        assert "Cas9" in (saved_claim.entities or "")

        # 4. Result
        res_q = await session.execute(select(Result).where(Result.id == res.id))
        saved_res = res_q.scalar_one()
        assert saved_res.quote_verified is True
        assert saved_res.numerical_consistency == "mismatch"
        assert "0.42 s^-1" in (saved_res.numerical_details or "")
        assert saved_res.scope_audit == "overgeneralized"
        assert saved_res.is_retracted_source is True
        assert saved_res.needs_human_review is True

        # 5. Assessment
        ass_q = await session.execute(select(Assessment).where(Assessment.document_id == doc.id))
        saved_ass = ass_q.scalar_one()
        assert saved_ass.overall_health_score == 42.0
        assert saved_ass.assessment_verdict == "high_concerns"
        assert "Retracted source cited" in (saved_ass.factors or "")
        assert "human audit advised" in (saved_ass.limitations_disclaimer or "")
