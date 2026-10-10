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

"""Safe HTTP downloads and cache paths for LayoutParser model weights."""

from __future__ import annotations

import logging
import os
import shutil
import uuid
from urllib.parse import urlparse
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

__all__ = [
    "LAYOUTPARSER_HF_WEIGHTS",
    "download_url_to_file",
    "dropbox_direct_url",
    "huggingface_weight_url",
    "looks_like_html",
    "patch_iopath_http_cache_filenames",
    "safe_http_cache_filename",
]

LAYOUTPARSER_HF_WEIGHTS: dict[str, tuple[str, str]] = {
    "publaynet-tf_efficientdet_d0.pth.tar": (
        "layoutparser/efficientdet",
        "PubLayNet/tf_efficientdet_d0/publaynet-tf_efficientdet_d0.pth.tar",
    ),
    "publaynet-tf_efficientdet_d1.pth.tar": (
        "layoutparser/efficientdet",
        "PubLayNet/tf_efficientdet_d1/publaynet-tf_efficientdet_d1.pth.tar",
    ),
    "mfd-tf_efficientdet_d0.pth.tar": (
        "layoutparser/efficientdet",
        "MFD/tf_efficientdet_d0/mfd-tf_efficientdet_d0.pth.tar",
    ),
    "mfd-tf_efficientdet_d1.pth.tar": (
        "layoutparser/efficientdet",
        "MFD/tf_efficientdet_d1/mfd-tf_efficientdet_d1.pth.tar",
    ),
}


def safe_http_cache_filename(url: str) -> str:
    """Basename for an HTTP cache file, without query strings (illegal on Windows)."""
    path = urlparse(url).path.rstrip("/")
    name = path.split("/")[-1] if path else ""
    return name or "download.bin"


def huggingface_weight_url(filename: str) -> str | None:
    """HTTP URL for a LayoutParser weight hosted on Hugging Face, if known."""
    spec = LAYOUTPARSER_HF_WEIGHTS.get(filename)
    if spec is None:
        return None
    repo, path = spec
    return f"https://huggingface.co/{repo}/resolve/main/{path}"


def dropbox_direct_url(url: str) -> str:
    """Convert a Dropbox share link to a direct file URL (avoids HTML landing pages)."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host in ("www.dropbox.com", "dropbox.com") and parsed.path.startswith("/s/"):
        return f"https://dl.dropboxusercontent.com{parsed.path}"
    return url


def looks_like_html(path: str) -> bool:
    """True if *path* starts with an HTML doctype (failed Dropbox download)."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(32).lstrip().lower()
    except OSError:
        return False
    return head.startswith(b"<!doctype") or head.startswith(b"<html")


def download_url_to_file(url: str, dest: str) -> None:
    """Download *url* to *dest*, trying Hugging Face then Dropbox, rejecting HTML."""
    filename = safe_http_cache_filename(url)
    spec = LAYOUTPARSER_HF_WEIGHTS.get(filename)
    if spec is not None:
        try:
            from huggingface_hub import hf_hub_download

            cached = hf_hub_download(repo_id=spec[0], filename=spec[1])
            if cached and os.path.isfile(cached) and not looks_like_html(cached):
                os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
                if os.path.abspath(cached) != os.path.abspath(dest):
                    shutil.copyfile(cached, dest)
                return
        except Exception as exc:
            logger.warning("Hugging Face hub download failed for %s: %s", filename, exc)

    candidates: list[str] = []
    hf_url = huggingface_weight_url(filename)
    if hf_url:
        candidates.append(hf_url)
    direct = dropbox_direct_url(url)
    if direct != url:
        candidates.append(direct)
    candidates.append(url)
    last_error: Exception | None = None
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    for candidate in candidates:
        tmp_path = dest + ".tmp"
        try:
            request = Request(
                candidate,
                headers={"User-Agent": "PatentExtractor/0.1 (layoutparser-weights)"},
            )
            with urlopen(request, timeout=120) as response, open(tmp_path, "wb") as handle:
                shutil.copyfileobj(response, handle)
            if looks_like_html(tmp_path):
                os.remove(tmp_path)
                last_error = RuntimeError(
                    f"Download from {candidate} returned HTML, not a model file."
                )
                continue
            os.replace(tmp_path, dest)
            return
        except Exception as exc:
            last_error = exc
            if os.path.isfile(tmp_path):
                os.remove(tmp_path)
    raise RuntimeError(f"Could not download a valid model file from {url}") from last_error


def patch_iopath_http_cache_filenames() -> None:
    """Patch iopath's Windows-unsafe query-string cache names and HTTP downloads."""
    try:
        from iopath.common.file_io import HTTPURLHandler, file_lock, get_cache_dir
    except ImportError:
        return
    if getattr(HTTPURLHandler, "_patentextractor_patched", False):
        return

    def _get_local_path(
        self, path: str, force: bool = False, cache_dir: str | None = None, **kwargs: object
    ) -> str:
        self._check_kwargs(kwargs)
        parsed_url = urlparse(path)
        dirname = os.path.join(
            get_cache_dir(cache_dir), os.path.dirname(parsed_url.path.lstrip("/"))
        )
        filename = safe_http_cache_filename(path)
        if len(filename) > HTTPURLHandler.MAX_FILENAME_LEN:
            filename = filename[:100] + "_" + uuid.uuid4().hex
        cached = os.path.join(dirname, filename)
        need_download = (
            force
            or path not in self.cache_map
            or not os.path.isfile(cached)
            or looks_like_html(cached)
        )
        if need_download:
            with file_lock(cached):
                if force or not os.path.isfile(cached) or looks_like_html(cached):
                    logger.info("Downloading %s ...", path)
                    download_url_to_file(path, cached)
            logger.info("URL %s cached in %s", path, cached)
        self.cache_map[path] = cached
        return cached

    HTTPURLHandler._get_local_path = _get_local_path  # type: ignore[method-assign]
    HTTPURLHandler._patentextractor_patched = True
    logger.info("Patched iopath HTTP cache to strip query strings from filenames.")