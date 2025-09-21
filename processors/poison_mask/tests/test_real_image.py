import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from processors.poison_mask.processor import compute_mask, load_image, reconstruct_preview

ORIGINAL_PATH = ROOT / "input" / "Mona_Lisa,_by_Leonardo_da_Vinci,_from_C2RMF_retouched.jpg"
PROCESSED_PATH = (
    ROOT
    / "outputs"
    / "Mona_Lisa,_by_Leonardo_da_Vinci,_from_C2RMF_retouched"
    / "layers"
    / "05-invisible-watermark"
    / "Mona_Lisa,_by_Leonardo_da_Vinci,_from_C2RMF_retouched.jpg"
)


def test_real_image_round_trip(tmp_path):
    original = load_image(ORIGINAL_PATH)
    processed = load_image(PROCESSED_PATH)

    mask = compute_mask(original, processed)

    # Persist artifacts in pytest tmpdir for debugging convenience.
    mask_hi_tmp = tmp_path / "mask_hi.png"
    mask_lo_tmp = tmp_path / "mask_lo.png"
    mask.hi_image.save(mask_hi_tmp)
    mask.lo_image.save(mask_lo_tmp)

    # Also drop artifacts into the repo outputs tree for manual inspection.
    output_dir = ROOT / "outputs" / "mask_test_real_image"
    output_dir.mkdir(parents=True, exist_ok=True)
    mask.hi_image.save(output_dir / "mask_hi.png")
    mask.lo_image.save(output_dir / "mask_lo.png")

    reconstructed = reconstruct_preview(processed, mask.hi_image, mask.lo_image)
    reconstructed.save(tmp_path / "reconstructed.png")
    reconstructed.save(output_dir / "reconstructed.png")

    original_arr = np.asarray(original, dtype=np.uint8)
    reconstructed_arr = np.asarray(reconstructed, dtype=np.uint8)

    assert np.array_equal(
        reconstructed_arr, original_arr
    ), "Reconstruction must match the original image pixel-for-pixel"

    # Ensure the diff range stays within expected int16 bounds for this real example.
    assert mask.diff_min >= -255
    assert mask.diff_max <= 255
