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

## Done after the table plan

Measured on full runs of the EGFR, FAK and JAK reviews (November 2026):

- Labels: activity values, conditions, captions, remarks and panel letters are no longer taken
  for compound labels (about half of FAK's labels were such text); merged coreference text is
  reduced to its compound number.
- Stray fragments from text read as atoms are removed (93 of 301 JAK structures had one), so
  copies of one drug now share an InChIKey skeleton and count as one match: JAK Table 1's
  ambiguous rows fell from 17 to 5.
- Table names spelt slightly differently from a structure's label link as "spelling differs".
- Names from Text had returned nothing (the name model's output format was misread); it now
  works, with OPSIN turning systematic names into structures. EGFR Table 3 links 13 of 14 rows
  (9 before).

- Values printed with structures in figures (activities, doses, pharmacokinetics) are kept on
  each structure and exported. A full FAK run gives 72 of 137 structures about 215 value lines;
  on pages 4-5, checked by eye, every value went to the right structure, including blocks
  printed beside a structure rather than below it. Reaction conditions under scheme structures
  are left out. Open: a bare number from a value line ("AUC ... 2757") can still be taken as
  a compound label.

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
- Trade and code names found in text ("Gefitinib", "AZD9291") stay names without a structure;
  OPSIN only reads systematic names. A PubChem lookup would cover them but sends the names to
  an outside service, so it would need to be opt-in.
- Both `opencv-python` and `opencv-python-headless` are dependencies; only one should be.
- PyPDF2 is deprecated in favour of `pypdf`.
- No CI runs the test suite.
