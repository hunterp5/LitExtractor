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

"""Turn systematic chemical names found in text into structures with OPSIN.

OPSIN (MIT licensed, bundled as a jar by the ``py2opsin`` package) reads IUPAC and other
systematic names ("N-(3-chloro-4-fluorophenyl)-7-methoxy-6-(3-morpholin-4-ylpropoxy)quinazolin-
4-amine") offline. It does not know trade or code names ("Gefitinib", "AZD9291"); those stay
names without a structure. OPSIN runs on Java, which is looked for where it is often installed
but not on PATH (the conda environment's ``lib/jvm``, ``JAVA_HOME``, Homebrew). All names of a
run are converted by one Java process, since starting Java takes seconds.
"""

from __future__ import annotations

import functools
import importlib.util
import logging
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

from .models import ExtractedMolecule

logger = logging.getLogger(__name__)

_JAR_NAME = re.compile(r"opsin.*\.jar$", re.IGNORECASE)
_SECONDS_PER_NAME = 0.05
_MIN_TIMEOUT = 60.0
# Worth sending to OPSIN: long enough, has letters, no sentence punctuation or spaces between
# words (systematic names are one token, apart from salts and acids like "acetic acid").
# Three lowercase letters in a row: systematic names have them, abbreviations ("EGFR") do not.
_NAME_LIKE = re.compile(r"^(?=.*[a-z]{3})[\w\-(),\[\]{}'′.+ ]{4,300}$")


def _java_candidates() -> list[Path]:
    prefixes = [sys.prefix, sys.base_prefix, os.environ.get("CONDA_PREFIX", "")]
    candidates: list[Path] = []
    if os.environ.get("JAVA_HOME"):
        candidates.append(Path(os.environ["JAVA_HOME"]) / "bin" / "java")
    for prefix in filter(None, prefixes):
        candidates += [Path(prefix) / "lib" / "jvm" / "bin" / "java", Path(prefix) / "bin" / "java",
                       Path(prefix) / "Library" / "bin" / "java.exe"]
    candidates += [Path("/opt/homebrew/opt/openjdk/bin/java"),
                   Path("/usr/local/opt/openjdk/bin/java")]
    on_path = shutil.which("java")
    if on_path:
        candidates.append(Path(on_path))
    return candidates


def _runs(java: Path) -> bool:
    """True when *java* starts (macOS's /usr/bin/java exists even without a Java runtime)."""
    try:
        completed = subprocess.run([str(java), "-version"], capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


@functools.lru_cache(maxsize=1)
def find_java() -> str | None:
    """Return a working ``java`` executable, or None."""
    seen: set[Path] = set()
    for candidate in _java_candidates():
        if candidate in seen or not candidate.is_file():
            continue
        seen.add(candidate)
        if _runs(candidate):
            return str(candidate)
    return None


@functools.lru_cache(maxsize=1)
def opsin_jar() -> str | None:
    """Return the OPSIN jar bundled with ``py2opsin``, or None if it is not installed.

    The package is located without importing it, since importing runs a Java check.
    """
    spec = importlib.util.find_spec("py2opsin")
    if spec is None or not spec.submodule_search_locations:
        return None
    for folder in spec.submodule_search_locations:
        for path in sorted(Path(folder).iterdir()):
            if _JAR_NAME.search(path.name):
                return str(path)
    return None


def unavailable_reason() -> str | None:
    """Why names cannot be converted, or None when OPSIN can run."""
    if opsin_jar() is None:
        return "the py2opsin package (OPSIN) is not installed"
    if find_java() is None:
        return "Java was not found (install it with 'conda install -c conda-forge openjdk')"
    return None


def looks_like_systematic_name(text: str) -> bool:
    """True for text worth sending to OPSIN (not a short abbreviation or a sentence)."""
    text = text.strip()
    return bool(_NAME_LIKE.match(text)) and len(text.split()) <= 4


def names_to_smiles(names: Iterable[str]) -> dict[str, str]:
    """Convert names to SMILES with one OPSIN run; return only the names OPSIN understood.

    Raises:
        RuntimeError: OPSIN cannot run (see :func:`unavailable_reason`), or it failed.
    """
    unique = list(dict.fromkeys(" ".join(name.split()) for name in names if name.strip()))
    if not unique:
        return {}
    reason = unavailable_reason()
    if reason:
        raise RuntimeError(f"Names cannot be converted to structures: {reason}.")
    try:
        completed = subprocess.run(
            [find_java(), "-jar", opsin_jar(), "-osmi"],
            input="\n".join(unique) + "\n",
            capture_output=True,
            text=True,
            timeout=max(_MIN_TIMEOUT, _SECONDS_PER_NAME * len(unique)),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"OPSIN could not be run: {exc}") from exc
    if completed.returncode != 0:
        raise RuntimeError(f"OPSIN failed: {completed.stderr.strip()[-300:]}")
    lines = completed.stdout.splitlines()
    if len(lines) < len(unique):
        logger.warning("OPSIN returned %d lines for %d names", len(lines), len(unique))
    return {name: smiles.strip() for name, smiles in zip(unique, lines) if smiles.strip()}


#: Source given to structures OPSIN made from names in the text.
NAME_SOURCE = "text (name)"


def structures_from_names(molecules: list[ExtractedMolecule]) -> int:
    """Give text molecules that are only a name a structure from OPSIN; return how many got one.

    Raises:
        RuntimeError: OPSIN cannot run or failed; no molecule is changed.
    """
    from .chemistry import enrich_molecule

    pending = [
        molecule
        for molecule in molecules
        if not molecule.smiles and molecule.identifier
        and looks_like_systematic_name(molecule.identifier)
    ]
    if not pending:
        return 0
    found = names_to_smiles(molecule.identifier for molecule in pending)
    converted = 0
    for molecule in pending:
        smiles = found.get(" ".join(molecule.identifier.split()))
        if not smiles:
            continue
        molecule.smiles = smiles
        molecule.source = NAME_SOURCE
        enrich_molecule(molecule)
        converted += 1
    return converted
