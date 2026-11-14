# LitExtractor roadmap

## Now: table data linked to structures

LitExtractor's job is to pull structures out of a PDF together with the table data that goes
with them (activity, yield, properties), so both can be reviewed and exported. Tables come from
OpenChemIE's own table extraction, which reads the PDF's text layer.

1. **Look at real output** (done). Run OpenChemIE's table extraction on the sample PDFs to see how
   well rows and columns come through, since that decides how much correcting the UI must allow.
2. **Data model and matching** (done). Store each table as its own record (raw cell text, title, page,
   crop image, key column). Keep links between table rows and molecules as separate records with
   how they were matched (exact, OCR-tolerant or manual) and whether the user confirmed them.
   Labels are normalized before matching; a label matching several molecules is flagged as
   ambiguous, never resolved silently.
3. **Tables tab** (done). The table image beside its parsed grid, a link status per row,
   confirming, choosing and linking rows by hand, correcting cells, chosen table columns shown on
   the molecule table ("Table 3 · IC50 (nM)"), and a table-data card in the detail pane.
4. **Exports** (done). Wide (one row per molecule with the chosen columns), long (one row per molecule,
   table and column, with raw and parsed values) and each table on its own, including rows that
   matched no molecule.
5. **Later.** R-group tables (core plus R1/R2 columns into full structures); tables that list
   compounds by category (a column of names per class), which are left without a key today.
   Tables continuing across pages are joined already.

## Shelved: going beyond OpenChemIE

Paused in November 2026 so that the table work comes first. The work so far is on the local
branch `shelved/benchmark`; the drafted answer keys and the baseline run are in
`samples/benchmark/` (not in git).

**What exists.** A benchmark to measure accuracy on your own PDFs instead of judging by eye:

- `benchmark/run.py` runs the pipeline over chosen pages and `draft_key.py` turns a run into a
  draft answer key per document.
- `benchmark/review.py` serves a local page for a chemist to confirm, reject or fix each
  structure, redraw it in the JSME editor (double-click), add structures the pipeline missed,
  and mark pages complete.
- `benchmark/score.py` scores any runs on the reviewed pages: exact and skeleton recall and
  precision by InChIKey, label accuracy, and how well the low-confidence flag separates wrong
  readings from right ones.
- Keys are drafted for EGFR, FAK and JAK reviews and 11 pages of WO 2026/136733 (484 structures)
  but not yet reviewed, so there is no baseline score.

**Why it could be worth resuming.** OpenChemIE's models are good; most lost accuracy is in the
glue around them. Measured or found so far:

- Fixed already: figures from the 17th on were read against the wrong image; labels were
  matched across every figure on a page; padding molecule crops made readings worse.
- Pages are rendered at 200 dpi, so small structures fall below MolScribe's 384 px input.
- Labels were always OCR'd ("1a" read as "Ia"). Done ahead of the rest: figure labels now
  come from the text layer (OCR for picture figures), which also names journal structures by
  drug name so they can be matched to table rows.
- Table rows and columns are guessed from text positions, and scanned tables come back empty.
- Layout detection was trained on journal pages (PubLayNet), not patents.

**Plan when resumed,** in order, each step scored against the benchmark:

1. Review the answer keys and score the baseline.
2. Replace OpenChemIE's orchestration with our own staged pipeline calling the same models
   (render, layout, detect, recognise, labels, tables, join). This removes most monkeypatches and
   the pinned legacy dependencies that come with OpenChemIE's glue.
3. Figure regions rendered at higher resolution.
4. One table route for digital and scanned PDFs: a table-structure model (Docling TableFormer
   or Microsoft Table Transformer) for rows and columns, cell text from the text layer or OCR.
5. Cross-checks (two crop margins), then a second recogniser (DECIMER or MolGrapher) only if
   the benchmark shows structure errors dominate. Save user corrections as future training data.

Licence note for that work: PyMuPDF is AGPL; pypdfium2 and pdfplumber are permissive.

## Known issues

- `ExtractOptions.max_molecules` (Python API only; the app no longer offers a limit) is applied
  before merging and ranking, so the cap can drop better results.
- Chemical names found in text never become structures (no name-to-structure step such as OPSIN).
- Both `opencv-python` and `opencv-python-headless` are dependencies; only one should be.
- PyPDF2 is deprecated in favour of `pypdf`.
- No CI runs the test suite.
