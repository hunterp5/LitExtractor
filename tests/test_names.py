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

"""Systematic names in the text turned into structures with OPSIN."""

from __future__ import annotations

import subprocess

import pytest

from litextractor import names
from litextractor.extraction import extract_from_pdf
from litextractor.models import ExtractedMolecule, ExtractOptions

GEFITINIB_NAME = "N-(3-chloro-4-fluorophenyl)-7-methoxy-6-(3-morpholin-4-ylpropoxy)quinazolin-4-amine"
GEFITINIB_SMILES = "COc1cc2ncnc(Nc3ccc(F)c(Cl)c3)c2cc1OCCCN1CCOCC1"


@pytest.mark.parametrize(
    ("text", "expected"),
    [(GEFITINIB_NAME, True), ("2,2,2-trifluoroacetic acid", True), ("ethanol", True),
     ("EGFR", False), ("HCl", False), ("the compound was stirred for 2 h at room temperature",
                                          False)],
)
def test_only_name_like_text_is_sent_to_opsin(text, expected):
    assert names.looks_like_systematic_name(text) is expected


@pytest.fixture
def fake_opsin(monkeypatch):
    """OPSIN that knows two names and records what it was sent."""
    known = {GEFITINIB_NAME: GEFITINIB_SMILES, "ethanol": "CCO"}
    calls = []

    def run(command, *, input, **kwargs):
        del kwargs
        calls.append((command, input))
        out = "".join(known.get(line, "") + "\n" for line in input.splitlines())
        return subprocess.CompletedProcess(command, 0, stdout=out, stderr="")

    monkeypatch.setattr(names, "find_java", lambda: "/jdk/bin/java")
    monkeypatch.setattr(names, "opsin_jar", lambda: "/site/opsin.jar")
    monkeypatch.setattr(names.subprocess, "run", run)
    return calls


def test_names_are_converted_in_one_opsin_run_and_unknown_names_left_out(fake_opsin):
    found = names.names_to_smiles(["ethanol", "Gefitinib", "ethanol", "  ethanol "])

    assert found == {"ethanol": "CCO"}
    ((command, sent),) = fake_opsin
    assert command == ["/jdk/bin/java", "-jar", "/site/opsin.jar", "-osmi"]
    assert sent == "ethanol\nGefitinib\n"


def test_text_molecules_without_a_structure_get_one(fake_opsin):
    named = ExtractedMolecule(smiles="", source="text", identifier=GEFITINIB_NAME)
    trade_name = ExtractedMolecule(smiles="", source="text", identifier="Gefitinib")
    drawn = ExtractedMolecule(smiles="CCN", source="figure", identifier="ethanol")

    assert names.structures_from_names([named, trade_name, drawn]) == 1

    assert named.source == names.NAME_SOURCE and named.inchi_key and named.formula == "C22H24ClFN4O3"
    assert trade_name.smiles == "" and drawn.smiles == "CCN"
    assert len(fake_opsin) == 1


def test_missing_java_is_explained(monkeypatch):
    monkeypatch.setattr(names, "opsin_jar", lambda: "/site/opsin.jar")
    monkeypatch.setattr(names, "find_java", lambda: None)

    with pytest.raises(RuntimeError, match="Java was not found"):
        names.names_to_smiles(["ethanol"])


def test_the_macos_java_stub_is_not_taken_for_java(monkeypatch, tmp_path):
    stub = tmp_path / "java"
    stub.write_text("#!/bin/sh\necho 'Unable to locate a Java Runtime.' >&2\nexit 1\n")
    stub.chmod(0o755)
    names.find_java.cache_clear()
    monkeypatch.setattr(names, "_java_candidates", lambda: [stub])
    try:
        assert names.find_java() is None
    finally:
        names.find_java.cache_clear()


class NamingClient:
    """Fake OpenChemIE whose text mentions gefitinib by its systematic and trade names."""

    def extract_molecules_from_text_in_pdf(self, pdf, **kwargs):
        del pdf, kwargs
        text = f"{GEFITINIB_NAME} (Gefitinib) inhibits EGFR."
        spans = [(GEFITINIB_NAME, "MOL"), ("Gefitinib", "MOL")]
        labels = [(kind, text.index(name), text.index(name) + len(name)) for name, kind in spans]
        return [{"page": 1, "molecules": [{"text": text, "labels": labels}]}]


def test_extraction_converts_names_unless_turned_off(fake_opsin):
    options = dict(figures=False, corefs=False, tables=False, merge_by_inchi=False)

    converted = extract_from_pdf("d.pdf", ExtractOptions(**options), client=NamingClient())
    kept = extract_from_pdf("d.pdf", ExtractOptions(**options, names_to_structures=False),
                            client=NamingClient())

    assert {(m.identifier, m.source) for m in converted.molecules if m.smiles} == {
        (GEFITINIB_NAME, names.NAME_SOURCE)}
    assert all(not m.smiles for m in kept.molecules) and len(fake_opsin) == 1


def test_opsin_failure_becomes_a_warning_and_keeps_the_names(monkeypatch):
    monkeypatch.setattr(names, "opsin_jar", lambda: None)

    result = extract_from_pdf(
        "d.pdf", ExtractOptions(figures=False, corefs=False, tables=False), client=NamingClient()
    )

    assert len(result.molecules) == 2
    assert result.warnings == [
        "Name-to-structure failed: Names cannot be converted to structures: the py2opsin "
        "package (OPSIN) is not installed."
    ]


@pytest.mark.integration
def test_real_opsin_converts_a_systematic_name():
    from litextractor.chemistry import parse_mol
    from rdkit import Chem

    smiles = names.names_to_smiles([GEFITINIB_NAME])[GEFITINIB_NAME]
    assert Chem.MolToSmiles(parse_mol(smiles=smiles)) == Chem.MolToSmiles(
        parse_mol(smiles=GEFITINIB_SMILES))
