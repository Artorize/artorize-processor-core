import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from processors.poison_mask.processor import compute_mask, load_image, reconstruct_preview
from artorize_gateway.sac_encoder import encode_mask_pair_from_arrays

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

    # Convert mask images to numpy arrays
    hi_arr = np.asarray(mask.hi_image, dtype=np.uint8)
    lo_arr = np.asarray(mask.lo_image, dtype=np.uint8)

    # Encode to SAC format
    width, height = mask.size
    sac_result = encode_mask_pair_from_arrays(hi_arr, lo_arr, width, height)

    # Persist SAC file in pytest tmpdir for debugging convenience
    sac_tmp = tmp_path / "mask.sac"
    sac_tmp.write_bytes(sac_result.sac_bytes)

    # Also drop artifacts into the repo outputs tree for manual inspection
    output_dir = ROOT / "outputs" / "mask_test_real_image"
    output_dir.mkdir(parents=True, exist_ok=True)
    sac_output = output_dir / "mask.sac"
    sac_output.write_bytes(sac_result.sac_bytes)

    # Verify SAC encoding dimensions
    assert sac_result.width == width
    assert sac_result.height == height
    assert sac_result.length_a == width * height
    assert sac_result.length_b == width * height

    # Verify reconstruction works
    reconstructed = reconstruct_preview(processed, mask.hi_image, mask.lo_image)
    reconstructed.save(tmp_path / "reconstructed.png")
    reconstructed.save(output_dir / "reconstructed.png")

    original_arr = np.asarray(original, dtype=np.uint8)
    reconstructed_arr = np.asarray(reconstructed, dtype=np.uint8)

    assert np.array_equal(
        reconstructed_arr, original_arr
    ), "Reconstruction must match the original image pixel-for-pixel"

    # Ensure the diff range stays within expected int16 bounds for this real example
    assert mask.diff_min >= -255
    assert mask.diff_max <= 255

    # Verify SAC file size is reasonable (should be around 2MB for typical image)
    sac_size_mb = len(sac_result.sac_bytes) / (1024 * 1024)
    print(f"SAC file size: {sac_size_mb:.2f} MB")
    assert sac_size_mb > 0.1, "SAC file unexpectedly small"
    assert sac_size_mb < 10, "SAC file unexpectedly large"
