# Artorize Runner

Core image protection pipeline module that processes images through multiple adversarial protection layers.

## Usage

### Command Line

```powershell
# Main protection pipeline (auto-detects GPU)
py -3.12 -m artorize_runner.pipeline

# Custom options
py -3.12 -m artorize_runner.pipeline --workers 4       # Adjust parallel workers
py -3.12 -m artorize_runner.pipeline --cpu-only        # Force CPU mode
py -3.12 -m artorize_runner.pipeline --no-analysis     # Skip hash analysis

# Single image analysis
py -3.12 -m artorize_runner.cli path\to\image.jpg --json-out report.json
```

**The pipeline automatically detects GPU availability and uses the optimal backend.**

### Python API

```python
from artorize_runner.protection_pipeline import run_full_workflow, ProtectionWorkflowConfig

# Custom configuration
config = ProtectionWorkflowConfig(
    enable_fawkes=True,
    enable_photoguard=False,
    watermark_strategy="tree-ring"
)

# Process images
result = run_full_workflow(
    input_dir="input",
    output_root="outputs",
    config=config
)
```

## Configuration

Configure protection layers via `ProtectionWorkflowConfig`:

- `enable_fawkes: bool = True` - Gaussian noise cloaking
- `enable_photoguard: bool = True` - Blur + edge blending
- `enable_mist: bool = True` - Color/contrast enhancement
- `enable_nightshade: bool = True` - Pixel shifting + noise
- `watermark_strategy: str = "invisible-watermark"` - "invisible-watermark" or "tree-ring"
- `enable_stegano_embed: bool = False` - Steganographic message embedding
- `enable_c2pa_manifest: bool = True` - C2PA provenance manifest

## Output Structure

```
outputs/<image-stem>/
├── summary.json          # Complete processing manifest
├── analysis.json         # Hash analysis (if enabled)
├── layers/
│   ├── 00-original/      # Unmodified input
│   ├── 01-fawkes/        # + mask image
│   ├── 02-photoguard/    # + mask image
│   ├── 03-mist/          # + mask image
│   ├── 04-nightshade/    # + mask image
│   └── 05-watermark/     # + mask image
└── c2pa/                 # C2PA manifest files
```

## Available Processors

### Analysis Processors
- **metadata** - EXIF/image metadata extraction
- **imagehash** - Perceptual hashing (pHash, aHash, dHash, wHash, colorhash)
- **stegano** - LSB steganography detection
- **tineye** - Reverse image search (requires API key)

### Protection Layers
- **fawkes** - Gaussian noise cloaking to fool facial recognition
- **photoguard** - Blur and edge blending to prevent image editing
- **mist** - Color/contrast perturbations
- **nightshade** - Pixel shifting and noise injection
- **invisible-watermark** - LSB text watermark embedding
- **tree-ring** - Radial watermark pattern
- **stegano-embed** - Hidden message embedding
- **c2pa-manifest** - Content provenance and AI training signals
