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

"""Desktop tool for extracting chemical structures from patents."""

from __future__ import annotations

import warnings

# Silence noisy third-party deprecation warnings from the OpenChemIE runtime stack.
# These warnings do not indicate an application failure but are repeated during startup
# and extraction runs and obscure useful console output.
warnings.filterwarnings(
    "ignore",
    message=r"PyPDF2 is deprecated.*",
    category=DeprecationWarning,
)
warnings.filterwarnings(
    "ignore",
    message=r"Please import `gaussian_filter` from the `scipy\.ndimage` namespace.*",
    category=DeprecationWarning,
)
warnings.filterwarnings(
    "ignore",
    message=r"The parameter 'pretrained' is deprecated since 0\.13.*",
    category=UserWarning,
)
warnings.filterwarnings(
    "ignore",
    message=r"Arguments other than a weight enum or `None` for 'weights'.*",
    category=UserWarning,
)
warnings.filterwarnings(
    "ignore",
    message=r"torch\.utils\.checkpoint: the use_reentrant parameter should be passed explicitly.*",
    category=UserWarning,
)
warnings.filterwarnings(
    "ignore",
    message=r"None of the inputs have requires_grad=True.*",
    category=UserWarning,
)
warnings.filterwarnings(
    "ignore",
    message=r"torch\.cuda\.amp\.custom_fwd\(args\.\.\.\).*",
    category=FutureWarning,
)
warnings.filterwarnings(
    "ignore",
    message=r"torch\.cuda\.amp\.custom_bwd\(args\.\.\.\).*",
    category=FutureWarning,
)

__version__ = "0.1.0"
