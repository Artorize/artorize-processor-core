"""
SAC v1 - Simple Array Container encoder for CDN delivery.
Fast, efficient encoding of dual int16 arrays for mask transmission.
"""
from __future__ import annotations

import struct
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image

SAC_MAGIC = b"SAC1"
DTYPE_INT16 = 1
DIFF_OFFSET = 32768  # center of uint16 range for signed diff packing


@dataclass
class SACEncodeResult:
    """Result of SAC encoding operation."""
    sac_bytes: bytes
    width: int
    height: int
    length_a: int
    length_b: int


def to_c_contiguous_i16(x: np.ndarray) -> np.ndarray:
    """Convert array to C-contiguous int16."""
    x = np.asarray(x, dtype=np.int16)
    if not x.flags['C_CONTIGUOUS']:
        x = np.ascontiguousarray(x)
    return x


def build_sac(a: np.ndarray, b: np.ndarray, width: int = 0, height: int = 0) -> bytes:
    """
    Build SAC v1 binary from two int16 arrays.

    Args:
        a: First int16 array (will be flattened)
        b: Second int16 array (will be flattened)
        width: Optional image width for validation
        height: Optional image height for validation

    Returns:
        Binary SAC v1 data ready for CDN upload

    Raises:
        AssertionError: If width*height validation fails
    """
    a = to_c_contiguous_i16(a)
    b = to_c_contiguous_i16(b)
    length_a = int(a.size)
    length_b = int(b.size)

    if width and height:
        assert length_a == width * height, f"A length {length_a} != width*height {width*height}"
        assert length_b == width * height, f"B length {length_b} != width*height {width*height}"

    header = struct.pack(
        '<4sBBBBIIII',
        SAC_MAGIC,      # 4s
        0,              # flags
        DTYPE_INT16,    # dtype_code
        2,              # arrays_count
        0,              # reserved
        length_a,       # uint32
        length_b,       # uint32
        width,          # uint32
        height          # uint32
    )
    return header + a.tobytes(order='C') + b.tobytes(order='C')


def encode_mask_pair_from_images(
    mask_hi_path: Path,
    mask_lo_path: Path,
) -> SACEncodeResult:
    """
    Encode mask hi/lo image pair into SAC format.

    Args:
        mask_hi_path: Path to high-byte mask image
        mask_lo_path: Path to low-byte mask image

    Returns:
        SACEncodeResult with encoded binary data

    Raises:
        ValueError: If images have mismatched dimensions
    """
    # Load mask images
    hi_img = Image.open(mask_hi_path)
    lo_img = Image.open(mask_lo_path)

    if hi_img.size != lo_img.size:
        raise ValueError(
            f"Mask dimension mismatch: hi={hi_img.size}, lo={lo_img.size}"
        )

    width, height = hi_img.size

    # Convert to arrays
    hi_arr = np.asarray(hi_img, dtype=np.uint8)
    lo_arr = np.asarray(lo_img, dtype=np.uint8)

    # Decode back to signed int16
    hi_u16 = hi_arr.astype(np.uint16)
    lo_u16 = lo_arr.astype(np.uint16)
    encoded = (hi_u16 << 8) | lo_u16
    diff = (encoded.astype(np.int32) - DIFF_OFFSET).astype(np.int16)

    # For SAC, we can store the diff directly as int16
    # Or split back into components if needed - let's store as two planes
    # matching the original encoding scheme
    a_flat = diff[:, :, 0].ravel() if diff.ndim == 3 else diff.ravel()
    b_flat = diff[:, :, 1].ravel() if diff.ndim == 3 and diff.shape[2] > 1 else diff.ravel()

    # Build SAC
    sac_bytes = build_sac(a_flat, b_flat, width, height)

    return SACEncodeResult(
        sac_bytes=sac_bytes,
        width=width,
        height=height,
        length_a=len(a_flat),
        length_b=len(b_flat),
    )


def encode_mask_pair_from_arrays(
    hi_array: np.ndarray,
    lo_array: np.ndarray,
    width: Optional[int] = None,
    height: Optional[int] = None,
) -> SACEncodeResult:
    """
    Encode mask hi/lo arrays directly into SAC format.

    Args:
        hi_array: High-byte mask array (uint8)
        lo_array: Low-byte mask array (uint8)
        width: Optional width for validation
        height: Optional height for validation

    Returns:
        SACEncodeResult with encoded binary data

    Raises:
        ValueError: If arrays have mismatched shapes
    """
    if hi_array.shape != lo_array.shape:
        raise ValueError(
            f"Array shape mismatch: hi={hi_array.shape}, lo={lo_array.shape}"
        )

    # Infer dimensions if not provided
    if width is None or height is None:
        if hi_array.ndim >= 2:
            height, width = hi_array.shape[:2]
        else:
            width = height = 0

    # Decode to signed int16 differences
    hi_u16 = hi_array.astype(np.uint16)
    lo_u16 = lo_array.astype(np.uint16)
    encoded = (hi_u16 << 8) | lo_u16
    diff = (encoded.astype(np.int32) - DIFF_OFFSET).astype(np.int16)

    # Flatten and split by channel if multi-channel
    if diff.ndim == 3 and diff.shape[2] > 1:
        # Multi-channel: use first two channels
        a_flat = diff[:, :, 0].ravel()
        b_flat = diff[:, :, 1].ravel() if diff.shape[2] > 1 else diff[:, :, 0].ravel()
    else:
        # Single channel: duplicate
        a_flat = diff.ravel()
        b_flat = diff.ravel()

    sac_bytes = build_sac(a_flat, b_flat, width, height)

    return SACEncodeResult(
        sac_bytes=sac_bytes,
        width=width or 0,
        height=height or 0,
        length_a=len(a_flat),
        length_b=len(b_flat),
    )


def encode_mask_pair_from_npz(npz_path: Path) -> SACEncodeResult:
    """
    Encode mask from .npz file containing 'hi' and 'lo' arrays.

    Args:
        npz_path: Path to .npz file with hi/lo arrays

    Returns:
        SACEncodeResult with encoded binary data

    Raises:
        KeyError: If npz doesn't contain 'hi' and 'lo' keys
    """
    data = np.load(npz_path)
    hi_arr = data['hi']
    lo_arr = data['lo']

    return encode_mask_pair_from_arrays(hi_arr, lo_arr)


def encode_single_array(
    array: np.ndarray,
    width: Optional[int] = None,
    height: Optional[int] = None,
) -> SACEncodeResult:
    """
    Encode a single array into SAC format by storing it in both slots.

    This is a compatibility function for backends that expect separate hi/lo SAC files.
    Since SAC v1 requires two arrays, we store the same array in both slots.

    Args:
        array: uint8 mask array
        width: Optional width for validation
        height: Optional height for validation

    Returns:
        SACEncodeResult with encoded binary data
    """
    # Infer dimensions if not provided
    if width is None or height is None:
        if array.ndim >= 2:
            height, width = array.shape[:2]
        else:
            width = height = 0

    # Convert uint8 to int16 for SAC encoding
    array_int16 = array.astype(np.int16)

    # Flatten
    if array_int16.ndim > 1:
        a_flat = array_int16.ravel()
    else:
        a_flat = array_int16

    # Store the same data in both slots (SAC requires two arrays)
    sac_bytes = build_sac(a_flat, a_flat, width, height)

    return SACEncodeResult(
        sac_bytes=sac_bytes,
        width=width or 0,
        height=height or 0,
        length_a=len(a_flat),
        length_b=len(a_flat),
    )


def _encode_single_mask_job(
    job_id: str,
    mask_hi_path: Path,
    mask_lo_path: Path,
) -> Tuple[str, SACEncodeResult]:
    """Worker function for parallel encoding."""
    result = encode_mask_pair_from_images(mask_hi_path, mask_lo_path)
    return job_id, result


def encode_masks_parallel(
    mask_pairs: List[Tuple[str, Path, Path]],
    max_workers: Optional[int] = None,
) -> dict[str, SACEncodeResult]:
    """
    Encode multiple mask pairs in parallel.

    Args:
        mask_pairs: List of (job_id, mask_hi_path, mask_lo_path) tuples
        max_workers: Max parallel workers (defaults to CPU count)

    Returns:
        Dict mapping job_id to SACEncodeResult

    Raises:
        Exception: If any encoding fails
    """
    results = {}

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_encode_single_mask_job, job_id, hi_path, lo_path): job_id
            for job_id, hi_path, lo_path in mask_pairs
        }

        for future in as_completed(futures):
            job_id = futures[future]
            try:
                returned_job_id, result = future.result()
                results[returned_job_id] = result
            except Exception as exc:
                raise RuntimeError(f"Encoding failed for job {job_id}: {exc}") from exc

    return results