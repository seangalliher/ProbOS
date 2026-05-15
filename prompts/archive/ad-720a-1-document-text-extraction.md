# AD-720a-1 — PDF / DOCX / XLSX text extraction for chat attachments

**Wave:** 162
**Closes:** #562
**Status:** ready to build
**Dependencies:** AD-720d (Wave 139 — text/JSON/CSV extraction shipped at `src/probos/cognitive/text_extractor.py`).
**Estimated tests:** +12 pytest (4 per MIME × happy / oversize / corrupt + dispatcher routing).
**Scope tag:** **Adds 3 new pip deps** — `pypdf`, `python-docx`, `openpyxl`. All permissive (BSD-3 / MIT / MIT). Captain approval required at acceptance.

---

## License disposition (REQUIRED — Captain awareness)

| Package | Min version | License | OSS posture | Source of truth |
|---------|-------------|---------|-------------|-----------------|
| `pypdf` | `>=4.0` | **BSD-3-Clause** | Compatible with Apache 2.0 | pypi.org/project/pypdf/ |
| `python-docx` | `>=1.1` | **MIT** | Compatible with Apache 2.0 | pypi.org/project/python-docx/ |
| `openpyxl` | `>=3.1` | **MIT** | Compatible with Apache 2.0 | pypi.org/project/openpyxl/ |

All three are permissive and OSS-clean per the Captain rule (MIT > BSD > Apache). No copyleft, no commercial-license dependencies, no model-weight side artifacts. Each goes into `[project.dependencies]` (mandatory, not optional) per the issue body. The Builder must verify the live PyPI metadata at install time matches these licenses (run `pip show pypdf python-docx openpyxl` after install and confirm each `License:` field) — surface to Architect if drift detected.

---

## Problem

`src/probos/cognitive/text_extractor.py` (AD-720d, Wave 139) handles `text/plain`, `text/markdown`, `text/csv`, `application/json`. PDF currently raises `NotImplementedError("AD-720a-1: PDF extraction not yet wired")` (line 44). DOCX and XLSX fall through to the `ValueError(f"unsupported MIME for text extraction: {mime!r}")` branch.

The Captain wants to attach PDFs/DOCX/XLSX in chat and have the agent reason over their text content (same `<ATTACHMENT>` block pattern AD-720d already wires for plaintext).

---

## Solution overview

1. Add `pypdf`, `python-docx`, `openpyxl` to `pyproject.toml` `[project.dependencies]`.
2. Add three new helpers to `src/probos/cognitive/text_extractor.py`:
   - `_extract_pdf(blob: bytes, max_bytes: int) -> tuple[str, bool]` — page-by-page, max 100 pages.
   - `_extract_docx(blob: bytes, max_bytes: int) -> tuple[str, bool]` — paragraphs + table cells.
   - `_extract_xlsx(blob: bytes, max_bytes: int) -> tuple[str, bool]` — cell-by-cell, max 10k rows total across sheets.
3. Replace the `if mime == "application/pdf"` block with a per-MIME dispatch table mapping `application/pdf` / `application/vnd.openxmlformats-officedocument.wordprocessingml.document` / `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` to the new helpers.
4. Add `AttachmentsConfig.pdf_extraction_enabled: bool = False` (default-OFF transitional flag per Wave 10 convention #14 — flip to True in AD-720a-1-1 grandchild AD).
5. Wire the call site in `routers/agents.py` (the existing `extract_text` caller) to honor the flag — if `pdf_extraction_enabled=False` and the MIME is PDF/DOCX/XLSX, fall back to the existing AD-720d "honest degrade" path (file attached as opaque ref, no inline text).

### What this does NOT change

- The image / vision pipeline (AD-731 attachment-ref invariant preserved — image bytes still flow through `AttachmentStore` SHA-256 refs, never through `text_extractor`).
- The `<ATTACHMENT>` block delimiter pattern in `routers/agents.py`.
- AD-720d behavior for text/plain, text/markdown, text/csv, application/json.
- The on-disk attachment storage layout.
- The `text_extraction_max_bytes` cap (the same cap applies to all MIME branches).

---

## Section 1 — `pyproject.toml` dependencies

Single SEARCH/REPLACE adding the three deps to the existing `[project.dependencies]` list. Builder: read `pyproject.toml` first, locate the dependencies block, and add the three lines in alphabetical position.

```toml
"openpyxl>=3.1",
"pypdf>=4.0",
"python-docx>=1.1",
```

Run `uv pip install -e .` (or `pip install -e .`) and confirm each license via `pip show`. Capture license strings in the build report.

---

## Section 2 — `_extract_pdf` helper

Add after the existing `_TEXT_PASSTHROUGH_MIMES` constant:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

_MAX_PDF_PAGES = 100


def _extract_pdf(blob: bytes, max_bytes: int) -> tuple[str, bool]:
    """Extract text from PDF bytes, page-by-page, capped at 100 pages.

    Returns ``(text, was_truncated)``. Truncation can be either page-cap
    or byte-cap triggered.
    """
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(blob))
    pages = reader.pages[:_MAX_PDF_PAGES]
    page_truncated = len(reader.pages) > _MAX_PDF_PAGES

    parts: list[str] = []
    running_bytes = 0
    byte_truncated = False
    for idx, page in enumerate(pages):
        try:
            page_text = page.extract_text() or ""
        except Exception:
            logger.warning(
                "AD-720a-1: pypdf failed on page %d; skipping",
                idx,
                exc_info=True,
            )
            page_text = ""
        chunk = f"\n--- Page {idx + 1} ---\n{page_text}"
        encoded = chunk.encode("utf-8")
        if running_bytes + len(encoded) > max_bytes:
            remaining = max_bytes - running_bytes
            if remaining > 0:
                parts.append(encoded[:remaining].decode("utf-8", errors="ignore"))
            byte_truncated = True
            break
        parts.append(chunk)
        running_bytes += len(encoded)

    text = "".join(parts).lstrip("\n")
    truncated = page_truncated or byte_truncated
    if truncated:
        text = text + "\n[TRUNCATED]"
    return (text, truncated)
```

Tier-2 honest-degrade: malformed PDFs (`pypdf` raises `PdfReadError` or generic Exception during construction) bubble up to the caller as a `ValueError` with a descriptive message — caller decides whether to surface to the user or honest-degrade to "file attached, contents not extractable."

---

## Section 3 — `_extract_docx` helper

```python
def _extract_docx(blob: bytes, max_bytes: int) -> tuple[str, bool]:
    """Extract text from DOCX bytes: paragraphs + table cells, in document order."""
    import io

    from docx import Document

    doc = Document(io.BytesIO(blob))

    parts: list[str] = []
    running_bytes = 0
    truncated = False

    # Paragraphs.
    for para in doc.paragraphs:
        text = para.text
        if not text:
            continue
        encoded = (text + "\n").encode("utf-8")
        if running_bytes + len(encoded) > max_bytes:
            remaining = max_bytes - running_bytes
            if remaining > 0:
                parts.append(encoded[:remaining].decode("utf-8", errors="ignore"))
            truncated = True
            break
        parts.append(text + "\n")
        running_bytes += len(encoded)

    # Tables (only if byte budget remains).
    if not truncated:
        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text for cell in row.cells) + "\n"
                encoded = row_text.encode("utf-8")
                if running_bytes + len(encoded) > max_bytes:
                    remaining = max_bytes - running_bytes
                    if remaining > 0:
                        parts.append(encoded[:remaining].decode("utf-8", errors="ignore"))
                    truncated = True
                    break
                parts.append(row_text)
                running_bytes += len(encoded)
            if truncated:
                break

    text = "".join(parts)
    if truncated:
        text = text + "\n[TRUNCATED]"
    return (text, truncated)
```

---

## Section 4 — `_extract_xlsx` helper

```python
_MAX_XLSX_ROWS = 10_000


def _extract_xlsx(blob: bytes, max_bytes: int) -> tuple[str, bool]:
    """Extract text from XLSX bytes: sheet-by-sheet, cell-by-cell, max 10k rows total."""
    import io

    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(blob), data_only=True, read_only=True)

    parts: list[str] = []
    running_bytes = 0
    rows_emitted = 0
    truncated = False

    for sheet_name in wb.sheetnames:
        if truncated:
            break
        ws = wb[sheet_name]
        parts.append(f"\n=== Sheet: {sheet_name} ===\n")
        running_bytes += len(parts[-1].encode("utf-8"))

        for row in ws.iter_rows(values_only=True):
            if rows_emitted >= _MAX_XLSX_ROWS:
                truncated = True
                break
            row_text = " | ".join("" if v is None else str(v) for v in row) + "\n"
            encoded = row_text.encode("utf-8")
            if running_bytes + len(encoded) > max_bytes:
                remaining = max_bytes - running_bytes
                if remaining > 0:
                    parts.append(encoded[:remaining].decode("utf-8", errors="ignore"))
                truncated = True
                break
            parts.append(row_text)
            running_bytes += len(encoded)
            rows_emitted += 1

    wb.close()
    text = "".join(parts).lstrip("\n")
    if truncated:
        text = text + "\n[TRUNCATED]"
    return (text, truncated)
```

---

## Section 5 — Dispatch table in `extract_text`

Replace the `if mime == "application/pdf": raise NotImplementedError` line with a dispatch lookup. Single `replace_string_in_file` (BF-274).

```python
_DISPATCH = {
    "application/pdf": _extract_pdf,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": _extract_docx,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": _extract_xlsx,
}

# ...inside extract_text(), replacing the NotImplementedError branch:
if mime in _DISPATCH:
    return _DISPATCH[mime](blob, max_bytes)
```

---

## Section 6 — `AttachmentsConfig.pdf_extraction_enabled` flag

In `src/probos/config.py`, add to the existing `AttachmentsConfig` (which already has `vision_tier`, `text_extraction_max_bytes` per existing line 1231 docstring):

```python
# AD-720a-1: PDF/DOCX/XLSX inline extraction. Default-OFF transitional flag
# per Wave 10 convention #14. Flipped to True in AD-720a-1-1 grandchild AD
# once operator feedback confirms quality.
pdf_extraction_enabled: bool = False
```

Field validator: none needed — bool default = False is the safe transitional state.

---

## Section 7 — Call-site gate in `routers/agents.py`

Locate the existing `extract_text` caller (currently routes plaintext/JSON/CSV). Add a gate so PDF/DOCX/XLSX MIMEs respect the flag:

```python
if mime in {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
} and not runtime.config.attachments.pdf_extraction_enabled:
    # Honest-degrade: file attached as opaque ref, no inline text.
    # Matches the AD-720d unsupported-MIME fallback shape.
    continue  # or whatever the existing skip pattern is — verify against the live caller
```

Builder: read the existing `extract_text` caller in `routers/agents.py` before writing this section. The exact skip pattern (continue / log+continue / return-honest-degrade-block) must match what AD-720d uses for unsupported MIMEs today — preserve the existing UX contract.

---

## Tests

`tests/test_ad720a_1_document_extraction.py` — 12 tests:

1. `test_pdf_happy_path` — 3-page PDF, full text returned, `was_truncated=False`.
2. `test_pdf_page_cap` — 150-page PDF, only 100 pages extracted, `was_truncated=True`, `[TRUNCATED]` suffix.
3. `test_pdf_byte_cap` — small `max_bytes`, truncation at byte boundary.
4. `test_pdf_corrupt_bytes_raises` — random bytes raise ValueError-or-bubble.
5. `test_docx_paragraphs_and_tables` — DOCX with paragraphs + 1 table, both extracted in order.
6. `test_docx_byte_cap` — truncation honored.
7. `test_docx_corrupt_bytes_raises`.
8. `test_xlsx_multiple_sheets` — 2 sheets, both included with `=== Sheet: N ===` headers.
9. `test_xlsx_row_cap` — 12k rows, only 10k emitted, `[TRUNCATED]`.
10. `test_xlsx_byte_cap`.
11. `test_dispatch_unknown_mime_still_raises_value_error` — regression: AD-720d MIMEs still rejected at unknown branch.
12. `test_pdf_extraction_disabled_flag_path` — when `pdf_extraction_enabled=False`, the caller in `routers/agents.py` falls back to AD-720d honest-degrade. (Use a real `SystemConfig()` per AD-722b-1a — no MagicMock.)

Fixtures: build the test PDFs / DOCX / XLSX in-memory using `pypdf.PdfWriter`, `python-docx`'s `Document()`, `openpyxl.Workbook()`. No on-disk test fixtures (keeps the repo clean).

---

## Tracking

- `PROGRESS.md` — Wave 162 bullet, dep additions listed.
- `docs/development/roadmap.md` — flip AD-720a-1 row from forward marker to SHIPPED Wave 162; file forward markers AD-720a-1-1 (flip flag to True after operator feedback) and AD-720a-1-2 (OCR pipeline for scanned PDFs — image-bearing pages).
- `DECISIONS.md` — append AD-720a-1 entry with the three-dep license disposition and the dispatch-table design.
- `THIRD_PARTY_LICENSES.md` — append entries for pypdf (BSD-3), python-docx (MIT), openpyxl (MIT).

---

## Acceptance criteria

- Three deps added to `pyproject.toml` with `>=` minimums; `pip show` confirms BSD-3 / MIT / MIT.
- `text_extractor.py` dispatch table + three helpers landed; AD-720d behavior unchanged.
- `AttachmentsConfig.pdf_extraction_enabled` default False; flipping to True in a test fixture activates the new path.
- `routers/agents.py` gate respects the flag.
- 12 new pytest tests green at `-n 0` and under `-n 4 --dist=loadfile`.
- `THIRD_PARTY_LICENSES.md` updated.
- No image-bytes-on-bus regressions (AD-731 invariant preserved — the new helpers operate on `blob: bytes` already-resolved from `AttachmentStore`).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-15)

- `src/probos/cognitive/text_extractor.py:44` — `raise NotImplementedError("AD-720a-1: PDF extraction not yet wired")` confirmed.
- `src/probos/cognitive/text_extractor.py:14-19` — `_TEXT_PASSTHROUGH_MIMES` constant confirmed.
- `src/probos/config.py:1231` — `AttachmentsConfig` docstring already names `vision_tier`, `text_extraction_max_bytes`, `pdf_extraction_enabled` as the future field set; this AD lands the third.
- `src/probos/config.py:1266` — `vision_tier: str = "vision"` confirmed (AttachmentsConfig location anchor).
- `src/probos/routers/agents.py:1286-1495` — image-attachment branch confirmed; this AD's gate sits in a sibling branch for non-image MIMEs.
- No existing import of `pypdf`, `docx`, or `openpyxl` in `src/probos/` (zero risk of dep collision).
