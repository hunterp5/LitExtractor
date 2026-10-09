# PatentExtractor Coding Rules

## Project description
PatentExtractor is a Python desktop application for extracting chemical structures and related data from patent and research PDFs. PySide6 provides the UI; OpenChemIE performs model-backed figure/text extraction; RDKit parses, validates, enriches, ranks, and depicts structures. Users can review molecules and reactions and export CSV, SDF, and SMILES. See `README.md` for setup and user workflows.

## General coding practices
- Support Python 3.10 and newer. Add type hints to public functions and non-obvious interfaces; use descriptive names and straightforward control flow.
- Preserve existing behavior, public imports, and defaults unless a change is intentional. When moving public symbols, retain compatibility re-exports and add regression coverage where appropriate.
- Validate inputs at boundaries and provide actionable errors. Catch exceptions only when recovery or a clearer user-facing message is possible; avoid silent failures and bare `except` blocks. Log recoverable failures with useful context.
- Use context managers for files and other resources. Keep model inference, PDF conversion, and expensive rendering out of the GUI thread; use the existing worker/signal pattern and preserve cancellation behavior.
- Do not hard-code machine-specific paths, credentials, or local model caches. Do not add local PDFs or model weights to Git. Keep dependency pins and framework constraints consistent across `requirements.txt` and `pyproject.toml`.
- Follow the configured Ruff rules and 100-character line limit. Update the README when setup, user-visible behavior, or test workflows change.
- Make incremental changes, inspect the diff, run relevant tests, and avoid unrelated cleanup in a feature or bug-fix change.

## PDF and test conventions
- Keep small generated PDFs in tests that specifically verify PDF parsing, shim behavior, or page slicing; those tests need controlled page counts/content and are not real-document sample tests.
- Keep the default test suite deterministic and model-free. Mark tests requiring OpenChemIE models or external system services with `@pytest.mark.integration`; do not download model weights in ordinary unit tests.
- Use the existing offscreen `qapp` fixture for Qt tests. Do not require an interactive display.
- Validate changes with `python -m pytest -q` and `python -m ruff check` on changed Python files; do not introduce new diagnostics. Run model-backed tests explicitly with `python -m pytest --run-integration -m integration` when the local sample, cached weights, and required system tools are available.
