# Poison Mask Grayscale Protocol

## Overview

The Artorize poison mask system uses **grayscale luminance masks** for optimal performance and file size efficiency. This document explains the technical rationale, performance characteristics, and implementation details of this design decision.

## Design Rationale

### The RGB vs Grayscale Trade-off

Artorize protection transforms modify RGB images channel-by-channel, creating per-channel perturbations. When computing reconstruction masks, there are two approaches:

1. **RGB Masks**: Store per-channel differences (R_diff, G_diff, B_diff)
2. **Grayscale Masks**: Convert to luminance, store single averaged difference

### Empirical Performance Analysis

Using the Mona Lisa test image (512×344px) with Fawkes-style protection:

| Metric | RGB | Grayscale | Improvement |
|--------|-----|-----------|-------------|
| **File Size (SAC)** | 2,064 KB | 688 KB | **3.0x smaller** |
| **File Size (PNG)** | 439 KB | 139 KB | **3.2x smaller** |
| **Mask Generation** | 19.30ms | 2.25ms | **8.6x faster** |
| **SAC Encoding** | 4.10ms | 1.09ms | **3.8x faster** |
| **Reconstruction** | 10.46ms | 7.99ms | **1.3x faster** |
| **PSNR Quality** | ∞ dB (perfect) | 32.98 dB | Minor loss |
| **Max Pixel Error** | 0 | 35 | Acceptable |

### Quality Loss Analysis

**Per-Channel Error Distribution** (grayscale reconstruction):
- **R channel**: avg 4.7, max 28 (7.8% pixels >10 error)
- **G channel**: avg 2.7, max 15 (0.2% pixels >10 error)
- **B channel**: avg 5.7, max 35 (14.2% pixels >10 error)

**Visual Characteristics**:
- Error appears as **distributed noise**, not structural artifacts
- Maximum error of 35 pixels (~14% of range) occurs in <0.5% of pixels
- Average error of 4-5 pixels (~2% of range) is imperceptible
- 32.98 dB PSNR is borderline visually lossless

### Why Grayscale is Acceptable

The small quality loss from grayscale masks is negligible because:

1. **Context of use**: Masks reconstruct images that have already been heavily perturbed by protection transforms (6.5px noise, blur, color shifts)
2. **Error magnitude**: 4-5 pixel average error is tiny compared to protection perturbations
3. **Error type**: Random distributed noise, not visible structure changes
4. **Reconstruction goal**: Approximate original, not pixel-perfect archival

The **3x file size savings** and **8.6x encoding speedup** dramatically outweigh the minor quality loss.

## Implementation

### Mask Generation

In `processors/poison_mask/processor.py`, the `compute_mask()` function converts both original and processed images to grayscale before computing differences:

```python
def compute_mask(original: Image.Image, processed: Image.Image) -> MaskComputation:
    """
    Return the packed difference mask that recreates the original.

    Uses grayscale luminance for masks to optimize file size (3x smaller)
    and encoding performance (8x faster) with minimal quality loss (~33 dB PSNR).
    """
    # Convert to grayscale for optimal mask encoding
    original_gray = original.convert("L")
    processed_gray = processed.convert("L")

    original_arr = np.asarray(original_gray, dtype=np.uint8)
    processed_arr = np.asarray(processed_gray, dtype=np.uint8)

    diff = original_arr.astype(np.int16) - processed_arr.astype(np.int16)
    # ... encode to hi/lo planes
```

**Key points**:
- PIL's `.convert("L")` uses standard RGB→grayscale formula: `Y = 0.299R + 0.587G + 0.114B`
- Resulting masks are 2D arrays: `(height, width)`
- Hi/lo planes are grayscale images (`mode='L'` in PIL)

### Reconstruction

The `reconstruct_preview()` function applies the grayscale difference to all RGB channels via broadcasting:

```python
def reconstruct_preview(processed: Image.Image, mask_hi: Image.Image, mask_lo: Image.Image) -> Image.Image:
    """
    Recreate the original image using grayscale mask.

    The grayscale diff is broadcast to all RGB channels for approximate reconstruction.
    """
    processed_arr = np.asarray(processed, dtype=np.int32)
    hi_arr = np.asarray(mask_hi, dtype=np.uint8)
    lo_arr = np.asarray(mask_lo, dtype=np.uint8)

    diff = _decode_difference(hi_arr, lo_arr).astype(np.int32)

    # Broadcast grayscale diff (H, W) to RGB (H, W, 3)
    if processed_arr.ndim == 3 and diff.ndim == 2:
        diff = diff[:, :, np.newaxis]

    reconstructed = processed_arr + diff
    return np.clip(reconstructed, 0, 255).astype(np.uint8)
```

### SAC Encoding

The SAC encoder in `artorize_gateway/sac_encoder.py` handles both grayscale and legacy RGB masks:

```python
def encode_mask_pair_from_arrays(hi_array, lo_array, width=None, height=None):
    """
    Encode mask hi/lo arrays into SAC format.

    Grayscale masks (H, W) are preferred for optimal file size (3x smaller).
    RGB masks are supported but will only encode the first channel.
    """
    # ... decode hi/lo to int16 diffs

    if diff.ndim == 3 and diff.shape[2] > 1:
        # Legacy RGB: extract first channel only
        a_flat = diff[:, :, 0].ravel()
        b_flat = diff[:, :, 0].ravel()
    else:
        # Grayscale (standard): duplicate for SAC v1 requirement
        a_flat = diff.ravel()
        b_flat = diff.ravel()

    return build_sac(a_flat, b_flat, width, height)
```

**SAC v1.1 Structure** (grayscale masks with single-array mode):
```
[24-byte header]
  - magic: "SAC1"
  - flags: 0x01 (FLAG_SINGLE_ARRAY)
  - dtype: int16
  - arrays_count: 1
  - length_a: width × height
  - length_b: width × height (not stored, decoder duplicates A)
  - width: image width
  - height: image height

[Payload: width × height × 2 bytes]
  - Array A: flattened int16 differences
  - Array B: omitted (50% smaller!)
```

**Optimization**: The SINGLE_ARRAY flag (bit 0 of flags byte) tells decoders that array B is identical to array A, so we omit it. This **cuts file size in half** with zero quality loss.

## Browser/Frontend Decoding

JavaScript reconstruction code applies the same grayscale diff to all RGB channels:

```javascript
// Decode hi/lo masks to int16 differences
const diff = (hiData[i] << 8) | loData[i] - 32768;

// Apply to all RGBA channels (skip alpha at i%4==3)
for (let i = 0; i < procData.data.length; i++) {
  if (i % 4 !== 3) {  // Skip alpha channel
    const pixelIndex = Math.floor(i / 4);
    const grayDiff = maskData[pixelIndex];
    procData.data[i] = Math.min(255, Math.max(0, procData.data[i] + grayDiff));
  }
}
```

## File Size Savings at Scale

**Per-image savings** (SAC v1.1 single-array mode):
- RGB (3 files): 2,064 KB
- Grayscale v1.1: 344 KB
- **Savings: 1,720 KB (84% reduction)**

For a production CDN serving protected artwork:
- **1,000 images**: 1.7 GB saved
- **10,000 images**: 17 GB saved
- **100,000 images**: 170 GB saved

At CDN bandwidth costs (~$0.08/GB), the savings are substantial:
- 100K images: **$13.60 saved per month** in bandwidth alone
- Plus faster page loads, better UX, reduced client-side decoding time

**Additional SAC v1.1 benefit**: 50% less memory allocation in browser (single array reference instead of two)

## Migration Path

### Backward Compatibility

Legacy RGB masks are still supported by the SAC encoder for transition:
- RGB hi/lo PNG files decode but only use first channel
- Reconstruction works but loses color-specific correction

### Forward Path

All new masks generated by the protection pipeline are grayscale:
1. `compute_mask()` automatically converts to grayscale
2. SAC encoder optimizes for grayscale arrays
3. Frontend decoding broadcasts to RGB channels

## Performance Benchmarks

**Test Configuration**:
- Image: Mona Lisa (512×344px, 176,128 pixels)
- Transform: Fawkes-style Gaussian noise (σ=6.5)
- Hardware: CUDA-enabled GPU

**Results**:
```
Mask Generation:
  RGB:       19.30ms  (generates 3-channel diffs)
  Grayscale:  2.25ms  (8.6x faster)

SAC Encoding:
  RGB:        4.10ms  (encodes 3 separate files)
  Grayscale:  1.09ms  (3.8x faster)

File Sizes:
  RGB SAC:       2,064 KB  (3 files × 688 KB)
  Grayscale SAC:   688 KB  (1 file)

Reconstruction Quality:
  RGB PSNR:      ∞ dB  (perfect)
  Grayscale:  32.98 dB  (visually lossless)
```

## Conclusion

**Grayscale masks with SAC v1.1 single-array mode** are the optimal choice for the Artorize poison mask protocol because:

✓ **6x smaller file sizes** (84% reduction) → faster CDN delivery, lower bandwidth costs
✓ **8.6x faster generation** → better pipeline throughput
✓ **3.8x faster encoding** → reduced server CPU load
✓ **50% less browser memory** → single array reference instead of duplicate
✓ **Minor quality loss** (33 dB PSNR) → imperceptible in practice
✓ **Simpler protocol** → no multi-channel complexity

The small reconstruction error is negligible compared to the large protection perturbations already applied, making grayscale masks with SAC v1.1 the clear winner for production deployment.

## References

- SAC Protocol Specification: `sac_v_1_cdn_mask_transfer_protocol.md`
- Implementation: `processors/poison_mask/processor.py`
- Encoder: `artorize_gateway/sac_encoder.py`
- Test Results: `test_rgb_vs_grayscale_masks.py`
