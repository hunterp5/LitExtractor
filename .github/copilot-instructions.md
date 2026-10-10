# LitExtractor Coding Rules

## Project description
LitExtractor is a Python desktop application for extracting chemical structures and related data from patent and research PDFs. PySide6 provides the UI; OpenChemIE performs model-backed figure/text extraction; RDKit parses, validates, enriches, ranks, and depicts structures. Users can review molecules and reactions and export CSV, SDF, and SMILES. See `README.md` for setup and user workflows.

## General coding practices
- Support Python 3.10 and newer. Add type hints to public functions and non-obvious interfaces; use descriptive names and straightforward control flow.
- Follow the configured Ruff rules and 100-character line limit. Update the README when setup, user-visible behavior, or test workflows change.
