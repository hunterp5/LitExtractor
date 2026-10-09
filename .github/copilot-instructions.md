# PatentExtractor Coding Rules

## Project description
PatentExtractor is a Python desktop application for extracting chemical structures and related data from patent and research PDFs. PySide6 provides the UI; OpenChemIE performs model-backed figure/text extraction; RDKit parses, validates, enriches, ranks, and depicts structures. Users can review molecules and reactions and export CSV, SDF, and SMILES. See `README.md` for setup and user workflows.

## Maintainable architecture
- Keep modules cohesive and functions focused. Do not turn `app.py`, `extraction.py`, or UI classes into catch-all modules; move new responsibilities into small, appropriately named modules.
- Preserve the existing boundaries: `extraction.py` orchestrates PDF/OpenChemIE work; `models.py` owns shared records/options; `chemistry.py` owns RDKit operations; `openchemie_compat.py` isolates upstream compatibility patches; `ui/` owns presentation; `workers/` runs long tasks off the UI thread; `export.py` owns file serialization.
- Keep dependencies flowing toward domain logic: domain modules must not import UI code, and extraction orchestration must not depend on UI. Avoid circular imports and import heavy model/runtime packages lazily so the GUI can start when optional extraction dependencies are unavailable.
- Prefer existing abstractions and the standard library over adding dependencies or frameworks for small tasks. Add caches only when profiling justifies them and the cache key/invalidation rules are explicit.
- Keep compatibility work narrow and reversible. Do not add process-wide monkeypatches or global behavior changes where a scoped adapter can preserve upstream behavior elsewhere.
- Keep user-configurable molecule-box expansion separate from the fixed parent-layout context margin; they apply at different crop stages. Molecule expansion defaults to 0%.

## General coding practices
- Support Python 3.10 and newer. Add type hints to public functions and non-obvious interfaces; use descriptive names and straightforward control flow.
- Preserve existing behavior, public imports, and defaults unless a change is intentional. When moving public symbols, retain compatibility re-exports and add regression coverage where appropriate.
- Validate inputs at boundaries and provide actionable errors. Catch exceptions only when recovery or a clearer user-facing message is possible; avoid silent failures and bare `except` blocks. Log recoverable failures with useful context.
- Use context managers for files and other resources. Keep model inference, PDF conversion, and expensive rendering out of the GUI thread; use the existing worker/signal pattern and preserve cancellation behavior.
- Do not hard-code machine-specific paths, credentials, or local model caches. Do not add local PDFs or model weights to Git. Keep dependency pins and framework constraints consistent across `requirements.txt` and `pyproject.toml`.
- Follow the configured Ruff rules and 100-character line limit. Update the README when setup, user-visible behavior, or test workflows change.
- Make incremental changes, inspect the diff, run relevant tests, and avoid unrelated cleanup in a feature or bug-fix change.

## PDF and test conventions
- Tests that require real patent content must use the shared `ddr2_sub_pdf` fixture, which resolves to the local `samples/ddr2_sub.pdf`. The file is intentionally not versioned; tests using it should skip clearly when it is unavailable. Do not substitute `samples/ddr2.pdf` or download a sample automatically.
- Keep small generated PDFs in tests that specifically verify PDF parsing, shim behavior, or page slicing; those tests need controlled page counts/content and are not real-document sample tests.
- Keep the default test suite deterministic and model-free. Mark tests requiring OpenChemIE models or external system services with `@pytest.mark.integration`; do not download model weights in ordinary unit tests.
- Use the existing offscreen `qapp` fixture for Qt tests. Do not require an interactive display.
- Validate changes with `python -m pytest -q` and `python -m ruff check` on changed Python files; do not introduce new diagnostics. Run model-backed tests explicitly with `python -m pytest --run-integration -m integration` when the local sample, cached weights, and required system tools are available.
