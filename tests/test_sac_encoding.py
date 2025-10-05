"""
Tests for SAC encoding utility and endpoints.
"""
from __future__ import annotations

import struct
import tempfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from artorize_gateway.sac_encoder import (
    DIFF_OFFSET,
    SAC_MAGIC,
    build_sac,
    encode_mask_pair_from_arrays,
    encode_mask_pair_from_images,
    encode_mask_pair_from_npz,
    encode_masks_parallel,
    to_c_contiguous_i16,
)


class TestSACEncoding:
    """Test SAC binary encoding functions."""

    def test_to_c_contiguous_i16(self):
        """Test array conversion to C-contiguous int16."""
        # Already contiguous
        arr = np.array([1, 2, 3], dtype=np.int16)
        result = to_c_contiguous_i16(arr)
        assert result.dtype == np.int16
        assert result.flags['C_CONTIGUOUS']
        np.testing.assert_array_equal(result, arr)

        # Non-contiguous
        arr_nc = np.array([[1, 2], [3, 4]], dtype=np.float32).T
        result = to_c_contiguous_i16(arr_nc)
        assert result.dtype == np.int16
        assert result.flags['C_CONTIGUOUS']

    def test_build_sac_basic(self):
        """Test basic SAC binary construction."""
        a = np.array([1, 2, 3], dtype=np.int16)
        b = np.array([4, 5, 6], dtype=np.int16)

        sac_bytes = build_sac(a, b, width=0, height=0)

        # Check header size (24 bytes) + payload
        expected_size = 24 + (3 * 2) + (3 * 2)
        assert len(sac_bytes) == expected_size

        # Parse header
        magic = sac_bytes[:4]
        assert magic == SAC_MAGIC

        # Unpack header
        header = struct.unpack('<4sBBBBIIII', sac_bytes[:24])
        assert header[0] == SAC_MAGIC
        assert header[1] == 0  # flags
        assert header[2] == 1  # dtype_code (int16)
        assert header[3] == 2  # arrays_count
        assert header[4] == 0  # reserved
        assert header[5] == 3  # length_a
        assert header[6] == 3  # length_b
        assert header[7] == 0  # width
        assert header[8] == 0  # height

    def test_build_sac_with_dimensions(self):
        """Test SAC with width/height validation."""
        a = np.arange(6, dtype=np.int16)
        b = np.arange(6, dtype=np.int16)

        # Valid dimensions
        sac_bytes = build_sac(a, b, width=3, height=2)
        header = struct.unpack('<4sBBBBIIII', sac_bytes[:24])
        assert header[7] == 3  # width
        assert header[8] == 2  # height

        # Invalid dimensions should raise
        with pytest.raises(AssertionError):
            build_sac(a, b, width=4, height=2)

    def test_build_sac_payload_integrity(self):
        """Test that payload is correctly encoded."""
        a = np.array([100, -200, 300], dtype=np.int16)
        b = np.array([-400, 500, -600], dtype=np.int16)

        sac_bytes = build_sac(a, b)

        # Extract payloads
        payload_a = np.frombuffer(sac_bytes[24:24+6], dtype=np.int16)
        payload_b = np.frombuffer(sac_bytes[24+6:24+12], dtype=np.int16)

        np.testing.assert_array_equal(payload_a, a)
        np.testing.assert_array_equal(payload_b, b)

    def test_encode_mask_pair_from_arrays(self):
        """Test encoding from NumPy arrays."""
        # Create mock hi/lo arrays (uint8)
        hi = np.random.randint(0, 256, (10, 10, 4), dtype=np.uint8)
        lo = np.random.randint(0, 256, (10, 10, 4), dtype=np.uint8)

        result = encode_mask_pair_from_arrays(hi, lo)

        assert result.width == 10
        assert result.height == 10
        assert len(result.sac_bytes) > 24
        assert result.sac_bytes[:4] == SAC_MAGIC

    def test_encode_mask_pair_from_arrays_mismatch(self):
        """Test that mismatched array shapes raise error."""
        hi = np.zeros((10, 10), dtype=np.uint8)
        lo = np.zeros((5, 5), dtype=np.uint8)

        with pytest.raises(ValueError, match="shape mismatch"):
            encode_mask_pair_from_arrays(hi, lo)

    def test_encode_mask_pair_from_images(self):
        """Test encoding from image files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            # Create test images
            hi_img = Image.fromarray(
                np.random.randint(0, 256, (64, 64, 4), dtype=np.uint8),
                mode='RGBA'
            )
            lo_img = Image.fromarray(
                np.random.randint(0, 256, (64, 64, 4), dtype=np.uint8),
                mode='RGBA'
            )

            hi_path = tmp_path / "hi.png"
            lo_path = tmp_path / "lo.png"
            hi_img.save(hi_path)
            lo_img.save(lo_path)

            result = encode_mask_pair_from_images(hi_path, lo_path)

            assert result.width == 64
            assert result.height == 64
            assert len(result.sac_bytes) > 24

    def test_encode_mask_pair_from_images_size_mismatch(self):
        """Test that mismatched image sizes raise error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            hi_img = Image.fromarray(
                np.zeros((64, 64, 4), dtype=np.uint8), mode='RGBA'
            )
            lo_img = Image.fromarray(
                np.zeros((32, 32, 4), dtype=np.uint8), mode='RGBA'
            )

            hi_path = tmp_path / "hi.png"
            lo_path = tmp_path / "lo.png"
            hi_img.save(hi_path)
            lo_img.save(lo_path)

            with pytest.raises(ValueError, match="dimension mismatch"):
                encode_mask_pair_from_images(hi_path, lo_path)

    def test_encode_mask_pair_from_npz(self):
        """Test encoding from NPZ file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            # Create NPZ
            hi_arr = np.random.randint(0, 256, (32, 32, 4), dtype=np.uint8)
            lo_arr = np.random.randint(0, 256, (32, 32, 4), dtype=np.uint8)

            npz_path = tmp_path / "mask.npz"
            np.savez_compressed(npz_path, hi=hi_arr, lo=lo_arr)

            result = encode_mask_pair_from_npz(npz_path)

            assert len(result.sac_bytes) > 24
            assert result.sac_bytes[:4] == SAC_MAGIC

    def test_encode_mask_pair_from_npz_missing_keys(self):
        """Test that NPZ without hi/lo keys raises error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            # Create NPZ with wrong keys
            arr = np.zeros((10, 10), dtype=np.uint8)
            npz_path = tmp_path / "bad.npz"
            np.savez_compressed(npz_path, wrong=arr)

            with pytest.raises(KeyError):
                encode_mask_pair_from_npz(npz_path)

    def test_encode_masks_parallel(self):
        """Test parallel batch encoding."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            # Create multiple mask pairs
            mask_pairs = []
            for i in range(5):
                hi_img = Image.fromarray(
                    np.random.randint(0, 256, (32, 32, 4), dtype=np.uint8),
                    mode='RGBA'
                )
                lo_img = Image.fromarray(
                    np.random.randint(0, 256, (32, 32, 4), dtype=np.uint8),
                    mode='RGBA'
                )

                hi_path = tmp_path / f"hi_{i}.png"
                lo_path = tmp_path / f"lo_{i}.png"
                hi_img.save(hi_path)
                lo_img.save(lo_path)

                mask_pairs.append((f"job_{i}", hi_path, lo_path))

            results = encode_masks_parallel(mask_pairs, max_workers=2)

            assert len(results) == 5
            for job_id in [f"job_{i}" for i in range(5)]:
                assert job_id in results
                assert len(results[job_id].sac_bytes) > 24

    def test_sac_round_trip(self):
        """Test that SAC encoding preserves data integrity."""
        # Create original data
        original_a = np.array([1, -1, 100, -100, 32767, -32768], dtype=np.int16)
        original_b = np.array([0, 5, -5, 1000, -1000, 12345], dtype=np.int16)

        # Encode
        sac_bytes = build_sac(original_a, original_b)

        # Decode
        header = struct.unpack('<4sBBBBIIII', sac_bytes[:24])
        length_a = header[5]
        length_b = header[6]

        decoded_a = np.frombuffer(
            sac_bytes[24:24 + length_a * 2],
            dtype=np.int16
        )
        decoded_b = np.frombuffer(
            sac_bytes[24 + length_a * 2:24 + length_a * 2 + length_b * 2],
            dtype=np.int16
        )

        np.testing.assert_array_equal(decoded_a, original_a)
        np.testing.assert_array_equal(decoded_b, original_b)

    def test_sac_header_validation(self):
        """Test SAC header field constraints."""
        a = np.array([1, 2, 3], dtype=np.int16)
        b = np.array([4, 5, 6], dtype=np.int16)

        sac_bytes = build_sac(a, b, width=3, height=1)
        header_data = struct.unpack('<4sBBBBIIII', sac_bytes[:24])

        # Validate header fields
        assert header_data[0] == b'SAC1'      # magic
        assert header_data[1] == 0            # flags
        assert header_data[2] == 1            # dtype_code
        assert header_data[3] == 2            # arrays_count
        assert header_data[4] == 0            # reserved
        assert header_data[5] == 3            # length_a
        assert header_data[6] == 3            # length_b
        assert header_data[7] == 3            # width
        assert header_data[8] == 1            # height

    def test_large_array_encoding(self):
        """Test encoding of larger realistic arrays."""
        # 512x512 image simulation (w*h total elements per array)
        width, height = 512, 512
        size = width * height
        a = np.random.randint(-32768, 32767, size, dtype=np.int16)
        b = np.random.randint(-32768, 32767, size, dtype=np.int16)

        sac_bytes = build_sac(a, b, width=width, height=height)

        # Check size: header (24) + array_a (size*2) + array_b (size*2)
        expected_size = 24 + (size * 2) + (size * 2)
        assert len(sac_bytes) == expected_size

        # Verify header
        header = struct.unpack('<4sBBBBIIII', sac_bytes[:24])
        assert header[5] == size   # length_a
        assert header[6] == size   # length_b
        assert header[7] == width  # width
        assert header[8] == height # height


class TestSACIntegration:
    """Integration tests for SAC encoding workflow."""

    def test_poison_mask_to_sac_workflow(self):
        """Test full workflow from poison mask generation to SAC encoding."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            # Simulate poison mask processor output
            # Create "original" and "processed" images
            original = Image.fromarray(
                np.random.randint(0, 256, (128, 128, 4), dtype=np.uint8),
                mode='RGBA'
            )
            processed = Image.fromarray(
                np.random.randint(0, 256, (128, 128, 4), dtype=np.uint8),
                mode='RGBA'
            )

            # Compute difference and encode
            orig_arr = np.asarray(original, dtype=np.int16)
            proc_arr = np.asarray(processed, dtype=np.int16)
            diff = orig_arr - proc_arr

            # Encode to hi/lo like poison mask processor
            diff_int = diff.astype(np.int32)
            encoded = diff_int + DIFF_OFFSET
            encoded = encoded.astype(np.uint16)
            hi = (encoded >> 8).astype(np.uint8)
            lo = (encoded & 0xFF).astype(np.uint8)

            # Save as images
            hi_img = Image.fromarray(hi, mode='RGBA')
            lo_img = Image.fromarray(lo, mode='RGBA')

            hi_path = tmp_path / "mask_hi.png"
            lo_path = tmp_path / "mask_lo.png"
            hi_img.save(hi_path)
            lo_img.save(lo_path)

            # Encode to SAC
            result = encode_mask_pair_from_images(hi_path, lo_path)

            assert result.width == 128
            assert result.height == 128
            assert len(result.sac_bytes) > 24

            # Save SAC
            sac_path = tmp_path / "output.sac"
            sac_path.write_bytes(result.sac_bytes)

            assert sac_path.exists()
            assert sac_path.stat().st_size == len(result.sac_bytes)
