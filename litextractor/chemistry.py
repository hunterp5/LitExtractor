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
    """Parse a molecule from molfile first, then SMILES.

    Parsing is lenient: if sanitization fails, a partially initialized molecule is returned
    so the structure can still be depicted. Returns ``None`` when neither input parses.
    """
    molfile = (molfile or "").strip()
    if molfile:
        rdkit_mol = Chem.MolFromMolBlock(molfile, sanitize=False)
        if rdkit_mol is not None:
            try:
                Chem.SanitizeMol(rdkit_mol)
            except Exception:
                try:
                    rdkit_mol.UpdatePropertyCache(strict=False)
                    Chem.GetSSSR(rdkit_mol)
                except Exception:
                    logger.debug("Molfile sanitization failed", exc_info=True)
            return rdkit_mol
    smiles = (smiles or "").strip()
    if not smiles:
        return None
    rdkit_mol = Chem.MolFromSmiles(smiles)
    if rdkit_mol is not None:
        return rdkit_mol
    rdkit_mol = Chem.MolFromSmiles(smiles, sanitize=False)
    if rdkit_mol is None:
        return None
    try:
        rdkit_mol.UpdatePropertyCache(strict=False)
        Chem.GetSSSR(rdkit_mol)
    except Exception:
        logger.debug("SMILES sanitization failed", exc_info=True)
    return rdkit_mol


def enrich_molecule(molecule_record: ExtractedMolecule) -> ExtractedMolecule:
    """Fill formula, MW, InChIKey, and canonical SMILES/molfile from RDKit.

    The record is updated in place and returned; it is returned unchanged if it cannot be parsed.
    """
    rdkit_mol = parse_mol(smiles=molecule_record.smiles, molfile=molecule_record.molfile)
    if rdkit_mol is None:
        return molecule_record
    try:
        molecule_record.smiles = Chem.MolToSmiles(rdkit_mol) or molecule_record.smiles
    except Exception:
        logger.debug("Canonical SMILES failed", exc_info=True)
    if not molecule_record.molfile:
        try:
            molecule_record.molfile = Chem.MolToMolBlock(rdkit_mol) or ""
        except Exception:
            logger.debug("Molblock write failed", exc_info=True)
    try:
        molecule_record.formula = rdMolDescriptors.CalcMolFormula(rdkit_mol)
    except Exception:
        logger.debug("Formula failed", exc_info=True)
    try:
        molecule_record.molecular_weight = round(float(Descriptors.MolWt(rdkit_mol)), 3)
    except Exception:
        logger.debug("MolWt failed", exc_info=True)
    try:
        molecule_record.inchi_key = Chem.MolToInchiKey(rdkit_mol) or ""
    except Exception:
        logger.debug("InChIKey failed", exc_info=True)
    return molecule_record


def _molecule_is_valid(molecule: ExtractedMolecule) -> bool:
    """True when at least one structure representation passes RDKit sanitization."""
    if not molecule.smiles and not molecule.molfile:
        return False
    rdkit_mol = parse_mol(smiles=molecule.smiles, molfile=molecule.molfile)
    if rdkit_mol is None:
        return False
    try:
        Chem.SanitizeMol(Chem.Mol(rdkit_mol))
        return True
    except Exception:
        logger.debug("Parsed molecule did not pass sanitization", exc_info=True)

    # parse_mol prefers a parseable molfile, including unsanitized blocks. If that
    # block is invalid but the SMILES is valid, still recognize the valid representation.
    if molecule.smiles:
        try:
            return Chem.MolFromSmiles(molecule.smiles) is not None
        except Exception:
            logger.debug("SMILES validation failed", exc_info=True)
    return False


def molecule_quality_score(molecule: ExtractedMolecule) -> float:
    """Return a quality score separating valid, well-annotated hits from weak candidates."""
    valid = _molecule_is_valid(molecule)
    return _quality_score_for_validity(molecule, valid)


def _quality_score_for_validity(molecule: ExtractedMolecule, valid: bool) -> float:
    """Compute the quality score using a validity result already obtained by the caller."""
    raw_score = float(molecule.score) if molecule.score is not None else 0.0
    quality = 0.5 * float(valid) + 0.3 * max(0.0, min(1.0, raw_score))
    if molecule.formula:
        quality += 0.08
    if molecule.molecular_weight is not None:
        quality += 0.05
    if molecule.molfile:
        quality += 0.05
    if molecule.identifier:
        quality += 0.04
    if molecule.source == "text":
        quality += 0.03
    return min(1.0, max(0.0, quality))


def prioritize_molecules(molecules: list[ExtractedMolecule]) -> list[ExtractedMolecule]:
    """Rank valid, better-annotated molecules ahead of weaker candidates.

    Ordering is by validity, then descending quality, then earliest page, then SMILES/molfile text.
    """
    ranked: list[tuple[tuple[int, float, int, str], ExtractedMolecule]] = []
    for molecule in molecules:
        valid = _molecule_is_valid(molecule)
        sort_key = (
            0 if valid else 1,
            -_quality_score_for_validity(molecule, valid),
            molecule.page_numbers[0] if molecule.page_numbers else 1_000_000,
            str(molecule.smiles or molecule.molfile or molecule.identifier or ""),
        )
        ranked.append((sort_key, molecule))
    ranked.sort(key=lambda item: item[0])
    return [molecule for _, molecule in ranked]
