# Artscraper Processor Pipeline Guide

This guide walks through the end-to-end pipeline that Artscraper uses to analyse images and apply layered protection transforms. It covers environment setup, running the workflow, understanding each processor stage, and interpreting the outputs that land in `outputs/`.

## What the pipeline does
- Collects image metadata, perceptual hashes, and LSB steganography findings via the reusable processor stack in `artscraper_runner.processors`.
- Applies a configurable stack of protection layers (default: Fawkes, PhotoGuard, Mist, Nightshade, invisible-watermark) and saves both the image and a change mask for each stage.
- Builds an inventory linking every known upstream project to the evidence produced locally, helping you report coverage.
- Emits machine-readable JSON (`analysis.json`, `summary.json`) plus on-disk derivatives under `outputs/<image-stem>/`.

## Requirements
- Python 3.10 or newer (Windows `py -3` or POSIX `python3`).
- Pillow, NumPy, SciPy, PyWavelets, piexif, rawpy (optional, for RAW files), Stegano, and support libs already listed in `artscraper_runner/README.md`.
- Runtime dependencies (blockhash, dhash, imagehash, Stegano, pytineye, etc.) are installed from PyPI; see  `requirements.txt` for the curated list. 
- Optional: `TINEYE_API_KEY` in the environment if you plan to extend the run with TinEye lookups.

> Tip: follow the repo-wide virtual environment instructions before installing dependencies. On Windows:
>
> ```powershell
> py -3 -m venv .venv
> .\.venv\Scripts\Activate.ps1
> pip install --upgrade pip
> pip install -r ..\\requirements.txt
> ```

## Prepare your inputs
1. Place one or more images (PNG, JPEG, TIFF, RAW, etc.) in the `input/` directory at the repo root. Use descriptive filenames; they become the output folder names.
2. Clear out old runs in `outputs/` if you want a clean slate. The pipeline will overwrite per-image directories but will keep unrelated artefacts.

## Run the workflow
The pipeline module is executable. From the repo root run:

```powershell
py -3 -m artscraper_runner.protection_pipeline
```

or on POSIX shells:

```bash
python -m artscraper_runner.protection_pipeline
```

The script prints a JSON summary listing every processed image, its output directory, and the summary file path. By default it:
- Reads from `input/`.
- Writes to `outputs/`.
- Runs the metadata/hash/stegano analysis stack.

### Custom runs from Python
Import and call `run_full_workflow` if you need to customise directories or toggle analysis:

```python
from pathlib import Path
from artscraper_runner.protection_pipeline import run_full_workflow

run_full_workflow(
    input_dir=Path("/path/to/images"),
    output_root=Path("/tmp/artscraper-out"),
    include_hash_analysis=False,
)
```

- Flip `include_hash_analysis` to `False` to skip the metadata/hash/stegano processors when you only want layered perturbations.
- Pass a custom `ProtectionWorkflowConfig` when you want to switch layers (e.g., enable the tree-ring watermark or the stegano export stage).

```python
from artscraper_runner.protection_pipeline import ProtectionWorkflowConfig, run_full_workflow

config = ProtectionWorkflowConfig(
    watermark_strategy="tree-ring",
    enable_stegano_embed=True,
    stegano_message="Protected by artscraper",
)
run_full_workflow(config=config)
```

## Processor breakdown

### Analysis processors (executed when `include_hash_analysis=True`)
- `metadata`: Uses Pillow to report basic properties and attempts to decode EXIF tags.
-  `imagehash`: Computes average, perceptual, difference, and wavelet hashes via the PyPI `imagehash` package. 
- `dhash`: Emits Ben Hoyt's row/column hashes plus the combined hexadecimal string.
- `blockhash`: Generates 8x8 and 16x16 blockhash fingerprints after normalising the image to RGB.
- `stegano`: Tries to reveal an LSB message using the Stegano `lsb` helper; absence of a message is reported without failing the run.
- `tineye`: Not part of this workflow by default, but you can add it by calling `build_processors(include_tineye=True)` before invoking `run_pipeline`.

Each processor returns a `ProcessorResult` recorded in `analysis.json` and echoed in the `projects` section of `summary.json`.

### Protection stages
The active protection layers are assembled from `ProtectionWorkflowConfig` via `_build_stage_sequence` in `protection_pipeline.py`. The default configuration keeps the familiar per-image stack:

1. **original** - The untouched source image saved for reference.
2. **fawkes** - Adds seeded Gaussian noise to approximate cloaking perturbations.
3. **photoguard** - Blends a Gaussian blur with edge detection before mixing with the working image.
4. **mist** - Boosts colour variance, contrast, and sharpness to mimic Mist v2 style perturbations.
5. **nightshade** - Applies a horizontal pixel roll and structured noise to simulate poisoning patterns.
6. **invisible-watermark** - Embeds ASCII text into the least-significant bits of the pixel buffer.

Optional layers you can toggle through the config:

- **tree-ring** – Adds a radial provenance watermark based on sinusoidal intensity modulation.
- **stegano-embed** – Writes a small payload into the RGB LSB plane for downstream verification.

Every exported stage is saved at full resolution alongside a `<stage>_mask.png` file that visualises the pixel deltas against the previous step.

## Output layout
For each input image `<stem>` the pipeline writes to `outputs/<stem>/`:

```
outputs/
  <stem>/
    analysis.json      # Processor results (present when analysis enabled)
    summary.json       # Master manifest of layers and project coverage
    layers/
      00-original/
        <stem>.<ext>
      01-fawkes/
        <stem>.<ext>
        <stem>_fawkes_mask.png
      02-photoguard/
        <stem>.<ext>
        <stem>_photoguard_mask.png
      03-mist/
        <stem>.<ext>
        <stem>_mist_mask.png
      04-nightshade/
        <stem>.<ext>
        <stem>_nightshade_mask.png
      05-invisible-watermark/
        <stem>.<ext>
        <stem>_invisible-watermark_mask.png
      06-tree-ring/            # optional, when enabled in config
        ...
      07-stegano-embed/        # optional, when enabled in config
        ...
```

`summary.json` merges three views:
- `image` / `analysis` - Absolute paths so you can locate artefacts quickly.
- `layers` - Ordered list of stage descriptors, processing canvas size, and file locations.
- `projects` - Coverage table keyed by the broader research projects cloned into the repo, with `applied`, `layer_path`, or `evidence` fields populated when the project contributed to the run.

## Consuming the results
- Feed the hashes and metadata in `analysis.json` into deduplication or similarity search workflows.
- Use the staged images under `layers/` for qualitative review or to publish protected versions.
- The `projects` table in `summary.json` is designed for reporting - drop it into dashboards or attach it to compliance documentation.

## Troubleshooting and tips
- Missing dependency? The corresponding processor will mark `ok=false` and include an `error` message in `analysis.json`; install the package and rerun.
- RAW images: ensure `rawpy` is installed; otherwise the fallback Pillow loader may fail.
- Large inputs: outputs preserve the original resolution, but you can raise or lower `MAX_STAGE_DIM` inside `protection_pipeline.py` if you need sharper working copies.
- TinEye: set `TINEYE_API_KEY` and manually add the processor when you need reverse-image search evidence.
- Reproducibility: the transforms use a fixed NumPy random seed (`20240917`), so re-running the pipeline yields identical perturbations, which simplifies diffing and regression testing.


