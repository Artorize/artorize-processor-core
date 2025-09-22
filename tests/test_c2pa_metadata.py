from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from artorize_runner.c2pa_metadata import C2PAManifestConfig


def test_manifest_has_training_and_license_labels():
    config = C2PAManifestConfig()
    manifest = config.build_manifest(asset_title="sample")
    labels = {assertion["label"] for assertion in manifest["assertions"]}
    assert "cawg.training-mining" in labels
    assert "com.artscraper.license" in labels
    license_assertion = next(
        item for item in manifest["assertions"] if item["label"] == "com.artscraper.license"
    )
    assert license_assertion["data"]["license_sha256"] == config.license.checksum()


def test_xmp_packet_includes_policy_url():
    config = C2PAManifestConfig()
    xmp = config.build_xmp_packet(asset_title="sample")
    assert config.license.license_url in xmp
    assert "plus:DataMining=\"allowed\"" in xmp
