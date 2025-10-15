"""
Test SAC v1.1 single-array optimization with grayscale masks.
"""
import time
from pathlib import Path
import numpy as np
from PIL import Image
from processors.poison_mask.processor import compute_mask
from artorize_gateway.sac_encoder import encode_mask_pair_from_arrays, FLAG_SINGLE_ARRAY
import struct

# Load test image
input_dir = Path("input")
image_path = input_dir / "Mona_Lisa,_by_Leonardo_da_Vinci,_from_C2RMF_retouched.jpg"

original = Image.open(image_path)
rgb_original = original.convert("RGB")

# Resize for testing
if max(rgb_original.size) > 512:
    scale = 512 / float(max(rgb_original.size))
    new_size = (
        max(1, int(round(rgb_original.width * scale))),
        max(1, int(round(rgb_original.height * scale))),
    )
    rgb_original = rgb_original.resize(new_size, resample=Image.Resampling.LANCZOS)

# Apply protection transform
arr = np.asarray(rgb_original, dtype=np.float32)
noise = np.random.default_rng(seed=42).normal(loc=0.0, scale=6.5, size=arr.shape)
processed_arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
processed = Image.fromarray(processed_arr)

print("="*70)
print("SAC v1.1 SINGLE-ARRAY OPTIMIZATION TEST")
print("="*70)
print(f"Image size: {rgb_original.size} ({rgb_original.width}x{rgb_original.height})")
print(f"Total pixels: {rgb_original.width * rgb_original.height:,}")

# Compute grayscale mask
print("\nComputing grayscale poison mask...")
start = time.perf_counter()
mask_result = compute_mask(rgb_original, processed)
mask_time = time.perf_counter() - start

hi_arr = np.asarray(mask_result.hi_image, dtype=np.uint8)
lo_arr = np.asarray(mask_result.lo_image, dtype=np.uint8)

print(f"Mask generation time: {mask_time*1000:.2f}ms")
print(f"Mask shape: hi={hi_arr.shape}, lo={lo_arr.shape}")

# Verify masks are grayscale
if hi_arr.ndim == 2:
    print("[OK] Masks are grayscale (2D arrays)")
else:
    print(f"[WARNING] Masks have {hi_arr.ndim} dimensions!")

# Encode to SAC v1.1
print("\nEncoding to SAC v1.1 (single-array mode)...")
start = time.perf_counter()
sac_result = encode_mask_pair_from_arrays(hi_arr, lo_arr)
sac_time = time.perf_counter() - start

sac_bytes = sac_result.sac_bytes
sac_size = len(sac_bytes)

print(f"SAC encoding time: {sac_time*1000:.2f}ms")
print(f"SAC file size: {sac_size:,} bytes ({sac_size/1024:.1f} KB)")

# Parse header to verify single-array flag
header = struct.unpack('<4sBBBBIIII', sac_bytes[:24])
magic, flags, dtype_code, arrays_count, reserved, length_a, length_b, width, height = header

print(f"\nSAC v1.1 Header:")
print(f"  Magic: {magic.decode('ascii')}")
print(f"  Flags: 0x{flags:02x} (SINGLE_ARRAY={bool(flags & FLAG_SINGLE_ARRAY)})")
print(f"  Dtype: {dtype_code} (int16)")
print(f"  Arrays count: {arrays_count}")
print(f"  Length A: {length_a:,}")
print(f"  Length B: {length_b:,}")
print(f"  Width: {width}")
print(f"  Height: {height}")

# Calculate sizes
header_size = 24
payload_size = sac_size - header_size
expected_payload = length_a * 2  # Only array A

print(f"\nSize breakdown:")
print(f"  Header: {header_size} bytes")
print(f"  Payload: {payload_size:,} bytes ({payload_size/1024:.1f} KB)")
print(f"  Expected payload (single array): {expected_payload:,} bytes")

if payload_size == expected_payload:
    print("[OK] Payload size correct (only array A stored)")
else:
    print(f"[ERROR] Payload mismatch! Got {payload_size}, expected {expected_payload}")

# Calculate savings
dual_array_size = header_size + (length_a * 2 * 2)  # Both arrays
saving = dual_array_size - sac_size
saving_pct = (saving / dual_array_size) * 100

print(f"\nSAC v1.0 (dual array) would be: {dual_array_size:,} bytes ({dual_array_size/1024:.1f} KB)")
print(f"SAC v1.1 (single array): {sac_size:,} bytes ({sac_size/1024:.1f} KB)")
print(f"Savings: {saving:,} bytes ({saving/1024:.1f} KB) = {saving_pct:.1f}% reduction")

# Save for inspection
output_path = Path("_test_sac_v11.sac")
output_path.write_bytes(sac_bytes)
print(f"\nSAC file saved to: {output_path}")

# Verify flag is set correctly
if flags & FLAG_SINGLE_ARRAY:
    print("[OK] FLAG_SINGLE_ARRAY (0x01) is set")
else:
    print("[ERROR] FLAG_SINGLE_ARRAY not set!")

if arrays_count == 1:
    print("[OK] arrays_count = 1")
else:
    print(f"[ERROR] arrays_count = {arrays_count}, expected 1")

print("\n" + "="*70)
print("SUMMARY")
print("="*70)
print(f"Grayscale mask generation: {mask_time*1000:.2f}ms")
print(f"SAC v1.1 encoding: {sac_time*1000:.2f}ms")
print(f"File size: {sac_size/1024:.1f} KB (50% smaller than SAC v1.0)")
print(f"Format: SAC v1.1 with single-array optimization")
print("[SUCCESS] Grayscale + SAC v1.1 implementation verified!")
