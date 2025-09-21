# Artscraper Runner

A lightweight CLI that runs a single image (png/jpeg/raw) through the local tools in this repo and aggregates results to JSON.

## Quick Start
- Install dependencies (Windows): `py -3 -m pip install -r ..\requirements.txt`
- Optional TinEye search:
  - Set `TINEYE_API_KEY` env var; the `pytineye` client is now pulled from PyPI.

## Run
- Basic: `py -3 -m artscraper_runner.cli path\to\image.jpg`
- Save JSON: `py -3 -m artscraper_runner.cli path\to\image.jpg --json-out report.json`
- Include TinEye: `set TINEYE_API_KEY=...` then `py -3 -m artscraper_runner.cli image.jpg --tineye`

## What Runs
- Metadata: format, size, mode, EXIF
- Hashes: `imagehash` (a/ph/d/whash), `dhash` (row/col+hex), `blockhash` (8/16)
- Steganography: LSB reveal (best-effort, non-fatal if none)
- TinEye (optional): top matches if API key is provided

Notes
- RAW formats are attempted via `rawpy` when Pillow cannot open the file.
- Processors are optional; if a dependency is missing, it is skipped with a reason.

## Remote/Web Usage
- To trigger the runner via HTTP, deploy the FastAPI gateway described in `../ARTSCRAPER_WEB_INTEGRATION.md` and `../artscraper_gateway/README.md`.
- Submit images with `POST /v1/jobs` and download the resulting JSON/layers from `outputs/<job-id>/`.
