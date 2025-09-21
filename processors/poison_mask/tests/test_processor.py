import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from processors.poison_mask.processor import compute_mask, reconstruct_preview


def test_reconstruct_matches_original_exactly():
    rng = np.random.default_rng(1234)
    original_arr = rng.integers(0, 256, size=(32, 32, 4), dtype=np.uint8)
    processed_arr = rng.integers(0, 256, size=(32, 32, 4), dtype=np.uint8)

    original = Image.fromarray(original_arr)
    processed = Image.fromarray(processed_arr)

    mask_result = compute_mask(original, processed)
    reconstructed = reconstruct_preview(processed, mask_result.hi_image, mask_result.lo_image)

    reconstructed_arr = np.asarray(reconstructed, dtype=np.uint8)
    assert np.array_equal(reconstructed_arr, original_arr), "Reconstruction must be lossless"


def test_diff_encoding_round_trip():
    original_arr = np.array([[[0, 255, 10, 200]]], dtype=np.uint8)
    processed_arr = np.array([[[255, 0, 200, 10]]], dtype=np.uint8)

    original = Image.fromarray(original_arr)
    processed = Image.fromarray(processed_arr)

    mask_result = compute_mask(original, processed)

    hi = np.asarray(mask_result.hi_image)
    lo = np.asarray(mask_result.lo_image)
    encoded = (hi.astype(np.uint16) << 8) | lo.astype(np.uint16)
    decoded_diff = encoded.astype(np.int32) - 32768

    expected_diff = original_arr.astype(np.int16) - processed_arr.astype(np.int16)
    assert np.array_equal(decoded_diff.astype(np.int16), expected_diff)
