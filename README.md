# Artorize Processor Core

Image protection pipeline that applies multiple adversarial perturbations (Fawkes, PhotoGuard, Mist, Nightshade) and watermarking techniques to protect images from unauthorized AI training.

## Requirements

**Python Version**: 3.12.10 (required for blockhash compatibility)

> **Note**: This project requires Python 3.12.10 or compatible 3.12.x versions. The `blockhash` library is not compatible with Python 3.13+.

## Quick Start

### Installation
```powershell
py -3.12 -m pip install -r requirements.txt
```

### Basic Usage
```powershell
# Process images from input/ to outputs/
py -3.12 -m artorize_runner.protection_pipeline

# GPU-accelerated processing
py -3.12 -m artorize_runner.protection_pipeline_gpu

# Single image analysis
py -3.12 -m artorize_runner.cli path\to\image.jpg --json-out report.json

# Start HTTP API server
py -3.12 -m artorize_gateway --host 0.0.0.0 --port 8000
```

### Testing
```powershell
$env:PYTHONPATH='.'
pytest -q
Remove-Item Env:PYTHONPATH
```

## Architecture

### Modules
- **`artorize_runner/`** - Core pipeline and CLI tools
- **`artorize_gateway/`** - FastAPI HTTP server for web integration
- **`processors/`** - Reference implementations of protection algorithms

### Protection Pipeline
1. **Input Processing** - Images from `input/` directory
2. **Analysis** (optional) - Metadata, perceptual hashing, steganography detection
3. **Protection Layers** (sequential):
   - Fawkes (Gaussian noise cloaking)
   - PhotoGuard (blur + edge blending)
   - Mist (color/contrast enhancement)
   - Nightshade (pixel shifting + noise)
   - Watermarking (invisible LSB or tree-ring)
   - C2PA manifest embedding
4. **Output** - Protected images, masks, and analysis in `outputs/<image-stem>/`

## Configuration

Protection workflow can be configured via JSON/TOML files or environment variables:

```json
{
  "workflow": {
    "enable_fawkes": true,
    "enable_photoguard": true,
    "enable_mist": true,
    "enable_nightshade": true,
    "watermark_strategy": "invisible-watermark",
    "enable_c2pa_manifest": true
  }
}
```

Environment variables use `ARTORIZE_RUNNER_` prefix:
```bash
ARTORIZE_RUNNER_WORKFLOW__ENABLE_FAWKES=true
ARTORIZE_RUNNER_WORKFLOW__WATERMARK_STRATEGY=tree-ring
```

## Documentation

- **API Reference**: See `documentation-processor.md` for complete HTTP API documentation
- **Development Guide**: See module-specific README files in subdirectories

## Development

### Setup
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Code Style
- Follow PEP 8, 4-space indentation, 88-100 char lines
- Use type hints and docstrings for public APIs
- Run tests before committing: `pytest -q`
