# PatentExtractor code audit

**Audit date:** 2026-10-09
**Scope:** Python application, UI, compatibility layer, tests, and project configuration.
**Purpose:** Track maintainability risks, correctness issues, remediation, and validation in the repository rather than only in chat.

## Summary

The project has useful boundaries between shared records, chemistry, extraction, UI, workers, export, and rendering. Names are generally descriptive. The main maintainability concern is concentration of responsibilities in `extraction.py`, `openchemie_compat.py`, `main_window.py`, and `ui/theme.py`, rather than consistently poor naming.

## Status legend

- **Open:** not yet addressed.
- **In progress:** implementation is in the worktree but has not yet been fully validated or committed.
- **Done:** addressed and validated.

## Priority findings

| Priority | Finding | Status | Recommended direction |
|---|---|---|---|
| High | Closing the main window while an extraction thread is active risks destroying a running `QThread`. Cancellation is cooperative and may wait for a model call to return. [Source](../patentextractor/ui/main_window.py) · [Worker](../patentextractor/workers/extract_worker.py) | Done | The window requests interruption, remains open until the worker thread finishes, and then closes; covered by a window test. |
| Medium | Cancellation was emitted as a generic worker failure and shown as a critical error. [Worker](../patentextractor/workers/extract_worker.py) · [UI](../patentextractor/ui/main_window.py) | Done | The worker has a dedicated cancellation signal and the UI reports a non-error cancelled state. |
| Medium | The molecule cap prevented independently selected coreference and reaction stages from running. [Source](../patentextractor/extraction.py) | Done | The cap now limits molecule records without suppressing selected coreference/reaction stages. |
| Medium | `parse_mol()` preserves unsanitized structures for review, while ranking treated every parseable structure as chemically valid. [Source](../patentextractor/chemistry.py) | Done | Display parsing remains permissive; ranking validity now requires RDKit sanitization. |
| Medium | Dependency availability checks imported `layoutparser`, `easyocr`, and `openchemie` before the compatibility setup preloaded the `pdftotext` shim. [Extraction check](../patentextractor/extraction.py) · [Compatibility setup](../patentextractor/openchemie_compat.py) | Done | Availability checks use `importlib.util.find_spec()` and do not import runtime packages. |
| Medium | Export I/O failures escaped GUI callbacks without an actionable message. [UI](../patentextractor/ui/main_window.py) · [Writers](../patentextractor/export.py) | Done | Export handling is centralized, errors include the destination and exception, and the remembered folder changes only after success. |
| Medium | Theme tests touched the user's persistent `QSettings`, and tests could leak shared palette/module state. [Fixtures](../tests/conftest.py) · [Theme tests](../tests/test_theme.py) · [Shim tests](../tests/test_openchemie_compat.py) | Done | Tests use a temporary QSettings path and restore palette/module state. |
| Medium | `MainWindow` owns widget construction, settings, extraction lifecycle, results, and export. [Source](../patentextractor/ui/main_window.py) | Open | Extract focused view/controller components incrementally; preserve public behavior. |
| Medium | `extraction.py` mixed vendor-result parsing, image conversion/cropping, PDF slicing, runtime setup, orchestration, molecule merging, and coreference linking. [Orchestration facade](../patentextractor/extraction.py) · [Result normalization](../patentextractor/extraction_results.py) · [Coreference linking](../patentextractor/extraction_coreference.py) · [PDF slicing](../patentextractor/extraction_pdf.py) · [Runtime setup](../patentextractor/extraction_runtime.py) | Done | Result normalization, coreference linking, PDF-window handling, and runtime setup are focused modules; `extraction.py` now coordinates the extraction pipeline and re-exports the existing compatibility API. |
| Medium | `openchemie_compat.py` combines shims, downloads, monkey patches, text parsing, and geometry/layout patches. [Source](../patentextractor/openchemie_compat.py) | Open | Divide compatibility concerns while retaining one small, documented preparation entry point. |
| Medium | Reaction payload parsing trusts nested values to have the expected shape; malformed vendor data can discard a stage's results. [Source](../patentextractor/extraction.py) | Done | Nested mappings/lists and page values are validated; malformed entries are logged and skipped individually. |
| Medium | Coreference pair parsing accepts negative indices and can abort on non-integer values. [Source](../patentextractor/extraction.py) | Done | Page, box, and pair inputs are validated; negative, fractional, non-integer, and out-of-range indices are skipped with warnings. |
| Medium | Merging kept only one page and could omit source entries when records already carried multiple sources; ranking used the retained page. | Done | Preserve sorted page numbers and all sources, keep `page` as the earliest-page compatibility field, rank by earliest page, and surface all pages in UI/exports. |
| Medium | `ExtractOptions` accepted invalid ranges when called outside the UI (for example negative page counts or molecule limits). | Done | Validate options at construction and before extraction; `first_page` starts at 1, page/cap zero means unlimited, batch size is positive, and crop margin is finite within the UI's 0–50% range. |
| Low | `structure_draw.py` says it is Qt-free but imports sizing from `structure_layout.py`, which loads `QSettings` at import time. | Open | Move pure rendering constants out of the Qt settings module or inject sizing at the UI boundary. |
| Low | The Windows DLL setup discards `os.add_dll_directory()` handles and suppresses all setup exceptions. | Open | Retain handles for process lifetime and log recoverable failures. |
| Low | OpenCV GUI and headless wheels are both direct dependencies. | Open | Select one distribution and keep dependency declarations aligned. |
| Low | Ruff has a 100-character setting but does not enable a line-length check; Pylance reports Qt override signature issues and dynamic compatibility typing noise. | Open | Enforce the intended line policy and address actionable typing findings without obscuring intentional runtime shims. |
| Low | A theme helper family appears unused; some short locals in vendor-adapter code are less descriptive than surrounding names. | Open | Confirm compatibility requirements, remove dead helpers if safe, and prefer names like `current_index`/`extracted_items`. |

## Work started

The following remediation is currently in the worktree and has not yet been committed:

- Added and validated a separate worker cancellation signal and deferred closing the main window until the worker thread finishes.
- Let selected coreference/reaction stages run even when the molecule cap has been reached.
- Made ranking validity require RDKit sanitization while preserving permissive parsing for review/rendering.
- Redirected `QSettings` to a temporary test location and restored test-mutated palette/module state.
- Strengthened invalid-valence, worker/window, capped-stage, and export-failure regression tests.
- Removed the five Ruff unused-import/unused-local findings.
- Changed OpenChemIE dependency discovery to use `importlib.util.find_spec()` instead of importing heavy modules before compatibility setup.
- Centralized GUI export handling and added failure reporting that does not update the remembered folder on failure.
- Hardened reaction/coreference parsing to validate nested vendor payloads and recover per entry.
- Moved OpenChemIE result normalization/cropping into `extraction_results.py`; `extraction.py` keeps compatibility exports for callers and tests.
- Moved bounding-box matching and coreference identifier attachment into `extraction_coreference.py`; `extraction.py` keeps the legacy private alias for compatibility.
- Moved PDF page-window slicing and page-number restoration into `extraction_pdf.py`; `extraction.py` retains the existing public slicing function and private shift alias.
- Moved device selection, dependency discovery, import diagnostics, and OpenChemIE construction into `extraction_runtime.py`; `extraction.py` retains compatibility re-exports.
- Moved runtime-focused tests into `tests/test_extraction_runtime.py` and added identity coverage for the compatibility re-exports.
- Added construction-time extraction-option validation and retained all merged molecule pages/sources through ranking, display, and export while preserving the legacy earliest `page` field.

This remediation is tracked as a separate audit-fix set from the earlier runtime-cache change.

The prior, pre-audit work was committed as `4d7483b` (`Cache and serialize OpenChemIE runtime`).

## Validation history

- Latest validation: default suite **77 passed, 1 skipped**; `ruff check patentextractor tests` passed.
- VS Code's file diagnostics reported no errors in the modified Python files.
- Six third-party deprecation/future warnings were emitted by installed dependencies during tests.
- The first broad audit test run happened before QSettings isolation was added and cleared the saved theme key. Future suite runs use a temporary settings directory; restore the desired theme in the app if the previous preference was not Light/default.
- Model-backed integration tests were not run; they depend on external model weights/system tools and are outside the deterministic default suite.

## Follow-up sequence

1. Assess `openchemie_compat.py` and UI decomposition in small steps, retaining compatibility entry points and regression tests.
2. Separate Qt settings from pure drawing/layout behavior; clean up dependency and type/lint policy.
3. Re-run default tests and Ruff after each coherent change; run integration tests only when local models and required system tools are available.
