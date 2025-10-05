from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

import numpy as np
from PIL import Image

MASK_MODE = "RGBA"
DIFF_OFFSET = 32768  # center of uint16 range for signed diff packing


@dataclass
class MaskComputation:
    hi_image: Image.Image
    lo_image: Image.Image
    diff_stats: Dict[str, float]
    size: Tuple[int, int]
    diff_min: int
    diff_max: int


def load_image(path: Path, mode: str = MASK_MODE) -> Image.Image:
    """Load an image and normalise its mode for consistent integer math."""
    image = Image.open(path)
    if mode:
        image = image.convert(mode)
    return image


def _encode_difference(diff: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Pack signed 16-bit differences into two uint8 planes (hi, lo)."""
    diff_int = diff.astype(np.int32)
    encoded = diff_int + DIFF_OFFSET
    if encoded.min() < 0 or encoded.max() > 65535:
        raise ValueError("Difference encoding exceeded 16-bit packing range.")

    encoded = encoded.astype(np.uint16)
    hi = (encoded >> 8).astype(np.uint8)
    lo = (encoded & 0xFF).astype(np.uint8)
    return hi, lo


def _decode_difference(hi: np.ndarray, lo: np.ndarray) -> np.ndarray:
    """Recover signed differences from packed hi/lo planes."""
    hi_u16 = hi.astype(np.uint16)
    lo_u16 = lo.astype(np.uint16)
    encoded = (hi_u16 << 8) | lo_u16
    diff = encoded.astype(np.int32) - DIFF_OFFSET
    return diff.astype(np.int16)


def compute_mask(original: Image.Image, processed: Image.Image) -> MaskComputation:
    """Return the packed difference mask that recreates the original exactly."""
    if original.size != processed.size:
        raise ValueError(
            "Images must share the same dimensions before computing a blend mask; "
            f"got original={original.size}, processed={processed.size}."
        )

    original_arr = np.asarray(original, dtype=np.uint8)
    processed_arr = np.asarray(processed, dtype=np.uint8)

    diff = original_arr.astype(np.int16) - processed_arr.astype(np.int16)

    diff_min = int(diff.min())
    diff_max = int(diff.max())

    abs_diff = np.abs(diff)
    diff_stats = {
        "mean_abs_diff": float(abs_diff.mean()),
        "max_abs_diff": float(abs_diff.max()),
        "nonzero_ratio": float(np.count_nonzero(abs_diff) / abs_diff.size),
    }

    hi_plane, lo_plane = _encode_difference(diff)

    hi_image = Image.fromarray(hi_plane)
    lo_image = Image.fromarray(lo_plane)

    return MaskComputation(
        hi_image=hi_image,
        lo_image=lo_image,
        diff_stats=diff_stats,
        size=processed.size,
        diff_min=diff_min,
        diff_max=diff_max,
    )


def reconstruct_preview(processed: Image.Image, mask_hi: Image.Image, mask_lo: Image.Image) -> Image.Image:
    """Recreate the original image using the processed frame and packed mask planes."""
    processed_arr = np.asarray(processed, dtype=np.int32)
    hi_arr = np.asarray(mask_hi, dtype=np.uint8)
    lo_arr = np.asarray(mask_lo, dtype=np.uint8)

    diff = _decode_difference(hi_arr, lo_arr).astype(np.int32)
    reconstructed = processed_arr + diff
    reconstructed = np.clip(reconstructed, 0, 255).astype(np.uint8)

    return Image.fromarray(reconstructed)


def _build_js_snippet(filter_id: str, css_class: str, processed_src: str, mask_hi_src: str, mask_lo_src: str) -> str:
    """Return a vanilla JS helper that swaps an <img> with a canvas-backed reconstruction."""
    return (
        "async function applyPoisonMask(img) {\n"
        "  const [procResp, hiResp, loResp] = await Promise.all([\n"
        "    fetch(img.src),\n"
        "    fetch('" + mask_hi_src + "'),\n"
        "    fetch('" + mask_lo_src + "')\n"
        "  ]);\n"
        "  const [proc, hi, lo] = await Promise.all([\n"
        "    createImageBitmap(await procResp.blob()),\n"
        "    createImageBitmap(await hiResp.blob()),\n"
        "    createImageBitmap(await loResp.blob())\n"
        "  ]);\n"
        "  const canvas = document.createElement('canvas');\n"
        "  canvas.width = proc.width;\n"
        "  canvas.height = proc.height;\n"
        "  const ctx = canvas.getContext('2d', { willReadFrequently: true });\n"
        "  ctx.drawImage(proc, 0, 0);\n"
        "  const procData = ctx.getImageData(0, 0, proc.width, proc.height);\n"
        "  const hiCanvas = new OffscreenCanvas(proc.width, proc.height);\n"
        "  const hiCtx = hiCanvas.getContext('2d');\n"
        "  hiCtx.drawImage(hi, 0, 0);\n"
        "  const hiData = hiCtx.getImageData(0, 0, proc.width, proc.height);\n"
        "  const loCanvas = new OffscreenCanvas(proc.width, proc.height);\n"
        "  const loCtx = loCanvas.getContext('2d');\n"
        "  loCtx.drawImage(lo, 0, 0);\n"
        "  const loData = loCtx.getImageData(0, 0, proc.width, proc.height);\n"
        "  const total = procData.data.length;\n"
        "  for (let i = 0; i < total; i++) {\n"
        "    const encoded = (hiData.data[i] << 8) | loData.data[i];\n"
        "    const diff = encoded - " + str(DIFF_OFFSET) + ";\n"
        "    procData.data[i] = Math.min(255, Math.max(0, procData.data[i] + diff));\n"
        "  }\n"
        "  ctx.putImageData(procData, 0, 0);\n"
        "  canvas.className = '" + css_class + "';\n"
        "  canvas.dataset.filterId = '" + filter_id + "';\n"
        "  img.replaceWith(canvas);\n"
        "}\n"
        "document.querySelectorAll('img." + css_class + "').forEach(applyPoisonMask);\n"
    )


def build_metadata(
    original_path: Path,
    processed_path: Path,
    mask_hi_path: Path,
    mask_lo_path: Path,
    size: Tuple[int, int],
    diff_stats: Dict[str, float],
    diff_min: int,
    diff_max: int,
    filter_id: str,
    css_class: str,
) -> Dict[str, object]:
    """Create a manifest that front-end code can consume."""
    width, height = size
    js_helper = _build_js_snippet(
        filter_id=filter_id,
        css_class=css_class,
        processed_src=processed_path.as_posix(),
        mask_hi_src=mask_hi_path.as_posix(),
        mask_lo_src=mask_lo_path.as_posix(),
    )

    return {
        "original": str(original_path),
        "processed": str(processed_path),
        "mask_hi": str(mask_hi_path),
        "mask_lo": str(mask_lo_path),
        "dimensions": {"width": width, "height": height},
        "diff_stats": diff_stats,
        "diff_range": {"min": diff_min, "max": diff_max},
        "encoding": {
            "type": "int16_split",
            "offset": DIFF_OFFSET,
            "hi_channel_bits": 8,
            "lo_channel_bits": 8,
        },
        "filter_id": filter_id,
        "css_class": css_class,
        "js_snippet": js_helper,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate high-fidelity mask planes that reconstruct an original image "
            "from its processed variant without exposing the original file."
        )
    )
    parser.add_argument("original", type=Path, help="Path to the original reference image.")
    parser.add_argument("processed", type=Path, help="Path to the processed/obfuscated image.")
    parser.add_argument(
        "--mask-hi-output",
        type=Path,
        help="Destination for the high-byte mask (PNG). Defaults to <processed>_mask_hi.png",
    )
    parser.add_argument(
        "--mask-lo-output",
        type=Path,
        help="Destination for the low-byte mask (PNG). Defaults to <processed>_mask_lo.png",
    )
    parser.add_argument(
        "--preview-output",
        type=Path,
        help="Optional path to store a reconstructed preview for sanity checks.",
    )
    parser.add_argument(
        "--metadata-output",
        type=Path,
        help="Optional JSON manifest describing the mask wiring for the web front-end.",
    )
    parser.add_argument(
        "--filter-id",
        default="poison-mask",
        help="Identifier used in DOM hooks and optional styling (default: poison-mask).",
    )
    parser.add_argument(
        "--css-class",
        default="poisoned-image",
        help="CSS class name applied to processed <img> tags (default: poisoned-image).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    original_path: Path = args.original
    processed_path: Path = args.processed

    mask_hi_path = args.mask_hi_output
    if mask_hi_path is None:
        mask_hi_path = processed_path.with_name(f"{processed_path.stem}_mask_hi.png")

    mask_lo_path = args.mask_lo_output
    if mask_lo_path is None:
        mask_lo_path = processed_path.with_name(f"{processed_path.stem}_mask_lo.png")

    original_image = load_image(original_path)
    processed_image = load_image(processed_path)

    # Added by me
    # Ensure the output directory exists and save a copy of the processed image
    # alongside the generated mask files for easy inspection/deployment.
    output_dir = mask_hi_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    processed_copy_path = output_dir / processed_path.name
    # Convert to a JPEG-friendly mode when the copy target is a JPEG.
    suffix = processed_copy_path.suffix.lower()
    to_save = processed_image
    if suffix in (".jpg", ".jpeg"):
        to_save = processed_image.convert("RGB")
    to_save.save(processed_copy_path)
    # Added by me

    mask_result = compute_mask(original_image, processed_image)
    # ensure output dir exists and save packed numeric planes (hi/lo) as compressed .npz
    output_dir = mask_hi_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    hi_arr = np.asarray(mask_result.hi_image, dtype=np.uint8)
    lo_arr = np.asarray(mask_result.lo_image, dtype=np.uint8)
    planes_npz = output_dir / f"{processed_path.stem}_mask_planes.npz"
    np.savez_compressed(planes_npz, hi=hi_arr, lo=lo_arr)
    print(f"wrote {planes_npz}")

    mask_result.hi_image.save(mask_hi_path)
    mask_result.lo_image.save(mask_lo_path)

    if args.preview_output:
        preview_image = reconstruct_preview(processed_image, mask_result.hi_image, mask_result.lo_image)
        preview_image.save(args.preview_output)

    if args.metadata_output:
        metadata = build_metadata(
            original_path=original_path,
            processed_path=processed_path,
            mask_hi_path=mask_hi_path,
            mask_lo_path=mask_lo_path,
            size=mask_result.size,
            diff_stats=mask_result.diff_stats,
            diff_min=mask_result.diff_min,
            diff_max=mask_result.diff_max,
            filter_id=args.filter_id,
            css_class=args.css_class,
        )
        args.metadata_output.write_text(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
