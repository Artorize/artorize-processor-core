"""Test that protection pipeline generates SAC mask files."""

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from artorize_runner.protection_pipeline_gpu import (
    run_full_workflow_parallel,
    ProtectionWorkflowConfig,
)


@pytest.fixture
def test_input_dir(tmp_path):
    """Create temporary input directory with a test image."""
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    # Create a simple test image
    img = Image.new('RGB', (128, 128), color=(100, 150, 200))
    pixels = np.array(img)
    pixels[30:60, 30:60] = [255, 200, 100]
    pixels[70:100, 70:100] = [100, 255, 200]
    img = Image.fromarray(pixels.astype(np.uint8))

    img_path = input_dir / "test_image.jpg"
    img.save(img_path, 'JPEG')

    return input_dir


def test_pipeline_generates_sac_files(test_input_dir, tmp_path):
    """Test that the pipeline generates SAC mask files when poison mask is enabled."""
    output_dir = tmp_path / "outputs"

    # Run pipeline with minimal stages but poison mask enabled
    config = ProtectionWorkflowConfig(
        enable_fawkes=True,
        enable_photoguard=True,
        enable_mist=False,
        enable_nightshade=False,
        watermark_strategy=None,  # Skip watermark for speed
        enable_poison_mask=True,  # This is what we're testing
        enable_c2pa_manifest=False,
        enable_stegano_embed=False,
    )

    result = run_full_workflow_parallel(
        input_dir=test_input_dir,
        output_root=output_dir,
        include_hash_analysis=False,  # Skip analysis for speed
        use_gpu=False,  # Use CPU for consistency
        max_workers=1,
        config=config,
    )

    # Verify processing succeeded
    assert "processed" in result
    assert len(result["processed"]) == 1

    processed_item = result["processed"][0]
    output_path = Path(processed_item["output_dir"])

    # Check that poison_mask directory exists
    poison_mask_dir = output_path / "poison_mask"
    assert poison_mask_dir.exists(), "poison_mask directory not created"

    # Verify SAC files were generated
    sac_files = list(poison_mask_dir.glob("*.sac"))
    assert len(sac_files) > 0, "No SAC files generated"

    print(f"\nGenerated {len(sac_files)} SAC files:")
    for sac_file in sac_files:
        size_kb = sac_file.stat().st_size / 1024
        print(f"  - {sac_file.name}: {size_kb:.2f} KB")

        # Verify file is not empty and has reasonable size
        assert size_kb > 1, f"{sac_file.name} is too small"
        assert size_kb < 500, f"{sac_file.name} is unexpectedly large"

    # Verify corresponding PNG and NPZ files also exist
    for sac_file in sac_files:
        base_name = sac_file.stem  # e.g., "01-fawkes_mask"

        # Check for hi/lo PNG files
        hi_png = poison_mask_dir / f"{base_name}_hi.png"
        lo_png = poison_mask_dir / f"{base_name}_lo.png"
        assert hi_png.exists(), f"Missing {hi_png.name}"
        assert lo_png.exists(), f"Missing {lo_png.name}"

        # Check for NPZ file
        npz_file = poison_mask_dir / f"{base_name}_planes.npz"
        assert npz_file.exists(), f"Missing {npz_file.name}"

    # Verify summary.json references the SAC files
    summary_path = Path(processed_item["summary"])
    assert summary_path.exists()

    with open(summary_path, 'r') as f:
        summary = json.load(f)

    # Check that layers with poison mask data include SAC paths
    layers_with_sac = [
        layer for layer in summary.get("layers", [])
        if layer.get("poison_mask_sac_path")
    ]
    assert len(layers_with_sac) > 0, "No layers reference SAC files in summary"

    print(f"\nLayers with SAC masks: {len(layers_with_sac)}")
    for layer in layers_with_sac:
        print(f"  - {layer['stage']}: {Path(layer['poison_mask_sac_path']).name}")


def test_pipeline_without_poison_mask_no_sac(test_input_dir, tmp_path):
    """Test that SAC files are NOT generated when poison mask is disabled."""
    output_dir = tmp_path / "outputs"

    # Run pipeline with poison mask DISABLED
    config = ProtectionWorkflowConfig(
        enable_fawkes=True,
        enable_photoguard=False,
        enable_mist=False,
        enable_nightshade=False,
        watermark_strategy=None,
        enable_poison_mask=False,  # Disabled
        enable_c2pa_manifest=False,
    )

    result = run_full_workflow_parallel(
        input_dir=test_input_dir,
        output_root=output_dir,
        include_hash_analysis=False,
        use_gpu=False,
        max_workers=1,
        config=config,
    )

    # Verify processing succeeded
    assert len(result["processed"]) == 1

    processed_item = result["processed"][0]
    output_path = Path(processed_item["output_dir"])

    # Poison mask directory should not exist
    poison_mask_dir = output_path / "poison_mask"
    if poison_mask_dir.exists():
        sac_files = list(poison_mask_dir.glob("*.sac"))
        assert len(sac_files) == 0, "SAC files generated when poison mask disabled"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
