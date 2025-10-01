# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Python Version Requirement

**IMPORTANT**: This project requires Python 3.12.x (specifically 3.12.10 or compatible).
The `blockhash` library is not compatible with Python 3.13+.

Use `py -3.12` instead of `py -3` for all Python commands.

## Core Commands

### Running the Pipeline
```powershell
# Main protection pipeline (processes images from input/ to outputs/)
py -3.12 -m artorize_runner.protection_pipeline

# GPU-accelerated pipeline with parallel processing
py -3.12 -m artorize_runner.protection_pipeline_gpu

# GPU pipeline with custom options
py -3.12 -m artorize_runner.protection_pipeline_gpu --workers 4 --no-gpu  # Disable GPU
py -3.12 -m artorize_runner.protection_pipeline_gpu --multiprocessing     # Use multiprocessing
py -3.12 -m artorize_runner.protection_pipeline_gpu --no-analysis        # Skip hash analysis

# CLI for single image analysis
py -3.12 -m artorize_runner.cli path\to\image.jpg --json-out report.json
```

### Testing
```powershell
# Run tests with proper PYTHONPATH
$env:PYTHONPATH='.'
pytest -q
Remove-Item Env:PYTHONPATH

# Run specific test module
$env:PYTHONPATH='.'
pytest tests/test_protection_pipeline.py -v
Remove-Item Env:PYTHONPATH
```

### Dependencies
```powershell
# Install all dependencies
py -3.12 -m pip install -r requirements.txt
```

## Architecture Overview

### Project Structure
The codebase implements an image protection pipeline that analyzes images and applies multiple protection layers (Fawkes, PhotoGuard, Mist, Nightshade, watermarks).

**Key Components:**
- `artorize_runner/`: Core pipeline module that orchestrates image processing
  - `protection_pipeline.py`: Main workflow that applies protection stages and generates outputs
  - `processors/`: Analysis modules (metadata, hashing, steganography)
  - `c2pa_metadata.py`: C2PA manifest embedding for provenance tracking

- `processors/`: External protection algorithm implementations (Mist-v2, Nightshade, CorruptEncoder, etc.)

- `artorize_gateway/`: FastAPI server for HTTP-based job submission

### Protection Pipeline Flow
1. **Input Processing**: Images from `input/` directory
2. **Analysis Stage** (optional): Metadata extraction, perceptual hashing, LSB steganography detection
3. **Protection Stages** (sequential):
   - Original (baseline)
   - Fawkes (Gaussian noise cloaking)
   - PhotoGuard (blur + edge blending)
   - Mist (color/contrast enhancement)
   - Nightshade (pixel shifting + noise)
   - Invisible watermark (LSB embedding)
   - Optional: Tree-ring watermark, Stegano embed
4. **Output Generation**:
   - Each stage saved to `outputs/<image-stem>/layers/`
   - Mask images showing pixel deltas between stages
   - `summary.json` with full manifest
   - `analysis.json` with processor results

### Configuration System
Protection workflow configured via `ProtectionWorkflowConfig` dataclass:
- Toggle individual protection layers
- Configure watermark strategies
- Enable C2PA manifest embedding
- Control stegano message embedding

### Key Implementation Details
- Uses fixed NumPy seed (20240917) for reproducible transformations
- Images processed at MAX_STAGE_DIM=512 for working copies
- Full resolution preserved in final outputs
- Protection stages build sequentially on previous results
- Mask generation visualizes incremental changes