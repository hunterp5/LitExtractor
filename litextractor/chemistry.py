# This file is part of LitExtractor.
# Copyright (C) 2026 Hunter Picard
#
# LitExtractor is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# LitExtractor is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with LitExtractor.  If not, see <https://www.gnu.org/licenses/>.

"""RDKit parsing, enrichment, validation, and ranking for molecule records."""

from __future__ import annotations

import logging

from rdkit import Chem, RDLogger
from rdkit.Chem import Descriptors, rdMolDescriptors

from .models import ExtractedMolecule

logger = logging.getLogger(__name__)

# Malformed OCR'd structures are expected; RDKit's own warnings would only spam the console.
RDLogger.DisableLog("rdApp.*")


def parse_mol(*, smiles: str = "", molfile: str = "") -> Chem.Mol | None:
    """Parse a molecule from molfile first, then SMILES."""
    molfile = (molfile or "").strip()
    if molfile:
        mol = Chem.MolFromMolBlock(molfile, sanitize=False)
        if mol is not None:
            try:
                Chem.SanitizeMol(mol)
            except Exception:
                try:
                    mol.UpdatePropertyCache(strict=False)
                    Chem.GetSSSR(mol)
                except Exception:
                    logger.debug("Molfile sanitization failed", exc_info=True)
            return mol
    smiles = (smiles or "").strip()
    if not smiles:
        return None
    mol = Chem.MolFromSmiles(smiles)
    if mol is not None:
        return mol
    mol = Chem.MolFromSmiles(smiles, sanitize=False)
    if mol is None:
        return None
    try:
        mol.UpdatePropertyCache(strict=False)
        Chem.GetSSSR(mol)
    except Exception:
        logger.debug("SMILES sanitization failed", exc_info=True)
    return mol


def enrich_molecule(mol_rec: ExtractedMolecule) -> ExtractedMolecule:
    """Fill formula, MW, InChIKey, and canonical SMILES/molfile from RDKit."""
    mol = parse_mol(smiles=mol_rec.smiles, molfile=mol_rec.molfile)
    if mol is None:
        return mol_rec
    try:
        mol_rec.smiles = Chem.MolToSmiles(mol) or mol_rec.smiles
    except Exception:
        logger.debug("Canonical SMILES failed", exc_info=True)
    if not mol_rec.molfile:
        try:
            mol_rec.molfile = Chem.MolToMolBlock(mol) or ""
        except Exception:
            logger.debug("Molblock write failed", exc_info=True)
    try:
        mol_rec.formula = rdMolDescriptors.CalcMolFormula(mol)
    except Exception:
        logger.debug("Formula failed", exc_info=True)
    try:
        mol_rec.molecular_weight = round(float(Descriptors.MolWt(mol)), 3)
    except Exception:
        logger.debug("MolWt failed", exc_info=True)
    try:
        mol_rec.inchi_key = Chem.MolToInchiKey(mol) or ""
    except Exception:
        logger.debug("InChIKey failed", exc_info=True)
    return mol_rec


def _molecule_is_valid(rec: ExtractedMolecule) -> bool:
    """True when at least one structure representation passes RDKit sanitization."""
    if not rec.smiles and not rec.molfile:
        return False
    mol = parse_mol(smiles=rec.smiles, molfile=rec.molfile)
    if mol is None:
        return False
    try:
        Chem.SanitizeMol(Chem.Mol(mol))
        return True
    except Exception:
        logger.debug("Parsed molecule did not pass sanitization", exc_info=True)

    # parse_mol prefers a parseable molfile, including unsanitized blocks. If that
    # block is invalid but the SMILES is valid, still recognize the valid representation.
    if rec.smiles:
        try:
            return Chem.MolFromSmiles(rec.smiles) is not None
        except Exception:
            logger.debug("SMILES validation failed", exc_info=True)
    return False


def molecule_quality_score(rec: ExtractedMolecule) -> float:
    """Return a derived quality score that separates valid, well-annotated hits from weak candidates."""
    valid = _molecule_is_valid(rec)
    return _quality_score_for_validity(rec, valid)


def _quality_score_for_validity(rec: ExtractedMolecule, valid: bool) -> float:
    """Compute the quality score using a validity result already obtained by the caller."""
    raw = float(rec.score) if rec.score is not None else 0.0
    quality = 0.5 * float(valid) + 0.3 * max(0.0, min(1.0, raw))
    if rec.formula:
        quality += 0.08
    if rec.molecular_weight is not None:
        quality += 0.05
    if rec.molfile:
        quality += 0.05
    if rec.identifier:
        quality += 0.04
    if rec.source == "text":
        quality += 0.03
    return min(1.0, max(0.0, quality))


def prioritize_molecules(molecules: list[ExtractedMolecule]) -> list[ExtractedMolecule]:
    """Rank valid, better-annotated molecules ahead of weaker candidates."""
    ranked: list[tuple[tuple[int, float, int, str], ExtractedMolecule]] = []
    for rec in molecules:
        valid = _molecule_is_valid(rec)
        key = (
            0 if valid else 1,
            -_quality_score_for_validity(rec, valid),
            rec.page_numbers[0] if rec.page_numbers else 1_000_000,
            str(rec.smiles or rec.molfile or rec.identifier or ""),
        )
        ranked.append((key, rec))
    ranked.sort(key=lambda item: item[0])
    return [rec for _, rec in ranked]
