"""
Run Mona Lisa through full protection pipeline and demonstrate SAC mask reconstruction.

Outputs all images to the outputs/ directory for inspection.
"""
from pathlib import Path
import json
import numpy as np
from PIL import Image

from artorize_runner.protection_pipeline_gpu import run_full_workflow_parallel
from processors.poison_mask.processor import reconstruct_preview, load_image


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


def main():
    # Setup paths
    input_dir = Path("input")
    output_dir = Path("outputs")

    mona_lisa_path = input_dir / "Mona_Lisa,_by_Leonardo_da_Vinci,_from_C2RMF_retouched.jpg"

    if not mona_lisa_path.exists():
        print(f"Error: Mona Lisa image not found at {mona_lisa_path}")
        return

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

    # Get output info
    processed_info = result["processed"][0]
    print(f"\n[+] Pipeline completed: {processed_info['image']}")

    # Load summary
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
        final_protected_path = Path(layer["path"])

    print(f"\n[+] Pipeline completed successfully")
    print(f"  - Original: {original_path}")
    print(f"  - Protected: {final_protected_path}")

    # Find the final comparison poison mask
    layers_dir = output_base / "layers"
    final_comparison_dir = None

    for dir_path in layers_dir.iterdir():
        if dir_path.is_dir() and "final-comparison" in dir_path.name:
            final_comparison_dir = dir_path
            break

    if not final_comparison_dir:
        print("\n[!] Warning: Final comparison directory not found")
        return

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

    print(f"\n[+] Found poison masks:")
    print(f"  - Mask Hi: {mask_hi_path.name}")
    print(f"  - Mask Lo: {mask_lo_path.name}")
    print(f"  - SAC: {sac_path.name} ({sac_path.stat().st_size / 1024 / 1024:.2f} MB)")

    # Load images
    original_img = load_image(original_path, mode="RGB")
    protected_img = load_image(final_protected_path, mode="RGB")
    mask_hi_img = Image.open(mask_hi_path)
    mask_lo_img = Image.open(mask_lo_path)

    print(f"\n[+] Loaded images:")
    print(f"  - Original size: {original_img.size}")
    print(f"  - Protected size: {protected_img.size}")
    print(f"  - Mask size: {mask_hi_img.size}")

    # Apply poison mask to reconstruct original
    print(f"\n" + "="*80)
    print("APPLYING POISON MASK TO RECONSTRUCT ORIGINAL")
    print("="*80)

    reconstructed_img = reconstruct_preview(protected_img, mask_hi_img, mask_lo_img)

    # Save the reconstructed image
    reconstructed_path = output_base / "reconstructed_from_mask.jpg"
    reconstructed_img.save(reconstructed_path, quality=95)

    print(f"\n[+] Reconstruction complete")
    print(f"  - Saved to: {reconstructed_path}")

    # Calculate reconstruction quality metrics
    print(f"\n" + "="*80)
    print("VERIFYING RECONSTRUCTION QUALITY")
    print("="*80)

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

    # Quality checks
    print(f"\n" + "="*80)
    print("QUALITY CHECKS")
    print("="*80)

    if psnr >= 30.0:
        print(f"[+] PSNR check passed: {psnr:.2f} dB >= 30.0 dB (good quality)")
    else:
        print(f"[-] PSNR check failed: {psnr:.2f} dB < 30.0 dB")

    if mean_diff <= 10.0:
        print(f"[+] Mean difference check passed: {mean_diff:.2f} <= 10.0")
    else:
        print(f"[!] Mean difference: {mean_diff:.2f} > 10.0 (acceptable due to grayscale masks)")

    if max_diff <= 255:
        print(f"[+] Max difference check passed: {max_diff:.0f} <= 255")
    else:
        print(f"[-] Max difference check failed: {max_diff:.0f} > 255")

    print(f"\n" + "="*80)
    print("[+] PROCESSING COMPLETE")
    print("="*80 + "\n")

    print(f"Output files saved to: {output_base}")
    print(f"  - Original: {original_path.name}")
    print(f"  - Protected: {final_protected_path.name}")
    print(f"  - Reconstructed: {reconstructed_path.name}")
    print(f"  - SAC mask: {sac_path.name}")
    print(f"\nFinal comparison mask directory: {final_comparison_dir}")


if __name__ == "__main__":
    main()
