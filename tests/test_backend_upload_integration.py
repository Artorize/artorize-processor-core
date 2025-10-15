"""Integration test for backend upload with SAC mask generation."""

import json
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from artorize_gateway.app import _process_job, _send_callback_on_completion, GatewayState, GatewayConfig, JobRecord
from artorize_gateway.backend_upload import BackendUploadClient


@pytest.fixture
def test_image():
    """Get the test image from input directory."""
    image_path = Path("input/Mona_Lisa,_by_Leonardo_da_Vinci,_from_C2RMF_retouched.jpg")
    if not image_path.exists():
        pytest.skip(f"Test image not found: {image_path}")
    return image_path


@pytest.fixture
def temp_output(tmp_path):
    """Create temporary output directory."""
    output_dir = tmp_path / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


@pytest.fixture
def temp_input(tmp_path, test_image):
    """Create temporary input directory with test image."""
    input_dir = tmp_path / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    # Copy test image to temp input
    dest_path = input_dir / test_image.name
    shutil.copy2(test_image, dest_path)

    return dest_path


def test_full_pipeline_generates_sac_masks(temp_input, temp_output):
    """Test that the full pipeline generates SAC masks correctly."""
    # Create job record
    job = JobRecord(
        job_id="test-job-123",
        input_path=temp_input,
        input_dir=temp_input.parent,
        output_root=temp_output,
        include_hash_analysis=True,
        include_protection=True,
        enable_tineye=False,
        processors=None,
    )

    # Process the job
    result = _process_job(job)

    # Verify result structure
    assert result is not None
    assert result.summary is not None
    assert "layers" in result.summary

    layers = result.summary["layers"]
    assert len(layers) > 0

    # Find the last protection layer with SAC mask
    final_layer = None
    for layer in reversed(layers):
        if layer.get("has_sac_mask"):
            final_layer = layer
            break

    assert final_layer is not None, f"No layer with SAC mask found in {len(layers)} layers"
    assert final_layer.get("is_protection_layer"), "Layer should be marked as protection layer"

    # Verify the layer has a path
    final_layer_path = Path(final_layer["path"])
    assert final_layer_path.exists(), f"Final layer image not found: {final_layer_path}"

    # Verify SAC mask is generated
    assert "poison_mask_sac_path" in final_layer, f"SAC mask path not found in layer: {final_layer.keys()}"

    sac_mask_path = Path(final_layer["poison_mask_sac_path"])
    assert sac_mask_path.exists(), f"SAC mask file not found: {sac_mask_path}"
    assert sac_mask_path.suffix == ".sac"

    # Verify SAC file has content
    assert sac_mask_path.stat().st_size > 24, "SAC file too small (should have header + data)"

    print(f"[PASS] Pipeline generated SAC mask: {sac_mask_path}")
    print(f"[PASS] SAC mask size: {sac_mask_path.stat().st_size} bytes")
    print(f"[PASS] Final layer: {final_layer['stage']}")


@pytest.mark.asyncio
async def test_backend_upload_with_real_pipeline(temp_input, temp_output):
    """Test backend upload with real pipeline output including SAC masks."""
    # Create job record
    job = JobRecord(
        job_id="test-job-456",
        input_path=temp_input,
        input_dir=temp_input.parent,
        output_root=temp_output,
        include_hash_analysis=True,
        include_protection=True,
        enable_tineye=False,
        processors=None,
        # Backend upload settings
        backend_url="http://localhost:3002",
        backend_auth_token="test-token-123",
        artist_name="Leonardo da Vinci",
        artwork_title="Mona Lisa",
        artwork_description="Test artwork",
        artwork_tags=["art", "renaissance"],
        watermark_strategy="invisible-watermark",
        watermark_strength=0.5,
    )

    # Process the job
    result = _process_job(job)

    # Verify SAC mask exists using the explicit attribute
    layers = result.summary["layers"]
    final_layer = None
    for layer in reversed(layers):
        if layer.get("has_sac_mask"):
            final_layer = layer
            break

    assert final_layer is not None, f"No layer with SAC mask found in {len(layers)} layers"
    assert final_layer.get("is_protection_layer"), "Layer should be marked as protection layer"
    assert "poison_mask_sac_path" in final_layer

    sac_mask_path = Path(final_layer["poison_mask_sac_path"])
    assert sac_mask_path.exists()

    # Create gateway state with backend upload client
    config = GatewayConfig()
    state = GatewayState(
        config=config,
        queue=None,
        jobs={},
        workers=[],
        callback_client=None,
        storage_uploader=None,
        backend_upload_client=BackendUploadClient(),
    )

    # Mock the backend response
    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.json.return_value = {
        "id": "60f7b3b3b3b3b3b3b3b3b3b3",
        "formats": {
            "original": {"fileId": "file1"},
            "protected": {"fileId": "file2"},
            "mask": {"fileId": "file3"},
        },
    }

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client

        # Create callback client mock
        callback_mock = AsyncMock()
        state.callback_client = callback_mock

        # Simulate callback sending (which triggers backend upload)
        await _send_callback_on_completion(job, result, None, state)

        # Verify backend upload was called
        assert mock_client.post.call_count == 1

        # Verify the call included all required files
        call_kwargs = mock_client.post.call_args[1]
        files = call_kwargs["files"]

        assert "original" in files, "Original image not in upload"
        assert "protected" in files, "Protected image not in upload"
        assert "mask" in files, "SAC mask not in upload"
        assert "analysis" in files, "Analysis JSON not in upload"
        assert "summary" in files, "Summary JSON not in upload"

        # Verify mask file is the correct one
        mask_file_tuple = files["mask"]
        assert mask_file_tuple[0] == sac_mask_path.name

        print(f"[PASS] Backend upload included SAC mask: {sac_mask_path.name}")
        print(f"[PASS] Callback was sent successfully")


def test_final_comparison_layer_has_no_path(temp_input, temp_output):
    """Test that final-comparison layer exists but has no image path."""
    job = JobRecord(
        job_id="test-job-789",
        input_path=temp_input,
        input_dir=temp_input.parent,
        output_root=temp_output,
        include_hash_analysis=True,
        include_protection=True,
        enable_tineye=False,
        processors=None,
    )

    result = _process_job(job)
    layers = result.summary["layers"]

    # Find final-comparison layer
    final_comparison = None
    for layer in layers:
        if layer.get("stage") == "final-comparison":
            final_comparison = layer
            break

    assert final_comparison is not None, "final-comparison layer should exist"
    assert final_comparison["path"] is None, "final-comparison should have None path"

    # But it should still have SAC mask data
    assert "poison_mask_sac_path" in final_comparison, "final-comparison should have SAC mask"

    # Verify the last protection layer with SAC mask is NOT final-comparison
    last_protection = None
    for layer in reversed(layers):
        if layer.get("has_sac_mask") and layer.get("is_protection_layer"):
            last_protection = layer
            break

    assert last_protection is not None, "Should have at least one protection layer with SAC mask"
    assert last_protection["stage"] != "final-comparison", "Last protection layer should not be final-comparison"

    print(f"[PASS] final-comparison layer has None path (expected)")
    print(f"[PASS] Last protection layer is: {last_protection['stage']}")


if __name__ == "__main__":
    # Allow running the test directly for quick debugging
    import sys
    sys.exit(pytest.main([__file__, "-v", "-s"]))
