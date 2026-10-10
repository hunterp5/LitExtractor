# PatentExtractor Coding Rules

## Project description
PatentExtractor is a Python desktop application for extracting chemical structures and related data from patent and research PDFs. PySide6 provides the UI; OpenChemIE performs model-backed figure/text extraction; RDKit parses, validates, enriches, ranks, and depicts structures. Users can review molecules and reactions and export CSV, SDF, and SMILES. See `README.md` for setup and user workflows.

## General coding practices
- Support Python 3.10 and newer. Add type hints to public functions and non-obvious interfaces; use descriptive names and straightforward control flow.
- Follow the configured Ruff rules and 100-character line limit. Update the README when setup, user-visible behavior, or test workflows change.

## PDF and test conventions
- Keep small generated PDFs in tests that specifically verify PDF parsing, shim behavior, or page slicing; those tests need controlled page counts/content and are not real-document sample tests.
- Keep the default test suite deterministic and model-free. Mark tests requiring OpenChemIE models or external system services with `@pytest.mark.integration`; do not download model weights in ordinary unit tests.
- Use the existing offscreen `qapp` fixture for Qt tests. Do not require an interactive display.
- Validate changes with `python -m pytest -q` and `python -m ruff check` on changed Python files; do not introduce new diagnostics. Run model-backed tests explicitly with `python -m pytest --run-integration -m integration` when the local sample, cached weights, and required system tools are available.
