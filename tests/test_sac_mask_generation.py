"""Test SAC mask generation in protection pipeline."""

import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

# Add root to path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from processors.poison_mask.processor import compute_mask
from artorize_gateway.sac_encoder import encode_mask_pair_from_arrays


def test_sac_mask_generation_from_synthetic_images(tmp_path):
    """Test SAC mask generation with synthetic images."""
    # Create synthetic original image
    original = Image.new('RGB', (256, 256), color=(128, 128, 128))
    pixels = np.array(original)
    pixels[50:100, 50:100] = [200, 150, 100]
    pixels[150:200, 150:200] = [100, 200, 150]
    original = Image.fromarray(pixels.astype(np.uint8))

    # Create synthetic processed image (add some perturbations)
    processed_pixels = pixels.copy()
    processed_pixels = processed_pixels.astype(np.int16)
    # Add Gaussian-like noise
    noise = np.random.randint(-20, 20, size=processed_pixels.shape)
    processed_pixels = np.clip(processed_pixels + noise, 0, 255)
    processed = Image.fromarray(processed_pixels.astype(np.uint8))

    # Compute poison mask
    mask = compute_mask(original, processed)

    # Convert mask images to numpy arrays
    hi_arr = np.asarray(mask.hi_image, dtype=np.uint8)
    lo_arr = np.asarray(mask.lo_image, dtype=np.uint8)

    # Encode to SAC format
    width, height = mask.size
    sac_result = encode_mask_pair_from_arrays(hi_arr, lo_arr, width, height)

    # Save SAC file
    sac_path = tmp_path / "test_mask.sac"
    sac_path.write_bytes(sac_result.sac_bytes)

    # Verify SAC encoding
    assert sac_result.width == width
    assert sac_result.height == height
    assert sac_result.length_a == width * height
    assert sac_result.length_b == width * height

    # Verify SAC file exists and has reasonable size
    assert sac_path.exists()
    sac_size_kb = sac_path.stat().st_size / 1024
    print(f"SAC file size: {sac_size_kb:.2f} KB")

    # For 256x256 RGB image: 256*256*3*2 bytes (int16) + 24 byte header
    # Expected: ~393 KB
    assert sac_size_kb > 100, "SAC file unexpectedly small"
    assert sac_size_kb < 1000, "SAC file unexpectedly large"

    # Verify mask diff range
    assert mask.diff_min >= -255
    assert mask.diff_max <= 255

    print(f"Mask diff range: [{mask.diff_min}, {mask.diff_max}]")
    print(f"Mask stats: {mask.diff_stats}")


def test_sac_mask_with_extreme_differences(tmp_path):
    """Test SAC encoding with maximum possible differences."""
    # Create white image
    original = Image.new('RGB', (128, 128), color=(255, 255, 255))

    # Create black image
    processed = Image.new('RGB', (128, 128), color=(0, 0, 0))

    # Compute poison mask (should have maximum differences)
    mask = compute_mask(original, processed)

    # Encode to SAC
    hi_arr = np.asarray(mask.hi_image, dtype=np.uint8)
    lo_arr = np.asarray(mask.lo_image, dtype=np.uint8)
    width, height = mask.size
    sac_result = encode_mask_pair_from_arrays(hi_arr, lo_arr, width, height)

    # Save SAC file
    sac_path = tmp_path / "extreme_mask.sac"
    sac_path.write_bytes(sac_result.sac_bytes)

    # Verify extreme differences are captured
    assert mask.diff_min == -255 or mask.diff_min == 255
    assert mask.diff_max == 255 or mask.diff_max == -255

    # Verify SAC encoding
    assert sac_result.width == width
    assert sac_result.height == height
    assert sac_path.exists()

    print(f"Extreme mask diff range: [{mask.diff_min}, {mask.diff_max}]")
    print(f"SAC file size: {sac_path.stat().st_size / 1024:.2f} KB")


def test_sac_mask_with_no_differences(tmp_path):
    """Test SAC encoding when images are identical."""
    # Create identical images
    original = Image.new('RGB', (64, 64), color=(123, 45, 67))
    processed = original.copy()

    # Compute poison mask (should have zero differences)
    mask = compute_mask(original, processed)

    # Encode to SAC
    hi_arr = np.asarray(mask.hi_image, dtype=np.uint8)
    lo_arr = np.asarray(mask.lo_image, dtype=np.uint8)
    width, height = mask.size
    sac_result = encode_mask_pair_from_arrays(hi_arr, lo_arr, width, height)

    # Save SAC file
    sac_path = tmp_path / "zero_diff_mask.sac"
    sac_path.write_bytes(sac_result.sac_bytes)

    # Verify zero differences
    assert mask.diff_min == 0
    assert mask.diff_max == 0
    assert mask.diff_stats["max_abs_diff"] == 0.0

    # SAC file should still be valid
    assert sac_path.exists()
    print(f"Zero-diff SAC file size: {sac_path.stat().st_size / 1024:.2f} KB")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
