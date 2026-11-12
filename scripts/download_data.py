"""Fetch the Recipe Box archive and extract the 3 JSON files into DATA_DIR.

Link source: the "Download recipes" anchor on https://eightportions.com/datasets/Recipes/
-> https://eightportions.com/recipes_raw.zip   (URL is configurable: --url or env DATA_URL).
Offline fallback: download the zip in a browser, then `python -m scripts.download_data --zip <path>`.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import zipfile
from pathlib import Path

import requests

from recipebot.db import SOURCE_FILES, SOURCES, data_dir

DEFAULT_URL = "https://eightportions.com/recipes_raw.zip"


def download(url: str, dest: Path, timeout: int = 60) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    with requests.get(url, stream=True, timeout=timeout, headers={"User-Agent": "recipebot-takehome/0.1"}) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done = 0
        with open(part, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r  {done / 1e6:7.1f} / {total / 1e6:.1f} MB", end="", flush=True)
        print()
    os.replace(part, dest)


def extract_zip(zip_path: Path, directory: Path) -> dict[str, Path]:
    """Extract the ar/epi/fn JSON files to canonical names (nested dirs / zip-slip safe: basenames only)."""
    if not zipfile.is_zipfile(zip_path):
        raise SystemExit(f"{zip_path} is not a zip file (got an HTML error page?). Check the URL.")
    directory.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}
    with zipfile.ZipFile(zip_path) as z:
        picked = {}
        for m in z.infolist():
            base = os.path.basename(m.filename).lower()
            if m.is_dir() or m.filename.startswith("__MACOSX") or base.startswith("._"):
                continue
            mm = re.search(r"(?:^|[_\-])(ar|epi|fn)\.json$", base)
            if mm and mm.group(1) not in picked:
                picked[mm.group(1)] = m
        missing = [s for s in SOURCES if s not in picked]
        if missing:
            names = [m.filename for m in z.infolist()]
            raise SystemExit(f"Archive lacks JSON for {missing}. Members: {names}")
        for src, m in picked.items():
            target = directory / SOURCE_FILES[src]
            part = target.with_name(target.name + ".part")
            with z.open(m) as fin, open(part, "wb") as fout:
                shutil.copyfileobj(fin, fout)
            os.replace(part, target)
            out[src] = target
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=os.environ.get("DATA_URL", DEFAULT_URL))
    ap.add_argument("--zip", type=Path, help="use an already-downloaded archive instead of fetching")
    ap.add_argument("--data-dir", type=Path, default=None)
    ap.add_argument("--force", action="store_true", help="re-download/extract even if the JSON files exist")
    ap.add_argument("--keep-zip", action="store_true")
    a = ap.parse_args(argv)

    directory = a.data_dir or data_dir()
    if not a.force and all((directory / f).exists() for f in SOURCE_FILES.values()):
        print(f"Data already present in {directory} (use --force to redo).")
        return 0

    zip_path = a.zip
    fetched = False
    if zip_path is None:
        zip_path = directory / "recipes_raw.zip"
        print(f"Downloading {a.url}")
        try:
            download(a.url, zip_path)
            fetched = True
        except requests.RequestException as e:
            print(f"Download failed: {e}\nSet DATA_URL / --url, or download the zip manually from "
                  "https://eightportions.com/datasets/Recipes/ and pass --zip <path>.", file=sys.stderr)
            return 1
    files = extract_zip(zip_path, directory)
    for src, p in files.items():
        print(f"  {src}: {p} ({p.stat().st_size / 1e6:.1f} MB)")
    if fetched and not a.keep_zip:
        zip_path.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
