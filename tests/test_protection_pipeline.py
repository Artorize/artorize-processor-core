from __future__ import annotations

import json
from pathlib import Path

from artorize_runner.protection_pipeline import run_full_workflow


def test_run_full_workflow_creates_layers_and_summary():
    output_root = Path("outputs")
    result = run_full_workflow(output_root=output_root)
    processed = result.get("processed", [])
    assert processed, "No images were processed."

    for item in processed:
        summary_path = Path(item["summary"])
        assert summary_path.exists(), "Summary JSON was not created."
        data = json.loads(summary_path.read_text())

        analysis_path = data.get("analysis")
        if analysis_path:
            assert Path(analysis_path).exists(), "Analysis JSON missing."

        layers = data.get("layers", [])
        stage_names = [layer.get("stage") for layer in layers]
        assert "fawkes" in stage_names
        assert "photoguard" in stage_names
        assert "mist" in stage_names
        assert "nightshade" in stage_names
        assert "invisible-watermark" in stage_names

        for layer in layers:
            # Check layer image exists (except for final-comparison which has no path)
            layer_path = layer.get("path")
            if layer.get("stage") != "final-comparison":
                assert layer_path and Path(layer_path).exists(), "Layer image missing."

            # Check for poison mask SAC files (except original and final-comparison)
            if layer.get("stage") not in ("original", "final-comparison"):
                sac_path = layer.get("poison_mask_sac_path")
                assert sac_path and Path(sac_path).exists(), "Poison mask SAC file missing."

        projects = {project["name"]: project for project in data.get("projects", [])}
        assert projects["Fawkes"]["applied"] is True
        assert projects["PhotoGuard"]["applied"] is True
        assert projects["Mist v2"]["applied"] is True
        assert projects["Nightshade (research code)"]["applied"] is True
        assert projects["invisible-watermark"]["applied"] is True
