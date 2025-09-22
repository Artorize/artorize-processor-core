from __future__ import annotations

import argparse
import os
import sys
from typing import List

from .core import run_pipeline, dumps_json
from .processors import (
    MetadataProcessor,
    ImageHashesProcessor,
    DHashProcessor,
    BlockHashProcessor,
    SteganoProcessor,
    TinEyeProcessor,
)
from .utils import extend_sys_path


def build_processors(
    include_tineye: bool,
    *,
    include_hashes: bool = True,
    include_stegano_analysis: bool = True,
) -> List[object]:
    procs: List[object] = [MetadataProcessor()]
    if include_hashes:
        procs.extend([ImageHashesProcessor(), DHashProcessor(), BlockHashProcessor()])
    if include_stegano_analysis:
        procs.append(SteganoProcessor())
    if include_tineye:
        procs.append(TinEyeProcessor())
    return procs


def main(argv: List[str] | None = None) -> int:
    extend_sys_path()

    p = argparse.ArgumentParser(
        prog="artscraper-runner",
        description=(
            "Run a single image (png/jpeg/raw) through available processors:"
            " metadata, hashing (imagehash/dhash/blockhash), LSB steganography,"
            " and optional TinEye search."
        ),
    )
    p.add_argument("image", help="Path to input image file")
    p.add_argument("--json-out", help="Write aggregated JSON results to path")
    p.add_argument("--tineye", action="store_true", help="Enable TinEye search if API key is set")

    args = p.parse_args(argv)

    if not os.path.isfile(args.image):
        print(f"error: not a file: {args.image}", file=sys.stderr)
        return 2

    processors = build_processors(include_tineye=bool(args.tineye))
    results = run_pipeline(args.image, processors)

    text = dumps_json(results)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"wrote {args.json_out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

