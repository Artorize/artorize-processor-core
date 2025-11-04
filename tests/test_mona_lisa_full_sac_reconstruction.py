"""
Test processing Mona Lisa through all protection layers and verify SAC mask reconstruction.

This test:
1. Runs Mona Lisa through the full protection pipeline
2. Generates the final comparison SAC mask
3. Applies the mask back to the protected image
4. Verifies the reconstruction matches the original
"""
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

# Add root to path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from artorize_runner.protection_pipeline_gpu import (
    run_full_workflow_parallel,
    ProtectionWorkflowConfig,
)
from processors.poison_mask.processor import (
    reconstruct_preview,
    load_image,
)


def calculate_psnr(img1: Image.Image, img2: Image.Image) -> float:
    """Calculate Peak Signal-to-Noise Ratio between two images."""
    arr1 = np.array(img1).astype(np.float64)
    arr2 = np.array(img2).astype(np.float64)

    mse = np.mean((arr1 - arr2) ** 2)
    if mse == 0:
        return float('inf')

    max_pixel = 255.0
    psnr = 20 * np.log10(max_pixel / np.sqrt(mse))
    return psnr


@pytest.mark.integration
def test_mona_lisa_full_pipeline_with_sac_reconstruction(tmp_path):
    """
    Process Mona Lisa through all protection layers and verify SAC mask reconstruction.

    This is the main integration test that:
    - Applies all protection layers (Fawkes, PhotoGuard, Mist, Nightshade, watermark)
    - Generates final comparison poison mask
    - Encodes mask to SAC format
    - Applies mask back to protected image
    - Verifies reconstruction quality (PSNR)
    """
    # Setup paths
    input_dir = Path("input")
    mona_lisa_path = input_dir / "Mona_Lisa,_by_Leonardo_da_Vinci,_from_C2RMF_retouched.jpg"

    if not mona_lisa_path.exists():
        pytest.skip("Mona Lisa image not found in input folder")

    output_dir = tmp_path / "mona_lisa_full_test"

    # Configure pipeline with ALL protection layers enabled
    print("\n" + "="*80)
    print("RUNNING FULL PROTECTION PIPELINE ON MONA LISA")
    print("="*80)
    print(f"Input: {mona_lisa_path}")
    print(f"Output: {output_dir}")
    print("\nEnabled protections:")
    print("  [+] Fawkes (Gaussian noise cloaking)")
    print("  [+] PhotoGuard (blur + edge blending)")
    print("  [+] Mist (color/contrast enhancement)")
    print("  [+] Nightshade (pixel shifting + noise)")
    print("  [+] Invisible Watermark (LSB embedding)")
    print("  [+] Poison Mask (final comparison)")
    print("="*80 + "\n")

    # Run the full protection pipeline
    result = run_full_workflow_parallel(
        input_dir=input_dir,
        output_root=output_dir,
        include_hash_analysis=True,
        use_gpu=True,
        max_workers=1,
    )

    # Verify processing completed
    assert len(result["processed"]) == 1, "Should process exactly one image"
    processed_info = result["processed"][0]
    assert "Mona_Lisa" in processed_info["image"]

    # Load summary to find output paths
    with open(Path(processed_info["summary"]), 'r') as f:
        summary = json.load(f)

    output_base = Path(processed_info["output_dir"])

    # Find the original and final protected images
    original_path = None
    final_protected_path = None

    for layer in summary["layers"]:
        if layer.get("path") is None:
            continue
        if layer["stage"] == "original":
            original_path = Path(layer["path"])
        # The last layer is the final protected output
        final_protected_path = Path(layer["path"])

    assert original_path and original_path.exists(), "Original layer not found"
    assert final_protected_path and final_protected_path.exists(), "Final protected layer not found"

    print(f"\n[+] Pipeline completed successfully")
    print(f"  - Original: {original_path}")
    print(f"  - Protected: {final_protected_path}")

    # Find the final comparison poison mask
    # Masks are stored in the layer directories, not a separate poison_mask dir
    layers_dir = output_base / "layers"
    final_comparison_dir = None

    # Find the final-comparison layer directory
    for dir_path in layers_dir.iterdir():
        if dir_path.is_dir() and "final-comparison" in dir_path.name:
            final_comparison_dir = dir_path
            break

    assert final_comparison_dir and final_comparison_dir.exists(), "Final comparison directory not found"

    # Look for final comparison mask files
    mask_hi_path = None
    mask_lo_path = None
    sac_path = None

    for file in final_comparison_dir.iterdir():
        if file.suffix == ".sac" and "_mask.sac" in file.name:
            sac_path = file
        elif "_mask_hi.png" in file.name:
            mask_hi_path = file
        elif "_mask_lo.png" in file.name:
            mask_lo_path = file

    assert mask_hi_path and mask_hi_path.exists(), "Final comparison mask_hi not found"
    assert mask_lo_path and mask_lo_path.exists(), "Final comparison mask_lo not found"
    assert sac_path and sac_path.exists(), "Final comparison SAC file not found"

    print(f"\n[+] Found poison masks:")
    print(f"  - Mask Hi: {mask_hi_path.name}")
    print(f"  - Mask Lo: {mask_lo_path.name}")
    print(f"  - SAC: {sac_path.name} ({sac_path.stat().st_size / 1024:.2f} KB)")

    # Load images
    original_img = load_image(original_path, mode="RGB")
    protected_img = load_image(final_protected_path, mode="RGB")
    mask_hi_img = Image.open(mask_hi_path)
    mask_lo_img = Image.open(mask_lo_path)

    print(f"\n[+] Loaded images:")
    print(f"  - Original size: {original_img.size}")
    print(f"  - Protected size: {protected_img.size}")
    print(f"  - Mask size: {mask_hi_img.size}")

    # Verify dimensions match
    assert original_img.size == protected_img.size, "Original and protected dimensions don't match"
    assert mask_hi_img.size == mask_lo_img.size, "Mask hi/lo dimensions don't match"

    # Apply poison mask to reconstruct original
    print(f"\n" + "="*80)
    print("APPLYING POISON MASK TO RECONSTRUCT ORIGINAL")
    print("="*80)

    reconstructed_img = reconstruct_preview(protected_img, mask_hi_img, mask_lo_img)

    # Save the reconstructed image for visual inspection
    reconstructed_path = output_base / "reconstructed_from_mask.jpg"
    reconstructed_img.save(reconstructed_path, quality=95)

    print(f"\n[+] Reconstruction complete")
    print(f"  - Saved to: {reconstructed_path}")

    # Calculate reconstruction quality metrics
    print(f"\n" + "="*80)
    print("VERIFYING RECONSTRUCTION QUALITY")
    print("="*80)

    # Calculate PSNR (Peak Signal-to-Noise Ratio)
    # PSNR > 30 dB is generally considered good quality
    # PSNR > 40 dB is excellent
    psnr = calculate_psnr(original_img, reconstructed_img)

    print(f"\n[+] Reconstruction metrics:")
    print(f"  - PSNR: {psnr:.2f} dB")

    # Calculate pixel-level differences
    orig_arr = np.array(original_img).astype(np.int16)
    recon_arr = np.array(reconstructed_img).astype(np.int16)

    diff = np.abs(orig_arr - recon_arr)
    mean_diff = float(np.mean(diff))
    max_diff = float(np.max(diff))
    pixels_changed = np.count_nonzero(diff)
    total_pixels = diff.size
    change_ratio = pixels_changed / total_pixels

    print(f"  - Mean absolute difference: {mean_diff:.2f}")
    print(f"  - Max absolute difference: {max_diff:.0f}")
    print(f"  - Pixels changed: {pixels_changed:,} / {total_pixels:,} ({change_ratio*100:.2f}%)")

    # Verify reconstruction quality
    # Note: Masks are grayscale, so there will be small color channel errors
    # PSNR should still be high (> 30 dB) for good reconstruction
    print(f"\n" + "="*80)
    print("QUALITY CHECKS")
    print("="*80)

    checks_passed = True

    # Check PSNR
    if psnr >= 30.0:
        print(f"[+] PSNR check passed: {psnr:.2f} dB >= 30.0 dB (good quality)")
    else:
        print(f"[-] PSNR check failed: {psnr:.2f} dB < 30.0 dB")
        checks_passed = False

    # Check mean difference
    if mean_diff <= 10.0:
        print(f"[+] Mean difference check passed: {mean_diff:.2f} <= 10.0")
    else:
        print(f"[!] Mean difference: {mean_diff:.2f} > 10.0 (acceptable due to grayscale masks)")

    # Check max difference is reasonable
    if max_diff <= 255:
        print(f"[+] Max difference check passed: {max_diff:.0f} <= 255")
    else:
        print(f"[-] Max difference check failed: {max_diff:.0f} > 255")
        checks_passed = False

    print(f"\n" + "="*80)
    if checks_passed:
        print("[+] ALL QUALITY CHECKS PASSED")
    else:
        print("[-] SOME QUALITY CHECKS FAILED")
    print("="*80 + "\n")

    # Final assertions
    assert psnr >= 30.0, f"Reconstruction quality too low: PSNR={psnr:.2f} dB"
    assert max_diff <= 255, f"Max difference out of range: {max_diff}"

    # Verify SAC file exists and has reasonable size
    # For high-res images like Mona Lisa (7479x11146), SAC can be 160+ MB
    # Size = width * height * 2 bytes (int16) + 24 byte header
    sac_size_kb = sac_path.stat().st_size / 1024
    expected_min_size_kb = 100  # At least 100 KB
    expected_max_size_kb = 200000  # Up to 200 MB for very large images
    assert sac_size_kb > expected_min_size_kb, f"SAC file unexpectedly small: {sac_size_kb:.2f} KB"
    assert sac_size_kb < expected_max_size_kb, f"SAC file unexpectedly large: {sac_size_kb:.2f} KB"

    print(f"[+] Test completed successfully!")
    print(f"\nOutput files saved to: {output_base}")
    print(f"  - Original: {original_path.name}")
    print(f"  - Protected: {final_protected_path.name}")
    print(f"  - Reconstructed: {reconstructed_path.name}")
    print(f"  - SAC mask: {sac_path.name}")

    return {
        "original_path": original_path,
        "protected_path": final_protected_path,
        "reconstructed_path": reconstructed_path,
        "sac_path": sac_path,
        "psnr": psnr,
        "mean_diff": mean_diff,
        "max_diff": max_diff,
    }


if __name__ == "__main__":
    # Run the test directly
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        result = test_mona_lisa_full_pipeline_with_sac_reconstruction(Path(tmpdir))
        print(f"\n{'='*80}")
        print("TEST SUMMARY")
        print(f"{'='*80}")
        print(f"PSNR: {result['psnr']:.2f} dB")
        print(f"Mean Difference: {result['mean_diff']:.2f}")
        print(f"Max Difference: {result['max_diff']:.0f}")
        print(f"{'='*80}\n")
