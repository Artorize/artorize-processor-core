# Artorize Processor Core

Image protection pipeline that applies multiple adversarial perturbations (Fawkes, PhotoGuard, Mist, Nightshade) and watermarking techniques to protect images from unauthorized AI training.

## Requirements

**Python Version**: 3.12.10 (required for blockhash compatibility)

> **Note**: This project requires Python 3.12.10 or compatible 3.12.x versions. The `blockhash` library is not compatible with Python 3.13+.
> PyTorch does not yet publish wheels for Python 3.13, so GPU acceleration will only install on Python 3.12 builds.

## Production Deployment (Debian/Ubuntu)

**One-liner Auto-Deploy:**
```bash
curl -fsSL https://raw.githubusercontent.com/Artorize/artorize-processor-core/main/deploy.sh | sudo bash
```

This will automatically:
- Install Python 3.12 and system dependencies
- Clone the repository to `/opt/artorize-processor`
- Create a dedicated `artorize` system user
- Set up virtual environment and install all dependencies
- Create two systemd services:
  - **`artorize-processor-gateway`** - FastAPI server with internal job queue (port 8765)
  - **`artorize-processor-runner`** - Optional batch processing service
- Start both services automatically

**Manual Deployment:**
```bash
# Clone the repository
git clone https://github.com/Artorize/artorize-processor-core.git
cd artorize-processor-core

# Run deployment script
sudo bash deploy.sh

# Check service status
sudo systemctl status artorize-processor-gateway
sudo systemctl status artorize-processor-runner
```

**Service Management:**
```bash
# Gateway (required - handles HTTP API and job queue)
sudo systemctl start artorize-processor-gateway
sudo systemctl stop artorize-processor-gateway
sudo systemctl restart artorize-processor-gateway
sudo journalctl -u artorize-processor-gateway -f

# Runner (optional - for batch processing)
sudo systemctl start artorize-processor-runner
sudo systemctl stop artorize-processor-runner
sudo systemctl restart artorize-processor-runner
sudo journalctl -u artorize-processor-runner -f

# Disable runner if not needed (gateway has internal workers)
sudo systemctl disable artorize-processor-runner
```

## Quick Start

### Installation
```powershell
py -3.12 -m pip install -r requirements.txt
```

The requirements file already points pip to the official PyTorch wheel indices (`cu121` for CUDA builds and `cpu` for CPU-only installs). No manual `--index-url` flags are necessary unless you are behind a proxy.

### Basic Usage
```powershell
# Process images from input/ to outputs/
py -3.12 -m artorize_runner.protection_pipeline

# GPU-accelerated processing
py -3.12 -m artorize_runner.protection_pipeline_gpu

# Single image analysis
py -3.12 -m artorize_runner.cli path\to\image.jpg --json-out report.json

# Start HTTP API server (listens on 127.0.0.1:8765)
py -3.12 -m artorize_gateway
```

### GPU Pipeline Checklist
- Confirm you are using Python 3.12.x. On newer interpreters the PyTorch pins are skipped and the GPU pipeline will fall back to CPU mode.
- Ensure CUDA 12.1 drivers (or the CPU-only PyTorch wheel) are available before installing `requirements.txt`.
- If you see `PyTorch stack not available... GPU acceleration disabled`, reinstall PyTorch/torchvision following the quick start above and verify by running  
  `py -3.12 -m artorize_runner.protection_pipeline_gpu --no-analysis --workers 1`.
- The GPU script can also be invoked directly (`py -3.12 artorize_runner\protection_pipeline_gpu.py`) thanks to the updated import guards, though the `-m` module form is preferred.
- For multi-GPU systems set `CUDA_VISIBLE_DEVICES` before launching the pipeline to target a specific device.

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

## HTTP Gateway Server

### Default Configuration

- **Host**: `127.0.0.1` (localhost only)
- **Port**: `8765`

The gateway server listens on `127.0.0.1` by default for security reasons, making it accessible only from the local machine. This prevents unauthorized external access.

### Production Security

**IMPORTANT**: For production deployments, it is **strongly recommended** to use a reverse proxy (such as Nginx or Apache) instead of exposing the gateway directly to the internet.

**Example Nginx Configuration:**

```nginx
server {
    listen 80;
    server_name api.yourdomain.com;

    # Optional: SSL/TLS configuration
    # listen 443 ssl;
    # ssl_certificate /path/to/cert.pem;
    # ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Recommended: Add rate limiting
        limit_req zone=api_limit burst=10 nodelay;

        # Recommended: Add authentication
        # auth_basic "Restricted Access";
        # auth_basic_user_file /etc/nginx/.htpasswd;
    }
}

# Rate limiting zone (add to http block)
# limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;
```

**Benefits of using a reverse proxy:**
- SSL/TLS termination
- Rate limiting and DDoS protection
- Authentication and access control
- Load balancing across multiple gateway instances
- Static file serving and caching
- Request logging and monitoring

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
