#!/usr/bin/env python3
"""Download remote media files for browser upload workflows."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from urllib.parse import unquote, urlparse


DEFAULT_TIMEOUT = 30
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".flv", ".wmv", ".webm"}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


class MediaDownloader:
    def __init__(self, temp_dir: str | None = None):
        if temp_dir:
            self.temp_dir = Path(temp_dir).expanduser().resolve()
            self.temp_dir.mkdir(parents=True, exist_ok=True)
            self._owns_dir = False
        else:
            self.temp_dir = Path(tempfile.mkdtemp(prefix="browser-media-"))
            self._owns_dir = True
        self.downloaded_files: list[str] = []

    def _guess_extension(self, url: str, content_type: str | None, allowed: set[str], default: str) -> str:
        path = urlparse(url).path
        ext = Path(unquote(path)).suffix.lower()
        if ext in allowed:
            return ext

        mapping = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/gif": ".gif",
            "image/webp": ".webp",
            "image/bmp": ".bmp",
            "video/mp4": ".mp4",
            "video/quicktime": ".mov",
            "video/x-msvideo": ".avi",
            "video/x-matroska": ".mkv",
            "video/x-flv": ".flv",
            "video/x-ms-wmv": ".wmv",
            "video/webm": ".webm",
        }
        if content_type:
            for mime, mapped_ext in mapping.items():
                if mime in content_type:
                    return mapped_ext
        return default

    def _download(self, url: str, allowed: set[str], default_ext: str, timeout: int) -> str:
        try:
            import requests
        except ImportError as exc:
            raise RuntimeError("requests package is not installed. Run: python3 -m pip install requests") from exc

        parsed = urlparse(url)
        headers = {
            "Referer": f"{parsed.scheme}://{parsed.netloc}/" if parsed.scheme and parsed.netloc else url,
            "User-Agent": USER_AGENT,
        }
        response = requests.get(url, timeout=timeout, stream=True, headers=headers)
        response.raise_for_status()
        ext = self._guess_extension(url, response.headers.get("Content-Type"), allowed, default_ext)
        path = self.temp_dir / f"{uuid.uuid4().hex[:12]}{ext}"
        with path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=65536):
                if chunk:
                    handle.write(chunk)
        self.downloaded_files.append(str(path))
        return str(path)

    def download_image(self, url: str) -> str:
        return self._download(url, IMAGE_EXTENSIONS, ".jpg", DEFAULT_TIMEOUT)

    def download_video(self, url: str) -> str:
        return self._download(url, VIDEO_EXTENSIONS, ".mp4", DEFAULT_TIMEOUT * 4)

    def download_images(self, urls: list[str]) -> list[str]:
        return [self.download_image(url) for url in urls]

    def cleanup(self) -> None:
        if self._owns_dir and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        else:
            for path in self.downloaded_files:
                try:
                    os.remove(path)
                except OSError:
                    pass
        self.downloaded_files.clear()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.cleanup()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: media_downloader.py <url>")
    with MediaDownloader() as downloader:
        print(downloader.download_image(sys.argv[1]))
