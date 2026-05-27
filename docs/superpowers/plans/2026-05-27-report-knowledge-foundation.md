# Report Knowledge Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first implementation slice of the enterprise report knowledge base: schema models, migration, deterministic object keys, and COS upload URL API shape.

**Architecture:** Keep document bodies in object storage and store only metadata, URIs, hashes, facts, outline, and chunk indexes in PostgreSQL. Start with database schema and object key generation so later OCR, PyMuPDF/Pillow rendering, RAG indexing, and frontend pages have stable contracts.

**Tech Stack:** FastAPI, SQLAlchemy ORM, Alembic, PostgreSQL, pgvector, Pydantic, Tencent COS patterns copied from `/Users/xinhuiwu/personalProj/finnav`.

---

## File Map

- Modify: `backend/app/models/models.py`
  Add ORM models for `mm_reports`, `mm_report_files`, `mm_report_pages`, `mm_report_facts`, `mm_report_outline_nodes`, and `mm_report_chunks`.
- Create: `backend/alembic/versions/20260527_create_mm_report_knowledge_base.py`
  Create the new tables, constraints, indexes, and pgvector column using `vector(1024)`.
- Create: `backend/app/reports/__init__.py`
  Package marker for report knowledge modules.
- Create: `backend/app/reports/storage_keys.py`
  Deterministic object key builders for `u/{owner_user_id}/r/{report_id}/...`.
- Create: `backend/app/reports/schemas.py`
  Pydantic request/response models for upload URL generation and report metadata.
- Create: `backend/app/reports/routes.py`
  Minimal API route for generating report upload object keys and future COS presigned URLs.
- Modify: `backend/app/main.py`
  Include the reports router.
- Modify: `backend/app/settings.py`
  Add optional Tencent COS settings matching the working `finnav` names.
- Create: `backend/test/test_report_knowledge_schema.py`
  Compile-level tests for ORM fields, table names, constraints, and indexes.
- Create: `backend/test/test_report_storage_keys.py`
  Unit tests for short object key generation.

## Task 1: Object Storage Key Builder

**Files:**
- Create: `backend/app/reports/__init__.py`
- Create: `backend/app/reports/storage_keys.py`
- Test: `backend/test/test_report_storage_keys.py`

- [ ] **Step 1: Write failing tests**

Create `backend/test/test_report_storage_keys.py` with tests for:

```python
import unittest

from app.reports.storage_keys import (
    layout_key,
    markdown_key,
    page_image_key,
    page_thumbnail_key,
    source_file_key,
)


class ReportStorageKeyTests(unittest.TestCase):
    def test_source_file_key_uses_short_owner_and_report_path(self) -> None:
        self.assertEqual(
            source_file_key("default", "report-1", "file-1", "pdf"),
            "u/default/r/report-1/source/file-1.pdf",
        )

    def test_page_keys_are_zero_padded(self) -> None:
        self.assertEqual(page_image_key("default", "report-1", 1), "u/default/r/report-1/pages/001.png")
        self.assertEqual(page_thumbnail_key("default", "report-1", 12), "u/default/r/report-1/pages/012-thumb.png")
        self.assertEqual(layout_key("default", "report-1", 3), "u/default/r/report-1/layout/003.json")

    def test_markdown_keys_are_fixed_names(self) -> None:
        self.assertEqual(markdown_key("default", "report-1", "original"), "u/default/r/report-1/md/original.md")
        self.assertEqual(markdown_key("default", "report-1", "current"), "u/default/r/report-1/md/current.md")

    def test_invalid_key_parts_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            source_file_key("default", "../report", "file-1", "pdf")
        with self.assertRaises(ValueError):
            markdown_key("default", "report-1", "draft")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify RED**

Run:

```bash
cd backend
uv run python -m unittest test.test_report_storage_keys
```

Expected: FAIL because `app.reports.storage_keys` does not exist.

- [ ] **Step 3: Implement storage key helpers**

Create `backend/app/reports/storage_keys.py` with:

```python
from typing import Literal


MarkdownKind = Literal["original", "current"]


def source_file_key(owner_user_id: str, report_id: str, file_id: str, extension: str) -> str:
    owner = _clean_part(owner_user_id, "owner_user_id")
    report = _clean_part(report_id, "report_id")
    file = _clean_part(file_id, "file_id")
    ext = _clean_extension(extension)
    return f"u/{owner}/r/{report}/source/{file}.{ext}"


def page_image_key(owner_user_id: str, report_id: str, page_number: int) -> str:
    return f"{_report_prefix(owner_user_id, report_id)}/pages/{_page_number(page_number)}.png"


def page_thumbnail_key(owner_user_id: str, report_id: str, page_number: int) -> str:
    return f"{_report_prefix(owner_user_id, report_id)}/pages/{_page_number(page_number)}-thumb.png"


def layout_key(owner_user_id: str, report_id: str, page_number: int) -> str:
    return f"{_report_prefix(owner_user_id, report_id)}/layout/{_page_number(page_number)}.json"


def markdown_key(owner_user_id: str, report_id: str, kind: MarkdownKind) -> str:
    if kind not in {"original", "current"}:
        raise ValueError("markdown kind must be original or current")
    return f"{_report_prefix(owner_user_id, report_id)}/md/{kind}.md"


def _report_prefix(owner_user_id: str, report_id: str) -> str:
    return f"u/{_clean_part(owner_user_id, 'owner_user_id')}/r/{_clean_part(report_id, 'report_id')}"


def _page_number(page_number: int) -> str:
    if page_number < 1:
        raise ValueError("page_number must be positive")
    return f"{page_number:03d}"


def _clean_extension(extension: str) -> str:
    ext = extension.removeprefix(".").strip().lower()
    return _clean_part(ext, "extension")


def _clean_part(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned or "/" in cleaned or "\\" in cleaned or cleaned in {".", ".."}:
        raise ValueError(f"{field_name} contains unsafe path characters")
    return cleaned
```

- [ ] **Step 4: Run test to verify GREEN**

Run:

```bash
cd backend
uv run python -m unittest test.test_report_storage_keys
```

Expected: PASS.

## Task 2: Report Knowledge ORM Models

**Files:**
- Modify: `backend/app/models/models.py`
- Test: `backend/test/test_report_knowledge_schema.py`

- [ ] **Step 1: Write failing compile-level model tests**

Create `backend/test/test_report_knowledge_schema.py` with tests that import the model classes and assert:

```python
import unittest

from app.models.models import (
    MmReport,
    MmReportChunk,
    MmReportFact,
    MmReportFile,
    MmReportOutlineNode,
    MmReportPage,
)


class ReportKnowledgeSchemaTests(unittest.TestCase):
    def test_report_tables_are_named_for_mm_knowledge_base(self) -> None:
        self.assertEqual(MmReport.__tablename__, "mm_reports")
        self.assertEqual(MmReportFile.__tablename__, "mm_report_files")
        self.assertEqual(MmReportPage.__tablename__, "mm_report_pages")
        self.assertEqual(MmReportFact.__tablename__, "mm_report_facts")
        self.assertEqual(MmReportOutlineNode.__tablename__, "mm_report_outline_nodes")
        self.assertEqual(MmReportChunk.__tablename__, "mm_report_chunks")

    def test_markdown_bodies_are_not_database_columns(self) -> None:
        column_names = set(MmReport.__table__.columns.keys())
        self.assertIn("original_markdown_uri", column_names)
        self.assertIn("current_markdown_uri", column_names)
        self.assertNotIn("original_markdown", column_names)
        self.assertNotIn("current_markdown", column_names)
        self.assertNotIn("ocr_text", set(MmReportPage.__table__.columns.keys()))

    def test_chunk_embedding_is_fixed_to_current_1024_dimensions(self) -> None:
        self.assertEqual(MmReportChunk.__table__.columns["embedding"].type.dim, 1024)

    def test_chunk_supports_cross_page_references(self) -> None:
        column_names = set(MmReportChunk.__table__.columns.keys())
        self.assertIn("primary_page_id", column_names)
        self.assertIn("page_start", column_names)
        self.assertIn("page_end", column_names)
        self.assertIn("page_refs", column_names)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify RED**

Run:

```bash
cd backend
uv run python -m unittest test.test_report_knowledge_schema
```

Expected: FAIL because the ORM classes do not exist.

- [ ] **Step 3: Implement ORM models**

Add focused SQLAlchemy models to `backend/app/models/models.py` after `MmCareSubjectAlias`. Use existing imports and add `Numeric` if needed. Define `MmReport`, `MmReportFile`, `MmReportPage`, `MmReportFact`, `MmReportOutlineNode`, `MmReportChunk` with fields from the design doc, including `Vector(1024)` and `search_vector`.

- [ ] **Step 4: Run schema tests**

Run:

```bash
cd backend
uv run python -m unittest test.test_report_knowledge_schema
```

Expected: PASS.

## Task 3: Alembic Migration

**Files:**
- Create: `backend/alembic/versions/20260527_create_mm_report_knowledge_base.py`
- Test: `backend/test/test_report_knowledge_schema.py`

- [ ] **Step 1: Write migration file from ORM shape**

Create the six new tables, check constraints, foreign keys, and indexes:

- `mm_reports`
- `mm_report_files`
- `mm_report_pages`
- `mm_report_facts`
- `mm_report_outline_nodes`
- `mm_report_chunks`

Use `pgvector.sqlalchemy.Vector(1024)` for chunk embeddings.

- [ ] **Step 2: Run compile checks**

Run:

```bash
cd backend
uv run python -m unittest test.test_report_knowledge_schema
```

Expected: PASS.

## Task 4: Minimal COS-Compatible Upload URL API Shape

**Files:**
- Modify: `backend/app/settings.py`
- Create: `backend/app/reports/schemas.py`
- Create: `backend/app/reports/routes.py`
- Modify: `backend/app/main.py`
- Test: `backend/test/test_report_upload_routes.py`

- [ ] **Step 1: Write route test with patched signer**

Test `POST /api/reports/uploads/presigned-url` returns a key under `u/default/r/{report_id}/source/` and a presigned URL when signer is patched.

- [ ] **Step 2: Implement schemas and route**

Keep route thin. Generate object key via `source_file_key`. Patchable signer boundary should be a function so tests do not require Tencent credentials.

- [ ] **Step 3: Run route test**

Run:

```bash
cd backend
uv run python -m unittest test.test_report_upload_routes
```

Expected: PASS.

## First Verification Gate

Run:

```bash
cd backend
uv run python -m unittest test.test_report_storage_keys test.test_report_knowledge_schema test.test_report_upload_routes
```

Expected: all tests PASS.
