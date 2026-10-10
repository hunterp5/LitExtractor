# This file is part of PatentExtractor.
# Copyright (C) 2026 Hunter Picard
#
# PatentExtractor is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# PatentExtractor is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with PatentExtractor.  If not, see <https://www.gnu.org/licenses/>.

"""Citation guide for the application's core software and extraction models."""

from __future__ import annotations

from html import escape

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout

from ... import __version__
from ..qt_widget_utils import make_window_minimizable


class CitationsDialog(QDialog):
    """Show bibliographic citations and project credits for the main technology stack."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Citations")
        self.resize(780, 700)
        self.setMinimumSize(620, 480)

        self._browser = QTextBrowser(self)
        self._browser.setOpenExternalLinks(True)
        self._browser.setHtml(self._citation_html())

        buttons = QDialogButtonBox(QDialogButtonBox.Close, parent=self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(self._browser)
        layout.addWidget(buttons)
        make_window_minimizable(self)

    @staticmethod
    def _citation_html() -> str:
        version = escape(__version__)
        return f"""<!doctype html>
<html>
<head>
<style>
body {{ line-height: 1.45; }}
h1 {{ margin-bottom: 0.2em; }}
h2 {{ margin-top: 1.1em; margin-bottom: 0.25em; }}
p {{ margin-top: 0.25em; margin-bottom: 0.65em; }}
li {{ margin-bottom: 0.45em; }}
</style>
</head>
<body>
<h1>Citations</h1>
<p>For publications using PatentExtractor, cite the application and core technologies below.
Include model citations only for the extraction features used in your work. Software documentation
is linked where a project does not publish a separate research paper.</p>

<h2>Application</h2>
<p>Picard, H. (2026). <i>PatentExtractor</i> (version {version}) [Computer software].
GNU General Public License v3 or later.</p>

<h2>Core software</h2>
<ul>
<li><b>Python.</b> Python Software Foundation. <i>Python 3 documentation</i>.
<a href="https://docs.python.org/3/">Official documentation</a>.</li>
<li><b>Qt for Python (PySide6).</b> The Qt Company. <i>Qt for Python documentation</i>.
<a href="https://doc.qt.io/qtforpython-6/">Official documentation</a>.</li>
<li><b>PyTorch.</b> Ansel, J. et al. (2024). “PyTorch 2: Faster Machine Learning Through Dynamic
Python Bytecode Transformation and Graph Compilation.” <i>ASPLOS ’24</i>, 929–947.
<a href="https://doi.org/10.1145/3620665.3640366">doi:10.1145/3620665.3640366</a>.</li>
<li><b>RDKit.</b> <i>RDKit: Open-source cheminformatics</i>.
<a href="https://www.rdkit.org/docs/Overview.html#citing-the-rdkit">Recommended citation</a>;
include the DOI for the RDKit version used, available from
<a href="https://doi.org/10.5281/zenodo.591637">RDKit's version DOI record</a>.</li>
</ul>

<h2>Extraction framework</h2>
<ul>
<li><b>OpenChemIE.</b> Fan et al. (2024). “OpenChemIE: An Information Extraction Toolkit for
Chemistry Literature.” <i>Journal of Chemical Information and Modeling, 64</i>(14), 5521–5534.
<a href="https://doi.org/10.1021/acs.jcim.4c00572">doi:10.1021/acs.jcim.4c00572</a>.</li>
</ul>

<h2>Text-model framework</h2>
<p><b>Transformers.</b> Wolf, T. et al. (2020). “Transformers: State-of-the-Art Natural Language
Processing.” <i>Proceedings of the 2020 Conference on Empirical Methods in Natural Language
Processing: System Demonstrations</i>, 38–45.
<a href="https://doi.org/10.18653/v1/2020.emnlp-demos.6">doi:10.18653/v1/2020.emnlp-demos.6</a>.</p>
</body>
</html>"""
