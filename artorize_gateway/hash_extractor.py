"""
Hash extraction module for image similarity search.

Provides unified interface for computing multiple hash types from images
using existing processors and the imagehash library.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from PIL import Image

from artorize_runner.utils import pil_image_from_path, ensure_rgb


def _hash_to_hex(hash_obj: Any) -> str:
    """Convert imagehash hash object to hex string with 0x prefix."""
    if hash_obj is None:
        return "0x0"
    # imagehash objects have __str__ that returns hex without prefix
    hex_str = str(hash_obj)
    if not hex_str.startswith("0x"):
        hex_str = "0x" + hex_str
    return hex_str


def _compute_imagehash_suite(im: Image.Image, hash_types: Optional[Sequence[str]] = None) -> Dict[str, str]:
    """
    Compute all imagehash library hashes.

    Args:
        im: PIL Image object
        hash_types: Optional list of hash types to compute. If None, computes all.
                   Supported: phash, ahash, dhash, whash, colorhash

    Returns:
        Dictionary mapping hash names to hex string values
    """
    try:
        import imagehash
    except ImportError:
        return {}

    all_types = ["phash", "ahash", "dhash", "whash", "colorhash"]
    if hash_types:
        # Filter to only requested types
        types_lower = {ht.lower() for ht in hash_types}
        compute_types = [ht for ht in all_types if ht in types_lower]
    else:
        compute_types = all_types

    hashes: Dict[str, str] = {}

    if "ahash" in compute_types:
        try:
            hashes["average_hash"] = _hash_to_hex(imagehash.average_hash(im))
        except Exception:
            pass

    if "phash" in compute_types:
        try:
            hashes["perceptual_hash"] = _hash_to_hex(imagehash.phash(im))
        except Exception:
            pass

    if "dhash" in compute_types:
        try:
            hashes["difference_hash"] = _hash_to_hex(imagehash.dhash(im))
        except Exception:
            pass

    if "whash" in compute_types:
        try:
            hashes["wavelet_hash"] = _hash_to_hex(imagehash.whash(im))
        except Exception:
            pass

    if "colorhash" in compute_types:
        try:
            # colorhash returns a different type, convert to string
            color_hash = imagehash.colorhash(im)
            hashes["color_hash"] = _hash_to_hex(color_hash)
        except Exception:
            pass

    return hashes


def _compute_blockhash(im: Image.Image, hash_types: Optional[Sequence[str]] = None) -> Dict[str, str]:
    """
    Compute blockhash hashes (8-bit and 16-bit).

    Args:
        im: PIL Image object
        hash_types: Optional list of hash types. Supported: blockhash, blockhash8, blockhash16

    Returns:
        Dictionary mapping hash names to hex string values
    """
    try:
        import blockhash as bh
    except ImportError:
        return {}

    # Check if blockhash types are requested
    if hash_types is not None:
        types_lower = {ht.lower() for ht in hash_types}
        if not any(t in types_lower for t in ["blockhash", "blockhash8", "blockhash16"]):
            return {}

    # Ensure RGB mode for blockhash
    im_rgb = ensure_rgb(im)
    if im_rgb is None:
        return {}

    hashes: Dict[str, str] = {}

    try:
        h8 = bh.blockhash(im_rgb, 8)
        hashes["blockhash8"] = f"0x{h8}"
    except Exception:
        pass

    try:
        h16 = bh.blockhash(im_rgb, 16)
        hashes["blockhash16"] = f"0x{h16}"
    except Exception:
        pass

    return hashes


def extract_hashes(
    image_path: str | Path,
    hash_types: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """
    Extract multiple hash types from an image file.

    Args:
        image_path: Path to image file
        hash_types: Optional list of hash types to compute.
                   If None or "all", computes all available hashes.
                   Supported types:
                   - phash (perceptual hash)
                   - ahash (average hash)
                   - dhash (difference hash)
                   - whash (wavelet hash)
                   - colorhash
                   - blockhash, blockhash8, blockhash16

    Returns:
        Dictionary with keys:
        - hashes: Dict mapping hash type names to hex string values
        - metadata: Dict with width, height, format, mode
        - error: Optional error message if extraction failed
    """
    # Load image
    im = pil_image_from_path(str(image_path))
    if im is None:
        return {
            "hashes": {},
            "metadata": {},
            "error": "Failed to open image file"
        }

    # Extract metadata
    metadata = {
        "width": im.size[0] if im.size else 0,
        "height": im.size[1] if im.size else 0,
        "format": getattr(im, "format", None),
        "mode": getattr(im, "mode", None),
    }

    # Normalize hash_types
    normalized_types: Optional[List[str]] = None
    if hash_types:
        types_list = list(hash_types)
        if "all" in [t.lower() for t in types_list]:
            normalized_types = None  # Compute all
        else:
            normalized_types = types_list

    # Compute hashes
    hashes: Dict[str, str] = {}

    # imagehash suite
    imagehash_results = _compute_imagehash_suite(im, normalized_types)
    hashes.update(imagehash_results)

    # blockhash
    blockhash_results = _compute_blockhash(im, normalized_types)
    hashes.update(blockhash_results)

    return {
        "hashes": hashes,
        "metadata": metadata,
        "error": None if hashes else "No hashes could be computed"
    }
