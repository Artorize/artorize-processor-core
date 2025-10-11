"""Tests for GPU-accelerated protection pipeline."""

import json
import shutil
import time
from pathlib import Path
import pytest
import numpy as np
from PIL import Image

from artorize_runner.protection_pipeline_gpu import (
    run_full_workflow_parallel,
    ProtectionWorkflowConfig,
    _apply_fawkes_like_gpu,
    _apply_photoguard_like_gpu,
    _apply_mist_like_gpu,
    _apply_nightshade_like_gpu,
    _apply_invisible_watermark_vectorized,
    _apply_tree_ring_gpu,
    TORCH_AVAILABLE,
    DEVICE
)


@pytest.fixture
def test_image(tmp_path):
    """Create a test image for pipeline testing."""
    img_path = tmp_path / "test_image.jpg"
    # Create a simple test image
    img = Image.new('RGB', (256, 256), color=(73, 109, 137))
    # Add some variation to make transformations visible
    pixels = np.array(img)
    pixels[50:100, 50:100] = [255, 200, 100]
    pixels[150:200, 150:200] = [100, 255, 200]
    img = Image.fromarray(pixels.astype(np.uint8))
    img.save(img_path, 'JPEG')
    return img_path


@pytest.fixture
def input_dir_with_images(tmp_path):
    """Create input directory with multiple test images."""
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    # Create multiple test images
    for i in range(3):
        img_path = input_dir / f"test_image_{i}.jpg"
        img = Image.new('RGB', (256, 256), color=(73 + i*20, 109, 137))
        pixels = np.array(img)
        pixels[50:100, 50:100] = [255 - i*30, 200, 100]
        img = Image.fromarray(pixels.astype(np.uint8))
        img.save(img_path, 'JPEG')

    return input_dir


def test_gpu_pipeline_single_image(test_image, tmp_path):
    """Test GPU pipeline with a single image."""
    input_dir = test_image.parent
    output_dir = tmp_path / "outputs"

    # Run the GPU pipeline
    result = run_full_workflow_parallel(
        input_dir=input_dir,
        output_root=output_dir,
        include_hash_analysis=True,
        use_gpu=True,
        max_workers=1
    )

    # Verify results
    assert "processed" in result
    assert len(result["processed"]) == 1
    assert "total_processing_time" in result
    assert result["total_processing_time"] > 0

    # Check GPU status
    if TORCH_AVAILABLE:
        assert result["gpu_available"] in [True, False]
        assert result["device_used"] in ["cuda", "cpu", "cuda:0"]

    # Verify output files exist
    processed = result["processed"][0]
    output_path = Path(processed["output_dir"])
    assert output_path.exists()

    # Check layers were created
    layers_dir = output_path / "layers"
    assert layers_dir.exists()

    # Verify summary.json
    summary_path = Path(processed["summary"])
    assert summary_path.exists()
    with open(summary_path, 'r') as f:
        summary = json.load(f)
    assert "layers" in summary
    assert len(summary["layers"]) > 0


def test_gpu_pipeline_parallel_processing(input_dir_with_images, tmp_path):
    """Test parallel processing of multiple images."""
    output_dir = tmp_path / "outputs"

    # Run with parallel workers
    result = run_full_workflow_parallel(
        input_dir=input_dir_with_images,
        output_root=output_dir,
        include_hash_analysis=False,  # Skip analysis for speed
        use_gpu=True,
        max_workers=2
    )

    # Verify all images were processed
    assert len(result["processed"]) == 3

    # Check that outputs exist for each image
    for item in result["processed"]:
        assert Path(item["output_dir"]).exists()
        assert Path(item["summary"]).exists()


def test_gpu_transformations():
    """Test individual GPU-accelerated transformations."""
    # Create test image with some variation
    test_img = Image.new('RGB', (128, 128), color=(128, 128, 128))
    # Add some variation to make transformations visible
    pixels = np.array(test_img)
    pixels[50:100, 50:100] = [200, 150, 100]
    pixels[20:40, 80:120] = [100, 200, 150]
    test_img = Image.fromarray(pixels.astype(np.uint8))

    # Test each transformation
    transforms = [
        (_apply_fawkes_like_gpu, "Fawkes"),
        (_apply_photoguard_like_gpu, "PhotoGuard"),
        (_apply_mist_like_gpu, "Mist"),
        (_apply_nightshade_like_gpu, "Nightshade"),
    ]

    for transform_func, name in transforms:
        result = transform_func(test_img)
        assert isinstance(result, Image.Image)
        assert result.size == test_img.size

        # Verify transformation actually changed the image
        orig_array = np.array(test_img)
        result_array = np.array(result)
        assert not np.array_equal(orig_array, result_array), f"{name} transformation didn't change image"


def test_watermark_operations():
    """Test watermarking operations."""
    test_img = Image.new('RGB', (128, 128), color=(128, 128, 128))

    # Test invisible watermark
    watermarked = _apply_invisible_watermark_vectorized(test_img, "test")
    assert isinstance(watermarked, Image.Image)
    assert watermarked.size == test_img.size

    # Test tree-ring watermark
    tree_ring = _apply_tree_ring_gpu(test_img, frequency=5.0, amplitude=10.0)
    assert isinstance(tree_ring, Image.Image)
    assert tree_ring.size == test_img.size




def test_cpu_fallback(test_image, tmp_path):
    """Test that CPU fallback works when GPU is disabled."""
    input_dir = test_image.parent
    output_dir = tmp_path / "outputs_cpu"

    # Run with GPU disabled
    result = run_full_workflow_parallel(
        input_dir=input_dir,
        output_root=output_dir,
        include_hash_analysis=False,
        use_gpu=False,  # Force CPU mode
        max_workers=1
    )

    assert len(result["processed"]) == 1
    assert result["device_used"] in ["cpu", "None"]

    # Verify output exists
    output_path = Path(result["processed"][0]["output_dir"])
    assert output_path.exists()


def test_performance_comparison(test_image, tmp_path):
    """Compare performance between GPU and CPU modes."""
    input_dir = test_image.parent

    # Time CPU version
    output_cpu = tmp_path / "outputs_cpu"
    start_cpu = time.perf_counter()
    result_cpu = run_full_workflow_parallel(
        input_dir=input_dir,
        output_root=output_cpu,
        include_hash_analysis=False,
        use_gpu=False,
        max_workers=1
    )
    time_cpu = time.perf_counter() - start_cpu

    # Time GPU version (if available)
    if TORCH_AVAILABLE:
        output_gpu = tmp_path / "outputs_gpu"
        start_gpu = time.perf_counter()
        result_gpu = run_full_workflow_parallel(
            input_dir=input_dir,
            output_root=output_gpu,
            include_hash_analysis=False,
            use_gpu=True,
            max_workers=1
        )
        time_gpu = time.perf_counter() - start_gpu

        print(f"\nPerformance Comparison:")
        print(f"CPU Time: {time_cpu:.3f}s")
        print(f"GPU Time: {time_gpu:.3f}s")
        if time_gpu < time_cpu:
            print(f"GPU Speedup: {time_cpu/time_gpu:.2f}x")
    else:
        print(f"\nCPU Time: {time_cpu:.3f}s (GPU not available)")


def test_workflow_config():
    """Test different workflow configurations."""
    config = ProtectionWorkflowConfig(
        enable_fawkes=True,
        enable_photoguard=False,
        enable_mist=True,
        enable_nightshade=False,
        watermark_strategy="tree-ring",
        tree_ring_frequency=7.0,
        tree_ring_amplitude=15.0,
        enable_stegano_embed=True,
        stegano_message="Test message",
        enable_c2pa_manifest=False
    )

    assert config.enable_fawkes == True
    assert config.enable_photoguard == False
    assert config.watermark_strategy == "tree-ring"
    assert config.tree_ring_frequency == 7.0


@pytest.mark.integration
def test_mona_lisa_processing(tmp_path):
    """Test processing the actual Mona Lisa image from input folder."""
    input_dir = Path("input")
    output_dir = tmp_path / "mona_lisa_output"

    # Check if Mona Lisa exists
    mona_lisa_path = input_dir / "Mona_Lisa,_by_Leonardo_da_Vinci,_from_C2RMF_retouched.jpg"
    if not mona_lisa_path.exists():
        pytest.skip("Mona Lisa image not found in input folder")

    # Process with GPU pipeline
    start_time = time.perf_counter()
    result = run_full_workflow_parallel(
        input_dir=input_dir,
        output_root=output_dir,
        include_hash_analysis=True,
        use_gpu=True,
        max_workers=1
    )
    processing_time = time.perf_counter() - start_time

    # Verify processing completed
    assert len(result["processed"]) == 1
    assert "Mona_Lisa" in result["processed"][0]["image"]

    # Check output structure
    output_path = Path(result["processed"][0]["output_dir"])
    assert output_path.exists()

    # Verify all layers created
    layers_dir = output_path / "layers"
    layer_folders = list(layers_dir.iterdir())
    assert len(layer_folders) >= 5  # At least original + 4 protection layers

    # Check summary contains GPU acceleration info
    with open(Path(result["processed"][0]["summary"]), 'r') as f:
        summary = json.load(f)

    # Verify processing times are recorded
    for layer in summary["layers"]:
        if layer["stage"] != "original":
            if "processing_time" in layer:
                assert layer["processing_time"] > 0
                if "gpu_accelerated" in layer:
                    print(f"{layer['stage']}: {layer['processing_time']:.3f}s (GPU: {layer['gpu_accelerated']})")

    print(f"\nTotal processing time: {processing_time:.2f}s")
    print(f"Device used: {result.get('device_used', 'unknown')}")
    print(f"GPU available: {result.get('gpu_available', False)}")


if __name__ == "__main__":
    # Run specific test with actual image
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    test_mona_lisa_processing(Path("test_outputs"))