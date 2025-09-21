# Poison Mask Processor

Produce a pair of mask planes that let a processed (obfuscated) image render exactly like the
original everywhere on the web while downloads still return the processed payload. The scheme packs
the per-channel difference into two 8-bit PNGs (high/low bytes) so the browser can reconstruct the
original losslessly in JavaScript.

## Pipeline Overview

1. Decode both images (JPEG, PNG, TIFF, RAW via Pillow) to a common 8-bit RGBA frame.
2. Compute the signed integer difference `delta = original - processed` for every channel.
3. Pack that `int16` field into two PNGs: `mask_hi` contains the high byte, `mask_lo` the low byte.
4. Ship the processed image plus the two mask planes. The client adds `delta` back to the processed pixels
   (with clamping) to recreate the original. Because the `<img>` `src` is still the processed file,
   crawlers and downloads never see the pristine source.

The packing range (-32768 to 32767) exceeds what an 8-bit image can differ by (-255 to 255), so
reconstruction is mathematically lossless.

## CLI Usage

```bash
python -m poison_mask.processor original.png processed.jpg \
  --mask-hi-output processed_mask_hi.png \
  --mask-lo-output processed_mask_lo.png \
  --preview-output reconstructed_preview.png \
  --metadata-output processed_mask.json \
  --filter-id portrait-mask \
  --css-class portrait-poison
```

### Outputs

- `*_mask_hi.png` - high byte of the packed difference (RGBA).
- `*_mask_lo.png` - low byte of the packed difference (RGBA).
- `reconstructed_preview.png` - optional sanity check that should be pixel-identical to the original.
- `processed_mask.json` - manifest with dimensions, diff stats, encoding parameters, and a ready-to-use
  JavaScript helper for in-browser reconstruction.

If you omit the `--mask-*` flags, files default to `<processed>_mask_hi.png` and `<processed>_mask_lo.png`.

## Web Integration

The manifest includes a vanilla JS helper (`js_snippet`) that:
1. Fetches the processed image plus the two mask planes.
2. Draws them into offscreen canvases.
3. Rebuilds the original pixels by combining high/low bytes and adding the resulting difference.
4. Swaps the `<img>` for a `<canvas>` that shows the reconstructed frame.

You can inline that snippet or adapt it to your framework. Example of attaching via the class supplied
on the CLI:

```html
<img src="/assets/portrait_processed.jpg" class="portrait-poison" alt="Portrait" />
<script type="module">
  import manifest from '/assets/portrait_mask.json' assert { type: 'json' };
  const applyPoisonMask = new Function(manifest.js_snippet + '\nreturn applyPoisonMask;')();
  document.querySelectorAll('img.' + manifest.css_class).forEach(applyPoisonMask);
</script>
```

### Responsive Layouts

- The canvas inherits the processed image's intrinsic resolution. Use CSS to scale it exactly as the
  original `<img>` (for example, `canvas.portrait-poison { width: 100%; height: auto; }`).
- Because both mask planes are standard PNGs, they resize identically to the processed image when the
  browser rescales, so the reconstruction holds for any viewport size.
- For art-directed crops, store the crop box and scaling metadata (not yet automatic) alongside the
  manifest so the front-end can reproduce the same `object-fit` behaviour before decoding the mask.

## Implementation Notes

- Works with any Pillow-readable source. For RAW, pre-develop to an 8-bit RGBA frame before running
  the tool to avoid camera-specific pipelines in the browser.
- Differences are encoded in integer space, so reconstruction is exact even after aggressive obfuscations
  (the mask just captures larger magnitudes).
- Serve the mask PNGs with the same cache policy as the processed asset; the JS helper downloads both
  before swapping the element.
- Dependencies: `numpy` and `Pillow`.

## Testing

Synthetic unit tests live under `poison_mask/tests`:

```bash
pytest -q poison_mask/tests
```

They assert round-trip exactness and verify the packing/decoding logic. Add image-based regression
cases as you plug the module into real pipelines.
