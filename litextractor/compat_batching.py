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

"""Fix image misalignment in batched RxnScribe/MolDetect predictions.

Upstream ``predict_images`` loops over batches but post-processes each prediction with
``input_images[i]``, where ``i`` is the position *within the batch*. From the second batch on
(figure 17+ at the default batch size), OCR, MolScribe, and reaction parsing therefore read
crops from the wrong figure. These replacements pair every prediction with its own image.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _predict_batches(model_wrapper: Any, input_images: list, batch_size: int, tokenizer: Any):
    """Yield ``(image, raw_prediction)`` pairs, running the detector one batch at a time."""
    import torch

    for start in range(0, len(input_images), batch_size):
        batch_images = input_images[start : start + batch_size]
        tensors, refs = zip(*[model_wrapper.transform(image) for image in batch_images])
        stacked = torch.stack(tensors, dim=0).to(model_wrapper.device)
        with torch.no_grad():
            pred_seqs, pred_scores = model_wrapper.model(stacked, max_len=tokenizer.max_len)
        for image, ref, seqs, scores in zip(batch_images, refs, pred_seqs, pred_scores):
            raw = tokenizer.sequence_to_data(seqs.tolist(), scores.tolist(), scale=ref["scale"])
            yield image, raw


def patch_rxnscribe_batch_images() -> None:
    """Replace ``MolDetect.predict_images`` and ``RxnScribe.predict_images`` with fixed copies."""
    try:
        import rxnscribe.interface as interface_module
    except Exception:
        return

    mol_detect = getattr(interface_module, "MolDetect", None)
    if mol_detect is not None and not getattr(
        mol_detect.predict_images, "_litextractor_patched", False
    ):

        def _mol_detect_predict_images(
            self, input_images, batch_size=16, molscribe=False, coref=False, ocr=False
        ):
            """Detect molecules (and optionally corefs) with each image post-processed itself."""
            tokenizer = self.tokenizer["coref" if coref else "bbox"]
            predictions = []
            for image, raw in _predict_batches(self, input_images, batch_size, tokenizer):
                if coref:
                    predictions.append(
                        interface_module.postprocess_coref_results(
                            raw,
                            image=image,
                            molscribe=self.molscribe if molscribe else None,
                            ocr=self.ocr_model if ocr else None,
                        )
                    )
                else:
                    predictions.append(
                        interface_module.postprocess_bboxes(
                            raw, image=image, molscribe=self.molscribe if molscribe else None
                        )
                    )
            return predictions

        _mol_detect_predict_images._litextractor_patched = True  # type: ignore[attr-defined]
        mol_detect.predict_images = _mol_detect_predict_images

    rxn_scribe = getattr(interface_module, "RxnScribe", None)
    if rxn_scribe is not None and not getattr(
        rxn_scribe.predict_images, "_litextractor_patched", False
    ):

        def _rxn_scribe_predict_images(
            self, input_images, batch_size=16, molscribe=False, ocr=False
        ):
            """Parse reactions with each prediction post-processed against its own image."""
            tokenizer = self.tokenizer["reaction"]
            return [
                interface_module.postprocess_reactions(
                    raw,
                    image=image,
                    molscribe=self.molscribe if molscribe else None,
                    ocr=self.ocr_model if ocr else None,
                )
                for image, raw in _predict_batches(self, input_images, batch_size, tokenizer)
            ]

        _rxn_scribe_predict_images._litextractor_patched = True  # type: ignore[attr-defined]
        rxn_scribe.predict_images = _rxn_scribe_predict_images
