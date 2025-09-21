import time
from pathlib import Path

import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUTPUTS_ROOT = (ROOT / "outputs").resolve()

from fastapi.testclient import TestClient
from PIL import Image

from artscraper_gateway import GatewayConfig, create_app


INPUT_IMAGE = Path("input") / "Mona_Lisa,_by_Leonardo_da_Vinci,_from_C2RMF_retouched.jpg"


def _wait_for_completion(client: TestClient, job_id: str, timeout: float = 90.0) -> str:
    deadline = time.time() + timeout
    status = "queued"
    while time.time() < deadline:
        resp = client.get(f"/v1/jobs/{job_id}")
        resp.raise_for_status()
        payload = resp.json()
        status = payload["status"]
        if status == "done":
            return status
        if status == "error":
            pytest.fail(f"job errored: {payload.get('error')}")
        time.sleep(1.0)
    pytest.fail("job did not reach completion in time")
    return status


def test_job_lifecycle_with_input_image(tmp_path):
    assert INPUT_IMAGE.is_file(), "expected sample image in input/"

    config = GatewayConfig(base_dir=tmp_path / "jobs", worker_concurrency=1)
    app = create_app(config)

    with TestClient(app) as client:
        with INPUT_IMAGE.open("rb") as handle:
            response = client.post(
                "/v1/jobs",
                files={"file": (INPUT_IMAGE.name, handle, "image/jpeg")},
                data={"include_protection": "false", "include_hash_analysis": "false"},
            )
        assert response.status_code == 200
        job_id = response.json()["job_id"]

        _wait_for_completion(client, job_id)

        result_resp = client.get(f"/v1/jobs/{job_id}/result")
        assert result_resp.status_code == 200
        result = result_resp.json()
        assert result["job_id"] == job_id
        summary = result["summary"]
        image_path = Path(summary["image"])
        assert image_path.is_file()
        assert image_path.suffix.lower() in {".jpg", ".jpeg", ".png"}
        layers = summary["layers"]
        assert layers and layers[0]["stage"] == "original"
        assert result["analysis"] is None

        output_dir = Path(result["output_dir"]).resolve()
        assert OUTPUTS_ROOT in output_dir.parents
        for entry in layers:
            assert OUTPUTS_ROOT in Path(entry["path"]).resolve().parents

        original_resp = client.get(f"/v1/jobs/{job_id}/layers/original")
        assert original_resp.status_code == 200
        assert original_resp.headers["content-type"].startswith("image/")


def test_job_with_full_protection(tmp_path):
    img_path = tmp_path / "small.png"
    Image.new("RGB", (32, 32), color=(20, 30, 40)).save(img_path)

    config = GatewayConfig(base_dir=tmp_path / "jobs_full", worker_concurrency=1)
    app = create_app(config)

    with TestClient(app) as client:
        with img_path.open("rb") as handle:
            response = client.post(
                "/v1/jobs",
                files={"file": ("small.png", handle, "image/png")},
            )
        assert response.status_code == 200
        job_id = response.json()["job_id"]

        _wait_for_completion(client, job_id, timeout=30.0)

        result_resp = client.get(f"/v1/jobs/{job_id}/result")
        assert result_resp.status_code == 200
        payload = result_resp.json()
        summary = payload["summary"]
        stage_names = {entry["stage"] for entry in summary["layers"]}
        assert {"fawkes", "photoguard", "mist", "nightshade", "invisible-watermark"}.issubset(stage_names)

        output_dir = Path(payload["output_dir"]).resolve()
        assert OUTPUTS_ROOT in output_dir.parents
        for entry in summary["layers"]:
            assert OUTPUTS_ROOT in Path(entry["path"]).resolve().parents

        layer_resp = client.get(f"/v1/jobs/{job_id}/layers/fawkes")
        assert layer_resp.status_code == 200
        assert layer_resp.headers["content-type"].startswith("image/")

        delete_resp = client.delete(f"/v1/jobs/{job_id}")
        assert delete_resp.status_code == 200



