# LitExtractor Coding Rules

## Project description
LitExtractor is a Python desktop application for extracting chemical structures and related data from patent and research PDFs. PySide6 provides the UI; OpenChemIE performs model-backed figure/text extraction; RDKit parses, validates, enriches, ranks, and depicts structures. Data tables are read from the PDF's text layer and their rows linked to structures by label (`tables.py`, `text_labels.py`), reviewed in the Tables tab (`table_review.py`, `ui/tables_view.py`) and exported (`table_export.py`). Users can extract one PDF or a batch, review molecules, tables and reactions, and export CSV, SDF, SMILES and table data. `ROADMAP.md` lists planned and shelved work. See `README.md` for setup and user workflows.

## General coding practices
- Support Python 3.10 and newer. Add type hints to public functions and non-obvious interfaces; use descriptive names and straightforward control flow.
- Follow the configured Ruff rules and 100-character line limit. Update the README when setup, user-visible behavior, or test workflows change.
