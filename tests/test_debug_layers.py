"""Debug script to see layer structure."""

import json
import shutil
from pathlib import Path

from artorize_gateway.app import _process_job, JobRecord


def main():
    # Use the test image
    test_image = Path("input/Mona_Lisa,_by_Leonardo_da_Vinci,_from_C2RMF_retouched.jpg")
    if not test_image.exists():
        print(f"Test image not found: {test_image}")
        return

    # Create temp directories
    temp_dir = Path("temp_test_output")
    temp_dir.mkdir(exist_ok=True)

    input_dir = temp_dir / "input"
    input_dir.mkdir(exist_ok=True)

    output_dir = temp_dir / "outputs"
    output_dir.mkdir(exist_ok=True)

    # Copy image
    temp_input = input_dir / test_image.name
    shutil.copy2(test_image, temp_input)

    # Create job
    job = JobRecord(
        job_id="debug-job",
        input_path=temp_input,
        input_dir=input_dir,
        output_root=output_dir,
        include_hash_analysis=True,
        include_protection=True,
        enable_tineye=False,
        processors=None,
    )

    # Process
    print("Processing image...")
    result = _process_job(job)

    # Print layer structure
    print("\n" + "=" * 80)
    print("LAYER STRUCTURE:")
    print("=" * 80)

    layers = result.summary["layers"]
    for i, layer in enumerate(layers):
        print(f"\nLayer {i}: {layer.get('stage')}")
        print(f"  Description: {layer.get('description')}")
        print(f"  Path: {layer.get('path')}")
        print(f"  Has SAC mask: {'poison_mask_sac_path' in layer}")
        if 'poison_mask_sac_path' in layer:
            sac_path = Path(layer['poison_mask_sac_path'])
            print(f"  SAC path: {sac_path}")
            print(f"  SAC exists: {sac_path.exists()}")
            if sac_path.exists():
                print(f"  SAC size: {sac_path.stat().st_size} bytes")
        if 'error' in layer:
            print(f"  ERROR: {layer['error']}")

    print("\n" + "=" * 80)
    print("RECOMMENDED LAYER TO USE FOR UPLOAD:")
    print("=" * 80)

    # Find the best layer for backend upload
    best_layer = None
    for layer in reversed(layers):
        # Skip layers without image files
        if not layer.get("path") or layer.get("path") == "None":
            continue
        # Skip error layers
        if layer.get("error"):
            continue
        # Prefer layers with SAC masks
        if "poison_mask_sac_path" in layer:
            best_layer = layer
            break

    if best_layer:
        print(f"\nBest layer: {best_layer['stage']}")
        print(f"Path: {best_layer['path']}")
        if 'poison_mask_sac_path' in best_layer:
            print(f"SAC mask: {best_layer['poison_mask_sac_path']}")
    else:
        print("No suitable layer found!")


if __name__ == "__main__":
    main()
