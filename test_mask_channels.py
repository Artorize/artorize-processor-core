"""
Test script to analyze whether poison masks are truly RGB or grayscale.
"""
from pathlib import Path
import numpy as np
from PIL import Image
from processors.poison_mask.processor import compute_mask

# Load test image
input_dir = Path("input")
image_path = input_dir / "Mona_Lisa,_by_Leonardo_da_Vinci,_from_C2RMF_retouched.jpg"

# Load and convert to RGB
original = Image.open(image_path)
rgb_original = original.convert("RGB")

# Resize to reasonable size for testing
if max(rgb_original.size) > 512:
    scale = 512 / float(max(rgb_original.size))
    new_size = (
        max(1, int(round(rgb_original.width * scale))),
        max(1, int(round(rgb_original.height * scale))),
    )
    rgb_original = rgb_original.resize(new_size, resample=Image.Resampling.LANCZOS)

# Apply a simple transform to create a "processed" version
arr = np.asarray(rgb_original, dtype=np.float32)
noise = np.random.default_rng(seed=42).normal(loc=0.0, scale=6.5, size=arr.shape)
processed_arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
processed = Image.fromarray(processed_arr)

# Compute mask
print("Computing mask...")
mask_result = compute_mask(rgb_original, processed)

# Analyze the mask images
hi_arr = np.asarray(mask_result.hi_image, dtype=np.uint8)
lo_arr = np.asarray(mask_result.lo_image, dtype=np.uint8)

print(f"\nMask hi shape: {hi_arr.shape}")
print(f"Mask lo shape: {lo_arr.shape}")

# Check if RGB or grayscale
if hi_arr.ndim == 3:
    print(f"\nhi_arr has {hi_arr.shape[2]} channels")
    # Check if all channels are identical
    if hi_arr.shape[2] >= 3:
        r_channel = hi_arr[:, :, 0]
        g_channel = hi_arr[:, :, 1]
        b_channel = hi_arr[:, :, 2]

        rg_identical = np.array_equal(r_channel, g_channel)
        rb_identical = np.array_equal(r_channel, b_channel)

        print(f"R == G: {rg_identical}")
        print(f"R == B: {rb_identical}")

        if rg_identical and rb_identical:
            print("\n[OK] HI mask is grayscale (all channels identical)")
        else:
            print("\n[IMPORTANT] HI mask is truly RGB (channels differ)")
            print(f"  R channel stats: min={r_channel.min()}, max={r_channel.max()}, mean={r_channel.mean():.2f}")
            print(f"  G channel stats: min={g_channel.min()}, max={g_channel.max()}, mean={g_channel.mean():.2f}")
            print(f"  B channel stats: min={b_channel.min()}, max={b_channel.max()}, mean={b_channel.mean():.2f}")

            # Show sample differences
            diff_rg = np.abs(r_channel.astype(np.int16) - g_channel.astype(np.int16))
            diff_rb = np.abs(r_channel.astype(np.int16) - b_channel.astype(np.int16))
            print(f"  |R-G| stats: min={diff_rg.min()}, max={diff_rg.max()}, mean={diff_rg.mean():.2f}")
            print(f"  |R-B| stats: min={diff_rb.min()}, max={diff_rb.max()}, mean={diff_rb.mean():.2f}")
else:
    print(f"\n[OK] hi_arr is already grayscale ({hi_arr.ndim}D array)")

if lo_arr.ndim == 3:
    print(f"\nlo_arr has {lo_arr.shape[2]} channels")
    # Check if all channels are identical
    if lo_arr.shape[2] >= 3:
        r_channel = lo_arr[:, :, 0]
        g_channel = lo_arr[:, :, 1]
        b_channel = lo_arr[:, :, 2]

        rg_identical = np.array_equal(r_channel, g_channel)
        rb_identical = np.array_equal(r_channel, b_channel)

        print(f"R == G: {rg_identical}")
        print(f"R == B: {rb_identical}")

        if rg_identical and rb_identical:
            print("\n[OK] LO mask is grayscale (all channels identical)")
        else:
            print("\n[IMPORTANT] LO mask is truly RGB (channels differ)")
            print(f"  R channel stats: min={r_channel.min()}, max={r_channel.max()}, mean={r_channel.mean():.2f}")
            print(f"  G channel stats: min={g_channel.min()}, max={g_channel.max()}, mean={g_channel.mean():.2f}")
            print(f"  B channel stats: min={b_channel.min()}, max={b_channel.max()}, mean={b_channel.mean():.2f}")

            # Show sample differences
            diff_rg = np.abs(r_channel.astype(np.int16) - g_channel.astype(np.int16))
            diff_rb = np.abs(r_channel.astype(np.int16) - b_channel.astype(np.int16))
            print(f"  |R-G| stats: min={diff_rg.min()}, max={diff_rg.max()}, mean={diff_rg.mean():.2f}")
            print(f"  |R-B| stats: min={diff_rb.min()}, max={diff_rb.max()}, mean={diff_rb.mean():.2f}")
else:
    print(f"\n[OK] lo_arr is already grayscale ({lo_arr.ndim}D array)")

# Check the mode of the PIL images
print(f"\nPIL image modes:")
print(f"  hi_image.mode: {mask_result.hi_image.mode}")
print(f"  lo_image.mode: {mask_result.lo_image.mode}")

print("\n" + "="*60)
print("CONCLUSION:")
if hi_arr.ndim == 2 or (hi_arr.ndim == 3 and np.array_equal(hi_arr[:,:,0], hi_arr[:,:,1]) and np.array_equal(hi_arr[:,:,0], hi_arr[:,:,2])):
    print("[OK] Masks are effectively GRAYSCALE")
    print("  - We can safely extract just one channel for SAC encoding")
    print("  - OR convert masks to 'L' mode when creating PIL images")
else:
    print("[CRITICAL] Masks contain different RGB channel data")
    print("  - Need to design multi-channel SAC protocol")
    print("  - OR change mask generation to produce grayscale")
    print("  - Current fix (extracting first channel only) LOSES DATA")
