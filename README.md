# PatentExtractor

PatentExtractor is a desktop tool for pulling chemical structures and associated details out of patent PDFs. It uses **OpenChemIE** to read figures and text, **RDKit** to validate and depict structures, and **PySide6** for the UI.

The look matches **MolManager**: Fusion style, Light / Dark / Groovy modes, named custom color schemes, and the same structure-column rendering.

---

## What it does

- Open a patent (or any chemistry) PDF
- Extract molecules from **figures** (MolScribe via OpenChemIE)
- Extract chemical **names / entities from text**
- Optionally resolve **figure–label coreferences** and parse **reactions**
- Show structures in a table with SMILES, identifiers, page, source, formula, MW, InChIKey
- Merge duplicate structures by InChIKey
- Export CSV, SDF, and SMILES

OpenChemIE models are large and slow on CPU. GPU (CUDA) is optional from the Extract panel.

---

## Install

Use **Python 3.10 or 3.11** (same as MolManager). OpenChemIE’s own docs mention 3.9; 3.10/3.11 usually work if PyTorch and Poppler are in place.

### 1. Install app dependencies

```powershell
cd PatentExtractor
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install --no-deps -r requirements.txt
python -m pip install -e ".[dev]"
```

On macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install --no-deps -r requirements.txt
python -m pip install -e ".[dev]"
```

The project keeps the full install list in `requirements.txt`, and the venv install uses `--no-deps` because OpenChemIE's upstream metadata still pins `torch<2.0` even though Python 3.10/3.11 wheels are only available for PyTorch 2.x.

Install [Poppler](https://github.com/jalan/pdftotext#os-dependencies) for your OS (needed by `pdf2image`) before running extraction.

The GUI still launches without OpenChemIE; Extract will explain what is missing.

**Python 3.11 note:** OpenChemIE declares `torch>=1.10,<2.0`, but that range does not match the available wheels for Python 3.11. The project workaround is to install the compatible torch version and skip dependency resolution for OpenChemIE during the single venv install. Do not re-create the `.venv` with a plain `pip install OpenChemIE` command.

### 3. Run

```powershell
python -m patentextractor
```

or `patentextractor` after an editable install.

---

## Usage

1. **File → Open PDF…** (or Open PDF on the left)
2. Choose sources: figures, text, coreferences, reactions
3. Optionally limit pages and pick CPU vs CUDA
4. Click **Extract** — first run downloads model weights
5. Inspect the Molecules / Reactions tabs and the detail pane
6. **File → Export** CSV, SDF, or SMILES

**Settings → GUI** is the same theme menu as MolManager (Light, Dark, Groovy, custom colors). Structure size and fonts are under Settings as well.

---

## Tests

```powershell
python -m pytest
```

The default suite skips model-backed integration tests and does not download model weights. To run the DDR2 end-to-end extraction test explicitly (the first run may download weights):

```powershell
python -m pytest --run-integration -m integration
```

The research PDF used by this test is not distributed with the repository. Place an authorized local copy at `samples/ddr2.pdf`, or set `PATENTEXTRACTOR_DDR2_SAMPLE` to its path; the test skips when no sample is available.

---

## License

GPLv3 or later. See `LICENSE`.

OpenChemIE is a separate project (Fan et al., *J. Chem. Inf. Model.* 2024). Cite it if you use the extractor in a paper.
