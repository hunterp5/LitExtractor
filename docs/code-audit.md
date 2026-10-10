# LitExtractor code audit

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
| High | Closing the main window while an extraction thread is active risks destroying a running `QThread`. Cancellation is cooperative and may wait for a model call to return. [Source](../litextractor/ui/main_window.py) · [Worker](../litextractor/workers/extract_worker.py) | Done | The window requests interruption, remains open until the worker thread finishes, and then closes; covered by a window test. |
| Medium | Cancellation was emitted as a generic worker failure and shown as a critical error. [Worker](../litextractor/workers/extract_worker.py) · [UI](../litextractor/ui/main_window.py) | Done | The worker has a dedicated cancellation signal and the UI reports a non-error cancelled state. |
| High | Cancelling stayed on "Cancel requested" for a long time: `should_cancel` was only polled between extraction stages, and each OpenChemIE stage is one blocking call over the whole PDF. [Hook](../litextractor/cancellation.py) · [Stage wiring](../litextractor/extraction.py) · [Checkpoint loads](../litextractor/compat_checkpoint.py) · [MolScribe and pdfminer patches](../litextractor/compat_figures.py) | Done | A torch forward pre-hook raises `ExtractionCancelled` before the next layer, scoped to the extraction thread and removed afterwards. Lazy checkpoint loads, each pdfminer page parse, and the MolScribe conversion loop are also cancellation points. MolScribe's per-call 16-process pool (uninterruptible and mostly single-worker) is replaced by an in-process loop. `ExtractionCancelled` now derives from `BaseException` so third-party `except Exception` fallbacks cannot swallow it. Measured on the sample PDF with real models over 18 cancels at different pipeline stages: average 0.37 s, worst 1.3 s (a checkpoint load or page parse already in flight), versus up to 6 s before. |
| Medium | The molecule cap prevented independently selected coreference and reaction stages from running. [Source](../litextractor/extraction.py) | Done | The cap now limits molecule records without suppressing selected coreference/reaction stages. |
| Medium | `parse_mol()` preserves unsanitized structures for review, while ranking treated every parseable structure as chemically valid. [Source](../litextractor/chemistry.py) | Done | Display parsing remains permissive; ranking validity now requires RDKit sanitization. |
| Medium | Dependency availability checks imported `layoutparser`, `easyocr`, and `openchemie` before the compatibility setup preloaded the `pdftotext` shim. [Extraction check](../litextractor/extraction.py) · [Compatibility setup](../litextractor/openchemie_compat.py) | Done | Availability checks use `importlib.util.find_spec()` and do not import runtime packages. |
| Medium | Export I/O failures escaped GUI callbacks without an actionable message. [UI](../litextractor/ui/main_window.py) · [Writers](../litextractor/export.py) | Done | Export handling is centralized, errors include the destination and exception, and the remembered folder changes only after success. |
| Medium | Theme tests touched the user's persistent `QSettings`, and tests could leak shared palette/module state. [Fixtures](../tests/conftest.py) · [Theme tests](../tests/test_theme.py) · [Shim tests](../tests/test_openchemie_compat.py) | Done | Tests use a temporary QSettings path and restore palette/module state. |
| Medium | `MainWindow` owns widget construction, settings, extraction lifecycle, results, and export. [Source](../litextractor/ui/main_window.py) · [Extraction controller](../litextractor/ui/extraction_controller.py) · [Result-tabs controller](../litextractor/ui/result_tabs_controller.py) · [Detail presenter](../litextractor/ui/detail_panel_presenter.py) | Done | The extraction lifecycle, result-tab lifecycle, and detail-pane rendering are now delegated to focused UI components while preserving the existing window behavior and public interactions. |
| Medium | A completed extraction replaced the prior visible tables, making it difficult to compare multiple runs in one session. | Done | Each run is retained in its own result tab, right-click deletion requires confirmation, and exports use the active result tab. The molecule/reaction pair is owned by [ExtractionResultTab](../litextractor/ui/extraction_result_tab.py). |
| Medium | `extraction.py` mixed vendor-result parsing, image conversion/cropping, PDF slicing, runtime setup, orchestration, molecule merging, and coreference linking. [Orchestration facade](../litextractor/extraction.py) · [Result normalization](../litextractor/extraction_results.py) · [Coreference linking](../litextractor/extraction_coreference.py) · [PDF slicing](../litextractor/extraction_pdf.py) · [Runtime setup](../litextractor/extraction_runtime.py) | Done | Result normalization, coreference linking, PDF-window handling, and runtime setup are focused modules; `extraction.py` now coordinates the extraction pipeline and re-exports the existing compatibility API. |
| Medium | `openchemie_compat.py` combines shims, downloads, monkey patches, text parsing, and geometry/layout patches. [Compatibility facade](../litextractor/openchemie_compat.py) · [Checkpoint gates](../litextractor/compat_checkpoint.py) · [PDF text fallbacks](../litextractor/compat_pdf_text.py) · [Figure patches](../litextractor/compat_figures.py) · [HTTP weights](../litextractor/http_weights.py) | Done | Each concern lives in a focused module. `openchemie_compat.py` is now a thin facade that re-exports every prior name and keeps `prepare_openchemie_imports()` with its original patch order, which a test pins. |
| Medium | Reaction payload parsing trusts nested values to have the expected shape; malformed vendor data can discard a stage's results. [Source](../litextractor/extraction.py) | Done | Nested mappings/lists and page values are validated; malformed entries are logged and skipped individually. |
| Medium | Coreference pair parsing accepts negative indices and can abort on non-integer values. [Source](../litextractor/extraction.py) | Done | Page, box, and pair inputs are validated; negative, fractional, non-integer, and out-of-range indices are skipped with warnings. |
| Medium | Merging kept only one page and could omit source entries when records already carried multiple sources; ranking used the retained page. | Done | Preserve sorted page numbers and all sources, keep `page` as the earliest-page compatibility field, rank by earliest page, and surface all pages in UI/exports. |
| Medium | `ExtractOptions` accepted invalid ranges when called outside the UI (for example negative page counts or molecule limits). | Done | Validate options at construction and before extraction; `first_page` starts at 1, page/cap zero means unlimited, batch size is positive, and crop margin is finite within the UI's 0–50% range. |
| Low | `structure_draw.py` says it is Qt-free but imports sizing from `structure_layout.py`, which loads `QSettings` at import time. [Source](../litextractor/structure_draw.py) · [Dimensions](../litextractor/structure_dimensions.py) | Done | Shared dimensions and runtime size state now live in a pure module; `structure_layout.py` retains the Qt settings facade and `structure_draw.py` imports no Qt modules. Covered by subprocess import-isolation and dynamic sizing tests. |
| Low | The Windows DLL setup discards `os.add_dll_directory()` handles and suppresses all setup exceptions. [Source](../litextractor/bootstrap.py) | Done | Retain registered handles for process lifetime, log a failure per directory, and continue setup for remaining Qt DLL locations; covered by Windows-path-mocked tests. |
| Low | OpenCV GUI and headless wheels are both direct dependencies. | Open | Select one distribution and keep dependency declarations aligned. |
| Low | Ruff has a 100-character setting but does not enable a line-length check; Pylance reports Qt override signature issues and dynamic compatibility typing noise. | Open | Enforce the intended line policy and address actionable typing findings without obscuring intentional runtime shims. |
| Low | Theme configuration had unused helper families, random Groovy palettes, custom-theme persistence, and local reset workarounds. [Source](../litextractor/ui/theme.py) | Done | The app now has exactly three themes, deterministic Light/Dark palettes, a randomized multi-hue Groovy palette, persisted startup selection, and app-wide palette propagation; obsolete custom-theme code and unused helpers were removed. |

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
- Enabled figure–label coreferences by default and kept each successful extraction in a separate result tab with confirmed deletion and active-tab-only exports.
- Extracted LayoutParser weight metadata, URL conversion, HTML detection, robust downloads, and iopath cache patching into `http_weights.py`; `openchemie_compat.py` re-exports the prior helper names and remains the setup entry point. Added a regression test for those compatibility aliases.
- Split `MainWindow` responsibilities into focused UI components: extraction lifecycle (`extraction_controller.py`), result-tab lifecycle (`result_tabs_controller.py`), and detail-pane rendering (`detail_panel_presenter.py`), with `MainWindow` retaining composition and menu wiring.
- Split `openchemie_compat.py` into `compat_checkpoint.py`, `compat_pdf_text.py`, and `compat_figures.py`; the original module remains the stable facade and entry point. Added tests for facade identity and patch order.

This remediation is tracked as a separate audit-fix set from the earlier runtime-cache change.

The prior, pre-audit work was committed as `4d7483b` (`Cache and serialize OpenChemIE runtime`).

## Validation history

- Cancellation validation (2026-10-10): `ruff check litextractor tests` passed; full default suite **120 passed, 1 skipped**. Real-model check on `samples/ddr2_sub.pdf` (CPU): 18 cancels spread across the figure, text, and coreference stages averaged 0.37 s and peaked at 1.3 s, with no crashes or spurious "stage failed" warnings. The one-page full run still takes about 30 s warm; the MolScribe pool replacement did not change the molecule count (12).

- Compatibility-layer split validation (2026-10-10): `ruff check litextractor tests` passed; full default suite **110 passed, 1 skipped** (venv). The startup-import test caught Phase 1 regressions where the new UI controllers eagerly imported RDKit; those imports are lazy again, so `MainWindow` startup still loads neither RDKit nor torch.

- UI-controller decomposition validation (2026-10-10): `ruff check litextractor tests` passed; targeted GUI regressions (`test_main_window_smoke.py`, `test_molecule_table.py`, `test_export.py`, `test_settings.py`, `test_theme.py`) **33 passed**; extraction/runtime regressions (`test_extraction_runtime.py`, `test_extraction.py`, `test_model_runtime.py`) **52 passed, 1 skipped**.
- LitExtractor namespace rename validation (2026-10-10): default suite **108 passed, 1 skipped**; `ruff check litextractor tests` passed. The editable distribution and `litextractor` console entry point were verified.
- VS Code's file diagnostics reported no errors in the modified Python files.
- Six third-party deprecation/future warnings were emitted by installed dependencies during tests.
- The first broad audit test run happened before QSettings isolation was added and cleared the saved theme key. Future suite runs use a temporary settings directory; restore the desired theme in the app if the previous preference was not Light/default.
- Model-backed integration tests were not run; they depend on external model weights/system tools and are outside the deterministic default suite.

## Follow-up sequence

1. Phase 3 (performance): shared structure-render cache, bounded result retention, and per-stage timing.
2. Phase 4: resolve the duplicate OpenCV wheel declaration and add an environment health check.
2. Separate Qt settings from pure drawing/layout behavior; clean up dependency and type/lint policy.
3. Re-run default tests and Ruff after each coherent change; run integration tests only when local models and required system tools are available.
