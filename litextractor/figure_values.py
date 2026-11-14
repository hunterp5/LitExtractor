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

"""Values printed under structures in figures: "FAK: IC50 = 4.0 nM", "Cmax (ng/mL) = 75.4".

Medicinal chemistry figures often print a compound's activity, and sometimes its
pharmacokinetics, as a stack of lines below the structure. These lines are found in the text
layer or OCR (OCR splits a line into pieces, which are joined again by baseline), kept on the
molecule as printed (``ExtractedMolecule.figure_values``) and split into a name and a value
for the exports.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .text_labels import _CAPTION, Box, TextLine, _center, _grow, _inside, _is_label_text

# OCR misreadings of what is printed in these lines.
_OCR_FIXES: list[tuple[re.Pattern[str], str]] = [
    # "ICs0", "ICso", "IC5o" for IC50 (and EC50, GI50, ...).
    (re.compile(r"\b(IC|EC|GI|CC|LD|ED|ID|DC)\s*[s5S][0oO]\b"), r"\g<1>50"),
    # "t12(h)", "tiz(h)", "tuz", "tin2", "tl/2" and other readings of t1/2.
    (re.compile(r"\bt\s*(?:[1il]\s*/\s*2|[1il]n?[2z]|[uv]z|z|½)(?=\s*\()"), "t1/2"),
    # "Fofo", "Folo", "F o/o" for F%.
    (re.compile(r"\bF\s*(?:[o0]\s*[/lf]\s*[o0]|%)(?=\s|=|$)"), "F%"),
    # "AUCo-" for "AUC0-".
    (re.compile(r"\bAUCo(?=\s*-)"), "AUC0"),
]
# A slash read as "l" or "I" between two units: "nglmL", "mLlminlkg", "ugIL".
_UNIT = r"(?:mL|L|ng|mg|ug|μg|µg|pg|g|kg|min|h|μL|µL|pL|mol|nmol|μmol|µmol)"
_SLASH_AS_LETTER = re.compile(rf"(?<![A-Za-z])({_UNIT})[lI](?={_UNIT}(?![a-km-z]))")

# What a value line names: an activity, a pharmacokinetic quantity, a dose. Case matters for
# the short names ("CL" is clearance, "Cl" chlorine).
_ACTIVITY = re.compile(
    r"\b(?:IC|EC|GI|CC|LD|ED|DC|ID)\s*50\b|\bK[id]\b|\bD\s*max\b|\binhibition\b|\bMIC\b"
)
_PK_NAMES = re.compile(
    r"\b(?:C\s*max|[Tt]\s*max|t1/2|AUC\w*|CL\w*|Vd?ss|Vd|MRT|F%)"
    r"|\b(?:bioavailability|half-life|clearance)\b"
)
_DOSE = re.compile(r"\d\s*(?:mg|μg|µg|ug)\s*/\s*kg\b")
# "Vd(L/kg) 13.2", "F% 16.37": a name with a unit, then a number.
_NAME_UNIT_NUMBER = re.compile(r"[A-Za-z][^=]*?[(%][^=]*?\s[<>≤≥~]?\s*-?\d[\d.,]*\s*\S{0,6}$")
# "Solubility (mg/mL) = 456", "cLogP = 3.1": a name of two or more letters, "=", a number.
_NAME_EQUALS_NUMBER = re.compile(r"^[A-Za-z][\w()/%*.,\-\s]*[A-Za-z)%][\w()/%*.\-\s]*=\s*[<>≤≥~]?\s*-?\d")
# "43: R = Et", "39: R1 = Et; R2 = H": which compound of a shared drawing the values below are.
_COMPOUND_HEADING = re.compile(r"^\d{1,4}[a-z]?\s*[:,]\s*R")
# Reaction conditions are printed under structures in schemes; they are not values.
_CONDITIONS = re.compile(
    r"\byield\b|\breflux\b|\bequiv|\br\.?\s*t\b|\bovernight\b|\d\s*[°*º]\s*C\b|\bmol\s*%"
    r"|\bsteps?\b|\bsynthesis\b",
    re.IGNORECASE,
)
_VALUE = re.compile(
    r"^(?P<qualifier><=|>=|[<>≤≥~≈])?\s*(?P<number>-?\d[\d,]*(?:\.\d+)?|-?\.\d+)"
    r"(?:\s*(?:±|\+/-)\s*[\d.]+)?\s*(?P<unit>[%°µμa-zA-Z][\w%/·*.\-]{0,15})?$"
)
_TRAILING_UNIT = re.compile(r"\s*[(\[]\s*([%°µμa-zA-Z][%°µμa-zA-Z0-9/·*.\-]{0,15})\s*[)\]]\s*$")
# "n = 8", "(n = 3)", "R = Me", "X = Cl": a repeat count or a substituent, not a measurement.
_ONE_LETTER_NAME = re.compile(r"^\(?\s*[A-Za-z]\d?'*\s*=")
_QUALIFIERS = {"<=": "<=", ">=": ">=", "≤": "<=", "≥": ">=", "≈": "~"}

# A line is part of a block while the gap to the line above is at most this many line heights.
_STACK_GAP_LINES = 1.2
# A block belongs to the nearest structure within this many points (or half its size).
_MAX_DISTANCE = 40.0
# Distance to a structure to the right of a block, or below it, counts this many times over.
_AWAY_WEIGHT = 3.0
# For a line above or below a structure, how much an off-centre position counts.
_OFFSET_WEIGHT = 0.25
# The same for a line inside the box: less, so a structure's own box beats a neighbour's edge.
_INSIDE_OFFSET_WEIGHT = 0.1


def fix_ocr_text(text: str) -> str:
    """Undo common OCR misreadings in an activity or pharmacokinetic line."""
    for pattern, replacement in _OCR_FIXES:
        text = pattern.sub(replacement, text)
    previous = None
    while previous != text:
        previous, text = text, _SLASH_AS_LETTER.sub(r"\1/", text)
    return text


def join_baselines(lines: list[TextLine]) -> list[TextLine]:
    """Join pieces of text that sit side by side on one line, as OCR returns them.

    Two pieces are joined when their middles are level (within a quarter of a line height),
    the gap between them is at most one line height, and the pieces are not two values printed
    side by side ("FAK: IC50 = 4 nM" and "FAK: IC50 = 7 nM" under neighbouring structures).
    """
    remaining = sorted(lines, key=lambda line: (line.box[0], -line.box[3]))
    joined: list[TextLine] = []
    while remaining:
        current = remaining.pop(0)
        changed = True
        while changed:
            changed = False
            for index, other in enumerate(remaining):
                if _same_line(current, other):
                    box = (min(current.box[0], other.box[0]), min(current.box[1], other.box[1]),
                           max(current.box[2], other.box[2]), max(current.box[3], other.box[3]))
                    current = TextLine(box, f"{current.text} {other.text}")
                    del remaining[index]
                    changed = True
                    break
        joined.append(current)
    return joined


def _same_line(left: TextLine, right: TextLine) -> bool:
    height = max(_height(left), _height(right))
    middle_left = (left.box[1] + left.box[3]) / 2
    middle_right = (right.box[1] + right.box[3]) / 2
    gap = right.box[0] - left.box[2]
    if height <= 0 or abs(middle_left - middle_right) > 0.25 * height:
        return False
    if not -0.5 * height <= gap <= height:
        return False
    # A new line starts with "Target:", and a line with "=" in it is complete.
    if ":" in right.text or ("=" in left.text and not left.text.endswith("=")):
        return False
    # "AUC (ng*h/mL) 2757" ends with its value: what follows is another line.
    last_word = left.text.split()[-1] if left.text.split() else ""
    return not (re.fullmatch(r"[\d.,]+", last_word) and "=" in right.text)


def is_value_line(text: str) -> bool:
    """True for a line that carries data: an activity, a dose, a pharmacokinetic value.

    Reaction conditions ("iPrOH, 80 °C, 8 h", "64% yield"), captions, repeat counts and
    substituents ("n = 8", "R = Me") are not values.
    """
    if _ONE_LETTER_NAME.match(text) or _CONDITIONS.search(text) or _CAPTION.match(text):
        return False
    if not any(char.isdigit() for char in text) and "N.T." not in text:
        return False
    return bool(
        _ACTIVITY.search(text) or _PK_NAMES.search(text) or _DOSE.search(text)
        or _NAME_UNIT_NUMBER.search(text) or _NAME_EQUALS_NUMBER.search(text)
    )


def _is_heading(text: str) -> bool:
    """A line introducing the values below it: "in human liver microsomes:", "43: R = Et"."""
    if _COMPOUND_HEADING.match(text):
        return True
    return text.endswith(":") and len(text.split()) <= 6 and not _is_label_text(text)


def values_near(
    molecule_boxes: list[Box], lines: list[TextLine], region: Box | None
) -> list[list[str]]:
    """The data lines printed next to each structure in a figure, top to bottom.

    Lines are grouped into blocks: lines stacked closely one below another, as values are
    printed. Each block goes to the nearest structure, measured from the block's nearest line;
    blocks are printed below or to the right of their structure, so structures to a block's
    right or below it count as further away. Only data lines are kept (labels are
    identifiers, atom labels belong to the drawing), with a heading such as
    "in human liver microsomes:" when data follows it.
    """
    candidates = [
        line
        for line in join_baselines(lines)
        if (region is None or _inside(_center(line.box), _grow(region, 4)))
        and (is_value_line(line.text)
             or not any(_inside(_center(line.box), box) for box in molecule_boxes))
    ]
    found: list[list[TextLine]] = [[] for _ in molecule_boxes]
    for block in _blocks(candidates):
        if not molecule_boxes or not any(is_value_line(line.text) for line in block):
            continue
        distances = [min(_distance(line.box, box) for line in block) for box in molecule_boxes]
        nearest = min(range(len(molecule_boxes)), key=distances.__getitem__)
        box = molecule_boxes[nearest]
        if distances[nearest] <= max(_MAX_DISTANCE, 0.5 * min(box[2] - box[0], box[3] - box[1])):
            found[nearest] += block
    return [_kept_lines(sorted(block, key=lambda line: -line.box[3])) for block in found]


def _blocks(lines: list[TextLine]) -> list[list[TextLine]]:
    """Group lines into stacks: each line closely below the last line of its stack."""
    blocks: list[list[TextLine]] = []
    for line in sorted(lines, key=lambda line: -line.box[3]):
        best: tuple[float, list[TextLine]] | None = None
        for block in blocks:
            last = block[-1]
            gap = last.box[1] - line.box[3]
            limit = _STACK_GAP_LINES * max(_height(last), _height(line))
            overlaps = line.box[0] < last.box[2] and line.box[2] > last.box[0]
            aligned = abs(line.box[0] - last.box[0]) <= max(_height(last), _height(line))
            if -0.5 * _height(line) <= gap <= limit and (overlaps or aligned):
                if best is None or gap < best[0]:
                    best = (gap, block)
        if best is None:
            blocks.append([line])
        else:
            best[1].append(line)
    return blocks


def _distance(line: Box, structure: Box) -> float:
    """How far a line is from a structure, weighted by the side the structure is on.

    A line that only clips the structure's box (its corner, say) is measured from its middle.
    """
    overlap_x = min(line[2], structure[2]) - max(line[0], structure[0])
    overlap_y = min(line[3], structure[3]) - max(line[1], structure[1])
    area = (line[2] - line[0]) * (line[3] - line[1])
    if overlap_x > 0 and overlap_y > 0:
        if overlap_x * overlap_y >= 0.5 * area:
            # Inside the box (boxes can overlap): the structure it is centred on wins.
            return _INSIDE_OFFSET_WEIGHT * abs(_center(line)[0] - _center(structure)[0])
        middle_x, middle_y = _center(line)
        line = (middle_x, middle_y, middle_x, middle_y)
    right_of_line = max(0.0, structure[0] - line[2])
    left_of_line = max(0.0, line[0] - structure[2])
    below_line = max(0.0, line[1] - structure[3])
    above_line = max(0.0, structure[1] - line[3])
    dx = left_of_line + _AWAY_WEIGHT * right_of_line
    dy = above_line + _AWAY_WEIGHT * below_line
    if dx == 0:
        # Above or below the structure: values are centred on theirs.
        dx = _OFFSET_WEIGHT * abs(_center(line)[0] - _center(structure)[0])
    return (dx * dx + dy * dy) ** 0.5


def _height(line: TextLine) -> float:
    return line.box[3] - line.box[1]


def _kept_lines(stack: list[TextLine]) -> list[str]:
    kept: list[str] = []
    for index, line in enumerate(stack):
        text = line.text
        if is_value_line(text):
            kept.append(text)
        elif _is_heading(text) and any(is_value_line(after.text) for after in stack[index + 1:]):
            kept.append(text)
    return kept


@dataclass(frozen=True)
class FigureValue:
    """One value line split into its parts.

    Attributes:
        name: What was measured, e.g. "FAK IC50" or "Cmax (ng/mL)".
        value: The value as printed, e.g. "4.0 nM" or "<1".
        qualifier: "<", ">", "<=", ">=", "~" or "".
        number: The number, or None when the value is not a number.
        unit: The unit after the number or at the end of the name, or "".
        heading: The heading above the line within its stack, e.g. "in rat: 5 mg/kg IV dose".
    """

    name: str
    value: str
    qualifier: str
    number: float | None
    unit: str
    heading: str = ""


def parse_value_line(text: str, heading: str = "") -> FigureValue | None:
    """Split "FAK: IC50 = 4.0 nM" into name and value; None when the line has no value."""
    if "=" in text:
        name, value = text.rsplit("=", 1)
    else:
        match = re.search(r"\s([<>≤≥~]?\s*-?\d[\d.,]*\s*\S{0,6})$", text)
        if not match or not re.search(r"[A-Za-z]", text[: match.start()]):
            return None
        name, value = text[: match.start()], match.group(1)
    name = " ".join(name.replace(":", " ").split())
    value = value.strip()
    if not name or not value:
        return None
    qualifier, number, unit = "", None, ""
    parsed = _VALUE.match(value)
    if parsed:
        qualifier = _QUALIFIERS.get(parsed.group("qualifier") or "", parsed.group("qualifier") or "")
        try:
            number = float(parsed.group("number").replace(",", ""))
        except ValueError:
            number = None
        unit = parsed.group("unit") or ""
    if number is not None and not unit:
        name_unit = _TRAILING_UNIT.search(name)
        unit = name_unit.group(1) if name_unit else ""
    return FigureValue(name, value, qualifier, number, unit, heading)


def parse_figure_values(lines: list[str]) -> list[FigureValue]:
    """Parse a molecule's value lines, giving each the heading above it (if any)."""
    values: list[FigureValue] = []
    heading = ""
    for text in lines:
        if _COMPOUND_HEADING.match(text):
            heading = text.rstrip(";").strip()
            continue
        if not is_value_line(text):
            if _is_heading(text):
                heading = text.rstrip(":").strip()
            continue
        parsed = parse_value_line(text, heading)
        if parsed is not None:
            values.append(parsed)
        else:
            heading = text  # "in rat: 5 mg/kg IV dose" introduces the lines after it
    return values
