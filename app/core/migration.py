"""Database migration and schema upgrade engine for CiteVerify.

Ensures that:
1. Fresh databases are completely initialized with all tables and columns.
2. Existing databases are safely upgraded via ALTER TABLE without dropping or corrupting data.
3. The S4 cache_entries table and existing documents/results remain intact.
"""

import logging
from typing import Dict, List, Tuple
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.db import Base
import app.models.tables  # noqa: F401 - ensure all tables are registered on Base.metadata

logger = logging.getLogger("citeverify.db.migration")

SCHEMA_VERSION = 4

# New columns to ensure on existing tables:
# table_name -> list of (column_name, sql_type_and_default)
COLUMNS_TO_ENSURE: Dict[str, List[Tuple[str, str]]] = {
    "documents": [
        ("file_type", "VARCHAR(16)"),
        ("page_count", "INTEGER DEFAULT 1"),
        ("file_size_bytes", "INTEGER DEFAULT 0"),
    ],
    "references": [
        ("authors", "TEXT"),
        ("pmcid", "VARCHAR(64)"),
        ("url", "VARCHAR(1024)"),
        ("oa_pdf_url", "VARCHAR(1024)"),
        ("is_open_access", "BOOLEAN DEFAULT 0"),
        ("availability_state", "VARCHAR(64) DEFAULT 'unavailable'"),
        ("is_retracted", "BOOLEAN DEFAULT 0"),
        ("retraction_notice", "TEXT"),
        ("resolution_source", "VARCHAR(64)"),
        ("resolution_status", "VARCHAR(64) DEFAULT 'unresolved'"),
        ("doi_title_mismatch", "BOOLEAN DEFAULT 0"),
    ],
    "claims": [
        ("category", "VARCHAR(64) DEFAULT 'other'"),
        ("citation_key", "VARCHAR(64)"),
        ("original_sentence", "TEXT"),
        ("sentence_index", "INTEGER DEFAULT 0"),
        ("is_key_claim", "BOOLEAN DEFAULT 1"),
        ("numerical_values", "TEXT"),
        ("entities", "TEXT"),
        ("qualifiers", "TEXT"),
        ("experimental_conditions", "TEXT"),
        ("importance_score", "FLOAT DEFAULT 0.0"),
        ("extraction_method", "VARCHAR(64) DEFAULT 'deterministic_rule_based'"),
    ],
    "evidences": [
        ("claim_id", "VARCHAR(36)"),
        ("source_url", "VARCHAR(1024)"),
    ],
    "results": [
        ("reference_id", "VARCHAR(36)"),
        ("quote_verified", "BOOLEAN DEFAULT 0"),
        ("numerical_consistency", "VARCHAR(64) DEFAULT 'not_applicable'"),
        ("numerical_details", "TEXT"),
        ("scope_audit", "VARCHAR(64) DEFAULT 'consistent'"),
        ("scope_details", "TEXT"),
        ("is_retracted_source", "BOOLEAN DEFAULT 0"),
        ("retraction_warning", "TEXT"),
        ("contradiction_type", "VARCHAR(64)"),
        ("needs_human_review", "BOOLEAN DEFAULT 0"),
        ("ai_verdict", "VARCHAR(64)"),
        ("override_reason", "TEXT"),
        ("verification_method", "VARCHAR(64) DEFAULT 'gemini_assisted'"),
        ("fallback_reason", "VARCHAR(64)"),
        ("warnings", "TEXT"),
    ],
    "reviews": [
        ("updated_at", "TIMESTAMP"),
    ],
}


async def run_migrations(conn: AsyncConnection) -> int:
    """Execute schema creation and idempotent column upgrades on SQLite."""
    # 1. Create any missing tables (e.g., assessments, claim_references, schema_version)
    await conn.run_sync(Base.metadata.create_all)

    # 2. Inspect existing columns and apply ALTER TABLE for missing ones
    for table_name, columns in COLUMNS_TO_ENSURE.items():
        try:
            # Query existing column names for table (quote table name for reserved words like "references")
            res = await conn.execute(text(f'PRAGMA table_info("{table_name}")'))
            existing_cols = {row[1] for row in res.fetchall()}

            for col_name, col_def in columns:
                if col_name not in existing_cols:
                    logger.info(f"Upgrading schema: adding column '{col_name}' to table '{table_name}'")
                    alter_stmt = text(f'ALTER TABLE "{table_name}" ADD COLUMN {col_name} {col_def}')
                    await conn.execute(alter_stmt)
                    existing_cols.add(col_name)
        except Exception as exc:
            logger.warning(f"Error inspecting or upgrading table '{table_name}': {exc}")

    # 3. Track schema version
    await conn.execute(text(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        "version INTEGER PRIMARY KEY, "
        "applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        ")"
    ))
    await conn.execute(text(
        "INSERT OR REPLACE INTO schema_version (version, applied_at) "
        f"VALUES ({SCHEMA_VERSION}, CURRENT_TIMESTAMP)"
    ))

    logger.info(f"Database schema migration completed successfully (version {SCHEMA_VERSION}).")
    return SCHEMA_VERSION
