"""
Compare RGB vs Grayscale mask encoding:
- Reconstruction quality (PSNR, MSE)
- File sizes (SAC, PNG)
- Encoding/decoding performance
"""
import time
from pathlib import Path
import numpy as np
from PIL import Image
from processors.poison_mask.processor import compute_mask, DIFF_OFFSET
from artorize_gateway.sac_encoder import build_sac

def psnr(img1: np.ndarray, img2: np.ndarray) -> float:
    """Calculate Peak Signal-to-Noise Ratio."""
    mse = np.mean((img1.astype(np.float64) - img2.astype(np.float64)) ** 2)
    if mse == 0:
        return float('inf')
    return 20 * np.log10(255.0 / np.sqrt(mse))

def reconstruct_from_rgb_mask(processed: np.ndarray, hi_arr: np.ndarray, lo_arr: np.ndarray) -> np.ndarray:
    """Reconstruct using full RGB mask data."""
    hi_u16 = hi_arr.astype(np.uint16)
    lo_u16 = lo_arr.astype(np.uint16)
    encoded = (hi_u16 << 8) | lo_u16
    diff = (encoded.astype(np.int32) - DIFF_OFFSET).astype(np.int16)
    reconstructed = processed.astype(np.int32) + diff
    return np.clip(reconstructed, 0, 255).astype(np.uint8)

def reconstruct_from_grayscale_mask(processed: np.ndarray, hi_gray: np.ndarray, lo_gray: np.ndarray) -> np.ndarray:
    """Reconstruct using grayscale mask (same diff applied to all channels)."""
    hi_u16 = hi_gray.astype(np.uint16)
    lo_u16 = lo_gray.astype(np.uint16)
    encoded = (hi_u16 << 8) | lo_u16
    diff = (encoded.astype(np.int32) - DIFF_OFFSET).astype(np.int16)

    # Apply same diff to all RGB channels
    reconstructed = processed.astype(np.int32) + diff[:, :, np.newaxis]
    return np.clip(reconstructed, 0, 255).astype(np.uint8)

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
print("RGB vs GRAYSCALE MASK COMPARISON")
print("="*70)
print(f"Image size: {rgb_original.size} ({rgb_original.width}x{rgb_original.height})")
print(f"Total pixels: {rgb_original.width * rgb_original.height:,}")

# ============================================================================
# 1. RGB MASKS (Current behavior)
# ============================================================================
print("\n" + "="*70)
print("1. RGB MASKS (Lossless per-channel reconstruction)")
print("="*70)

start = time.perf_counter()
mask_result = compute_mask(rgb_original, processed)
rgb_mask_time = time.perf_counter() - start

hi_arr = np.asarray(mask_result.hi_image, dtype=np.uint8)
lo_arr = np.asarray(mask_result.lo_image, dtype=np.uint8)

print(f"Mask generation time: {rgb_mask_time*1000:.2f}ms")
print(f"Mask shape: hi={hi_arr.shape}, lo={lo_arr.shape}")

# Encode to SAC (3 separate files for R, G, B)
start = time.perf_counter()
r_hi, r_lo = hi_arr[:, :, 0], lo_arr[:, :, 0]
g_hi, g_lo = hi_arr[:, :, 1], lo_arr[:, :, 1]
b_hi, b_lo = hi_arr[:, :, 2], lo_arr[:, :, 2]

h, w = hi_arr.shape[:2]
sac_r = build_sac(r_hi.ravel().astype(np.int16), r_lo.ravel().astype(np.int16), w, h)
sac_g = build_sac(g_hi.ravel().astype(np.int16), g_lo.ravel().astype(np.int16), w, h)
sac_b = build_sac(b_hi.ravel().astype(np.int16), b_lo.ravel().astype(np.int16), w, h)
rgb_sac_time = time.perf_counter() - start

rgb_sac_size = len(sac_r) + len(sac_g) + len(sac_b)

print(f"SAC encoding time: {rgb_sac_time*1000:.2f}ms")
print(f"SAC sizes: R={len(sac_r):,}B, G={len(sac_g):,}B, B={len(sac_b):,}B")
print(f"Total SAC size: {rgb_sac_size:,} bytes ({rgb_sac_size/1024:.1f} KB)")

# PNG sizes
mask_result.hi_image.save("_test_rgb_hi.png")
mask_result.lo_image.save("_test_rgb_lo.png")
rgb_png_size = Path("_test_rgb_hi.png").stat().st_size + Path("_test_rgb_lo.png").stat().st_size
print(f"PNG sizes: {rgb_png_size:,} bytes ({rgb_png_size/1024:.1f} KB)")

# Reconstruct and measure quality
start = time.perf_counter()
reconstructed_rgb = reconstruct_from_rgb_mask(processed_arr, hi_arr, lo_arr)
rgb_recon_time = time.perf_counter() - start

original_arr = np.asarray(rgb_original, dtype=np.uint8)
rgb_psnr = psnr(original_arr, reconstructed_rgb)
rgb_mse = np.mean((original_arr.astype(np.float64) - reconstructed_rgb.astype(np.float64)) ** 2)
rgb_max_error = np.abs(original_arr.astype(np.int16) - reconstructed_rgb.astype(np.int16)).max()

print(f"Reconstruction time: {rgb_recon_time*1000:.2f}ms")
print(f"PSNR: {rgb_psnr:.2f} dB")
print(f"MSE: {rgb_mse:.4f}")
print(f"Max pixel error: {rgb_max_error}")

# ============================================================================
# 2. GRAYSCALE MASKS (Convert to grayscale before computing diff)
# ============================================================================
print("\n" + "="*70)
print("2. GRAYSCALE MASKS (Lossy - averaged channel reconstruction)")
print("="*70)

# Convert to grayscale and compute mask
start = time.perf_counter()
gray_original = rgb_original.convert("L")
gray_processed = processed.convert("L")

gray_original_arr = np.asarray(gray_original, dtype=np.uint8)
gray_processed_arr = np.asarray(gray_processed, dtype=np.uint8)

diff_gray = gray_original_arr.astype(np.int16) - gray_processed_arr.astype(np.int16)
encoded_gray = (diff_gray.astype(np.int32) + DIFF_OFFSET).astype(np.uint16)
hi_gray = (encoded_gray >> 8).astype(np.uint8)
lo_gray = (encoded_gray & 0xFF).astype(np.uint8)
gray_mask_time = time.perf_counter() - start

print(f"Mask generation time: {gray_mask_time*1000:.2f}ms")
print(f"Mask shape: hi={hi_gray.shape}, lo={lo_gray.shape}")

# Encode to SAC (single file)
start = time.perf_counter()
sac_gray = build_sac(hi_gray.ravel().astype(np.int16), lo_gray.ravel().astype(np.int16), w, h)
gray_sac_time = time.perf_counter() - start

print(f"SAC encoding time: {gray_sac_time*1000:.2f}ms")
print(f"SAC size: {len(sac_gray):,} bytes ({len(sac_gray)/1024:.1f} KB)")

# PNG sizes
hi_gray_img = Image.fromarray(hi_gray, mode='L')
lo_gray_img = Image.fromarray(lo_gray, mode='L')
hi_gray_img.save("_test_gray_hi.png")
lo_gray_img.save("_test_gray_lo.png")
gray_png_size = Path("_test_gray_hi.png").stat().st_size + Path("_test_gray_lo.png").stat().st_size
print(f"PNG sizes: {gray_png_size:,} bytes ({gray_png_size/1024:.1f} KB)")

# Reconstruct and measure quality
start = time.perf_counter()
reconstructed_gray = reconstruct_from_grayscale_mask(processed_arr, hi_gray, lo_gray)
gray_recon_time = time.perf_counter() - start

gray_psnr = psnr(original_arr, reconstructed_gray)
gray_mse = np.mean((original_arr.astype(np.float64) - reconstructed_gray.astype(np.float64)) ** 2)
gray_max_error = np.abs(original_arr.astype(np.int16) - reconstructed_gray.astype(np.int16)).max()

print(f"Reconstruction time: {gray_recon_time*1000:.2f}ms")
print(f"PSNR: {gray_psnr:.2f} dB")
print(f"MSE: {gray_mse:.4f}")
print(f"Max pixel error: {gray_max_error}")

# ============================================================================
# 3. COMPARISON SUMMARY
# ============================================================================
print("\n" + "="*70)
print("COMPARISON SUMMARY")
print("="*70)

print("\nFile Size:")
print(f"  RGB SAC:       {rgb_sac_size:,} bytes ({rgb_sac_size/1024:.1f} KB)")
print(f"  Grayscale SAC: {len(sac_gray):,} bytes ({len(sac_gray)/1024:.1f} KB)")
print(f"  Size ratio:    {rgb_sac_size/len(sac_gray):.2f}x larger")
print(f"  Space saved:   {(rgb_sac_size - len(sac_gray)):,} bytes ({(rgb_sac_size - len(sac_gray))/1024:.1f} KB)")

print("\nEncoding Performance:")
print(f"  RGB mask gen:  {rgb_mask_time*1000:.2f}ms")
print(f"  Gray mask gen: {gray_mask_time*1000:.2f}ms")
print(f"  RGB SAC enc:   {rgb_sac_time*1000:.2f}ms")
print(f"  Gray SAC enc:  {gray_sac_time*1000:.2f}ms")

print("\nDecoding Performance:")
print(f"  RGB recon:     {rgb_recon_time*1000:.2f}ms")
print(f"  Gray recon:    {gray_recon_time*1000:.2f}ms")

print("\nReconstruction Quality:")
print(f"  RGB PSNR:      {rgb_psnr:.2f} dB (max error: {rgb_max_error})")
print(f"  Gray PSNR:     {gray_psnr:.2f} dB (max error: {gray_max_error})")
print(f"  Quality loss:  {rgb_psnr - gray_psnr:.2f} dB")

if rgb_psnr == float('inf') and gray_psnr == float('inf'):
    print("\n  [PERFECT] Both methods achieve perfect reconstruction!")
elif rgb_psnr == float('inf'):
    print("\n  [PERFECT] RGB achieves perfect reconstruction")
    print(f"  [LOSSY] Grayscale has visible artifacts ({gray_psnr:.1f} dB)")
elif gray_psnr >= 50:
    print(f"\n  [EXCELLENT] Grayscale quality is visually lossless (>50 dB)")
elif gray_psnr >= 40:
    print(f"\n  [GOOD] Grayscale quality is very good (>40 dB)")
elif gray_psnr >= 30:
    print(f"\n  [MODERATE] Grayscale has minor visible artifacts (>30 dB)")
else:
    print(f"\n  [POOR] Grayscale has significant quality loss (<30 dB)")

print("\n" + "="*70)
print("RECOMMENDATION:")
print("="*70)

if gray_psnr >= 50:
    print("[GRAYSCALE] Quality loss is negligible, 3x size savings recommended")
elif gray_psnr >= 40:
    print("[GRAYSCALE] Minor quality loss acceptable for 3x size savings")
elif gray_psnr >= 30:
    print("[CONTEXT DEPENDENT] Evaluate if quality loss is acceptable")
else:
    print("[RGB] Quality loss too high, keep RGB encoding")

# Save comparison images
Image.fromarray(reconstructed_rgb).save("_test_rgb_reconstructed.png")
Image.fromarray(reconstructed_gray).save("_test_gray_reconstructed.png")
print("\nComparison images saved:")
print("  - _test_rgb_reconstructed.png")
print("  - _test_gray_reconstructed.png")

# Cleanup
Path("_test_rgb_hi.png").unlink()
Path("_test_rgb_lo.png").unlink()
Path("_test_gray_hi.png").unlink()
Path("_test_gray_lo.png").unlink()
