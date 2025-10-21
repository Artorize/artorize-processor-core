# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Python Version Requirement

**IMPORTANT**: This project requires Python 3.11.x (specifically 3.11.9 or compatible).
The `blockhash` library dependency chain (specifically `future==0.18.2` required by `pytineye`) is not compatible with Python 3.12+ due to the removal of the `imp` module.

**Always use `py -3.11`** (not `py -3` or `python3`) for all Python commands to ensure compatibility.

## Core Commands

### Running the Pipeline
```powershell
# Main protection pipeline (processes images from input/ to outputs/)
py -3.11 -m artorize_runner.protection_pipeline

# GPU-accelerated pipeline with parallel processing
py -3.11 -m artorize_runner.protection_pipeline_gpu

# GPU pipeline with custom options
py -3.11 -m artorize_runner.protection_pipeline_gpu --workers 4 --no-gpu  # Disable GPU
py -3.11 -m artorize_runner.protection_pipeline_gpu --multiprocessing     # Use multiprocessing
py -3.11 -m artorize_runner.protection_pipeline_gpu --no-analysis        # Skip hash analysis

# CLI for single image analysis
py -3.11 -m artorize_runner.cli path\to\image.jpg --json-out report.json

# Start HTTP gateway server (FastAPI on port 8765)
py -3.11 -m artorize_gateway
```

### Testing
```powershell
# Run all tests with proper PYTHONPATH
$env:PYTHONPATH='.'
pytest -q
Remove-Item Env:PYTHONPATH

# Run specific test file
$env:PYTHONPATH='.'
pytest tests/test_protection_pipeline.py -v
Remove-Item Env:PYTHONPATH

# Run specific test function
$env:PYTHONPATH='.'
pytest tests/test_gpu_pipeline.py::test_mona_lisa_processing -v -s
Remove-Item Env:PYTHONPATH
```

### Dependencies
```powershell
# Install all dependencies
py -3.11 -m pip install -r requirements.txt

# Check installed packages
py -3.11 -m pip list
```

## Architecture Overview

### Project Structure
The codebase implements an image protection pipeline that applies multiple adversarial perturbations and watermarks to protect images from unauthorized AI training.

**Key Components:**
- `artorize_runner/`: Core pipeline orchestration
  - `protection_pipeline.py`: Main workflow (sequential stage application)
  - `protection_pipeline_gpu.py`: GPU-accelerated variant with parallel batch processing
  - `cli.py`: Single-image analysis command-line interface
  - `config.py`: Configuration management (JSON/TOML + environment variables)
  - `core.py`: Base processor abstractions and pipeline runner
  - `c2pa_metadata.py`: C2PA manifest embedding for provenance tracking

- `processors/`: Reference protection algorithm implementations
  - `poison_mask/`: Dual-mask processor for reversible protection layering

- `artorize_gateway/`: FastAPI server (port 8765) for HTTP-based job submission
  - `app.py`: Main FastAPI application with job queue system
  - `similarity_routes.py`: Image similarity/hash search endpoints
  - `sac_routes.py`: SAC encoding endpoints for mask transmission
  - `sac_encoder.py`: SAC v1 binary encoding utility with parallel processing
  - `callback_client.py`: Async callback delivery for job completion
  - `image_storage.py`: CDN/S3/local storage uploader (includes SAC mask upload)

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
4. **Poison Mask Generation**:
   - Per-stage masks (optional): Generated between each protection layer if `enable_poison_mask=true`
     - Saved as PNG only (SAC encoding skipped for performance)
   - **Final comparison mask (MANDATORY)**: ALWAYS generated comparing final protected image to original
     - This mask is required for provenance tracking and cannot be disabled
     - Provides complete reconstruction path from protected image back to original
     - Generated regardless of `enable_poison_mask` setting
     - **SAC encoding only for final comparison** (sent to backend)
   - SAC encoding is automatic for final comparison (2-10ms per mask)
5. **Output Generation**:
   - Each stage saved to `outputs/<image-stem>/layers/`
   - Mask images showing pixel deltas between stages
   - **SAC-encoded masks** in `outputs/<image-stem>/poison_mask/`
   - **Final comparison SAC mask is ALWAYS included** (mandatory for all processed images)
   - `summary.json` with full manifest (includes SAC paths)
   - `analysis.json` with processor results

### Configuration System
Protection workflow configured via `ProtectionWorkflowConfig` dataclass. Configuration can be loaded from:
- JSON or TOML files (via `load_processor_config()`)
- Environment variables with `ARTORIZE_RUNNER_` prefix (nested with `__`)
- Programmatic instantiation

**Key settings:**
- Toggle individual protection layers (`enable_fawkes`, `enable_photoguard`, `enable_mist`, `enable_nightshade`)
- Watermark strategy (`invisible-watermark`, `tree-ring`, or `None`)
- C2PA manifest embedding (`enable_c2pa_manifest`)
- Per-stage poison mask generation (`enable_poison_mask`) - controls optional intermediate masks
  - Note: Final comparison mask is ALWAYS generated regardless of this setting

### Key Implementation Details
- **Reproducibility**: Fixed NumPy seed (20240917) ensures deterministic transformations
- **Resolution handling**: Working copies processed at MAX_STAGE_DIM=512, full resolution preserved in final outputs
- **Sequential layering**: Each protection stage builds on the previous result (not the original)
- **Poison mask generation**: Dual-plane (hi/lo) delta masks for reversible protection
  - **MANDATORY final comparison mask**: Every processed image generates a final mask comparing the protected output to the original
  - Optional per-stage masks: Can be enabled/disabled via `enable_poison_mask` config (PNG only, no SAC)
  - **SAC encoding optimization**: Only final comparison mask is encoded to SAC format (saves 2-10ms per stage)
  - Automatically encoded to **SAC v1 binary format** (24-byte header + int16 payloads)
  - SAC files are CDN-ready with immutable caching headers
  - File naming: `XX-final-comparison_mask.sac` (only final comparison has SAC file)
- **Gateway callbacks**: Include `sac_mask_url` in completion payload for frontend consumption (always present, points to final comparison)
- **Testing**: All tests require `PYTHONPATH='.'` environment variable to resolve imports correctly

### SAC Protocol
**SAC (Simple Array Container) v1** is a compact binary format for shipping dual int16 arrays:
- **Format**: 24-byte header + two int16 array payloads (little-endian)
- **Size**: ~2MB uncompressed, ~200KB-1MB with CDN Brotli compression
- **Speed**: 2-10ms encoding, parallelized for batch operations
- **Specification**: See `sac_v_1_cdn_mask_transfer_protocol.md`
- **Endpoints**: `/v1/sac/encode`, `/v1/sac/encode/batch`, `/v1/sac/encode/job/{id}`