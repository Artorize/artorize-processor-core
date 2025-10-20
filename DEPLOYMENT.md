# Artorize Processor - Deployment Guide

This guide provides instructions for deploying the Artorize image protection processor on Debian 12 servers.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Manual Deployment](#manual-deployment)
- [Configuration](#configuration)
- [Service Management](#service-management)
- [SSL/TLS Setup](#ssltls-setup)
- [Monitoring & Logging](#monitoring--logging)
- [Troubleshooting](#troubleshooting)
- [Upgrade & Maintenance](#upgrade--maintenance)

---

## Prerequisites

### System Requirements

- **Operating System**: Debian 12 (Bookworm)
- **Python**: 3.12.x (required for `blockhash` compatibility)
- **RAM**: Minimum 4GB, 8GB+ recommended
- **CPU**: 2+ cores recommended
- **Storage**: 20GB+ available space
- **Network**: Public IP for production deployments

### Optional

- **GPU**: NVIDIA GPU with CUDA support for accelerated processing
- **Domain**: Domain name for SSL/TLS setup

---

## Quick Start

### Automated Deployment

The easiest way to deploy is using the automated deployment script:

```bash
# Clone the repository
git clone <repository-url>
cd artorize-processor-core

# Run deployment script (production mode)
sudo ./deploy.sh --production

# Or for development mode
sudo ./deploy.sh --development
```

**What the script does:**

1. Installs system dependencies (nginx, Python 3.12, build tools)
2. Creates dedicated `artorize` user
3. Sets up application directory at `/opt/artorize-processor`
4. Creates Python 3.12 virtual environment
5. Installs Python dependencies
6. Configures systemd service
7. Sets up nginx reverse proxy
8. Starts services

---

## Manual Deployment

If you prefer manual deployment or need to customize the process:

### 1. Install System Dependencies

```bash
sudo apt-get update
sudo apt-get install -y \
    build-essential git curl wget nginx \
    python3.12 python3.12-venv python3.12-dev \
    libjpeg-dev libpng-dev libtiff-dev \
    libavcodec-dev libavformat-dev libswscale-dev
```

### 2. Create Application User

```bash
sudo useradd -r -m -d /home/artorize -s /bin/bash artorize
```

### 3. Setup Application Directory

```bash
sudo mkdir -p /opt/artorize-processor
sudo mkdir -p /var/log/artorize

# Copy files
sudo cp -r . /opt/artorize-processor/
sudo chown -R artorize:artorize /opt/artorize-processor
sudo chown -R artorize:artorize /var/log/artorize
```

### 4. Create Virtual Environment

```bash
cd /opt/artorize-processor
sudo -u artorize python3.12 -m venv venv
sudo -u artorize venv/bin/pip install --upgrade pip
sudo -u artorize venv/bin/pip install -r requirements.txt
```

### 5. Configure Environment

```bash
sudo cp .env.example .env
sudo nano .env  # Edit configuration
sudo chown artorize:artorize .env
```

### 6. Setup Systemd Service

```bash
sudo cp artorize-gateway.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable artorize-gateway
sudo systemctl start artorize-gateway
```

### 7. Configure Nginx

```bash
# Create nginx config (see nginx config in deploy.sh)
sudo nano /etc/nginx/sites-available/artorize
sudo ln -s /etc/nginx/sites-available/artorize /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

---

## Configuration

### Environment Variables

Configuration is managed through the `.env` file. See `.env.example` for all available options.

**Key settings:**

```bash
# Protection layers
ARTORIZE_RUNNER__enable_fawkes=true
ARTORIZE_RUNNER__enable_photoguard=true
ARTORIZE_RUNNER__enable_mist=true
ARTORIZE_RUNNER__enable_nightshade=true

# Watermark strategy
ARTORIZE_RUNNER__watermark_strategy=invisible-watermark

# Gateway settings
GATEWAY_PORT=8765
GATEWAY_WORKERS=4

# Storage backend
STORAGE_TYPE=local  # or s3, cdn
```

### Storage Backends

#### Local Storage

Default configuration. Files saved to `/opt/artorize-processor/outputs/`.

```bash
STORAGE_TYPE=local
```

#### AWS S3

```bash
STORAGE_TYPE=s3
S3_BUCKET=artorize-outputs
S3_REGION=us-east-1
S3_ACCESS_KEY_ID=your-access-key
S3_SECRET_ACCESS_KEY=your-secret-key
```

#### CDN

```bash
STORAGE_TYPE=cdn
CDN_URL=https://cdn.example.com
CDN_API_KEY=your-api-key
```

---

## Service Management

### Systemd Commands

```bash
# Start service
sudo systemctl start artorize-gateway

# Stop service
sudo systemctl stop artorize-gateway

# Restart service
sudo systemctl restart artorize-gateway

# Check status
sudo systemctl status artorize-gateway

# View logs
sudo journalctl -u artorize-gateway -f

# Enable auto-start on boot
sudo systemctl enable artorize-gateway
```

### Health Check

```bash
# Basic health check
curl http://localhost:8765/health

# Expected response:
# {"status": "healthy"}
```

### Manual Testing

```bash
# Activate virtual environment
cd /opt/artorize-processor
source venv/bin/activate

# Test gateway
python -m artorize_gateway

# Test pipeline
python -m artorize_runner.protection_pipeline
```

---

## SSL/TLS Setup

### Using Let's Encrypt (Certbot)

```bash
# Install certbot
sudo apt-get install certbot python3-certbot-nginx

# Obtain certificate
sudo certbot --nginx -d your-domain.com

# Auto-renewal is configured automatically
# Test renewal:
sudo certbot renew --dry-run
```

### Manual SSL Certificate

```bash
# Edit nginx config
sudo nano /etc/nginx/sites-available/artorize
```

Add SSL configuration:

```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    # ... rest of config
}

server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$server_name$request_uri;
}
```

---

## Monitoring & Logging

### Log Files

```bash
# Gateway logs
tail -f /var/log/artorize/gateway.log

# Error logs
tail -f /var/log/artorize/gateway-error.log

# Systemd journal
sudo journalctl -u artorize-gateway -n 100 --no-pager
```

### Log Rotation

Create `/etc/logrotate.d/artorize`:

```
/var/log/artorize/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 0640 artorize artorize
    sharedscripts
    postrotate
        systemctl reload artorize-gateway > /dev/null 2>&1 || true
    endscript
}
```

### Performance Monitoring

```bash
# CPU and memory usage
htop

# Service resource usage
systemctl status artorize-gateway

# Disk usage
df -h
du -sh /opt/artorize-processor/outputs
```

---

## Troubleshooting

### Service Won't Start

```bash
# Check service status
sudo systemctl status artorize-gateway

# Check logs
sudo journalctl -u artorize-gateway -n 50

# Verify Python version
/opt/artorize-processor/venv/bin/python --version
# Should be 3.12.x

# Test manual start
sudo -u artorize /opt/artorize-processor/venv/bin/python -m artorize_gateway
```

### Port Already in Use

```bash
# Find process using port 8765
sudo lsof -i :8765

# Kill process
sudo kill <PID>

# Or change port in .env
GATEWAY_PORT=8766
```

### Permission Errors

```bash
# Fix ownership
sudo chown -R artorize:artorize /opt/artorize-processor
sudo chown -R artorize:artorize /var/log/artorize

# Fix permissions
sudo chmod 755 /opt/artorize-processor
sudo chmod -R 755 /opt/artorize-processor/outputs
```

### Blockhash Import Errors

```bash
# Verify Python version (must be 3.12.x)
/opt/artorize-processor/venv/bin/python --version

# Reinstall blockhash
sudo -u artorize /opt/artorize-processor/venv/bin/pip install --force-reinstall blockhash
```

### Out of Memory

```bash
# Check memory usage
free -h

# Reduce concurrent workers in .env
GATEWAY_WORKERS=2
MAX_CONCURRENT_JOBS=2

# Restart service
sudo systemctl restart artorize-gateway
```

---

## Upgrade & Maintenance

### Update Application Code

```bash
# Stop service
sudo systemctl stop artorize-gateway

# Backup current version
sudo cp -r /opt/artorize-processor /opt/artorize-processor.backup

# Pull updates
cd /opt/artorize-processor
sudo -u artorize git pull

# Update dependencies
sudo -u artorize venv/bin/pip install -r requirements.txt --upgrade

# Restart service
sudo systemctl start artorize-gateway

# Verify
curl http://localhost:8765/health
```

### Database Migrations (if applicable)

```bash
cd /opt/artorize-processor
source venv/bin/activate
# Run migration commands here
```

### Rollback to Previous Version

```bash
# Stop service
sudo systemctl stop artorize-gateway

# Restore backup
sudo rm -rf /opt/artorize-processor
sudo mv /opt/artorize-processor.backup /opt/artorize-processor

# Restart service
sudo systemctl start artorize-gateway
```

### Clean Old Outputs

```bash
# Remove outputs older than 30 days
find /opt/artorize-processor/outputs -type f -mtime +30 -delete
find /opt/artorize-processor/gateway_jobs -type f -mtime +30 -delete
```

---

## GPU Support (Optional)

### Install NVIDIA Drivers

```bash
# Check GPU
lspci | grep -i nvidia

# Install drivers
sudo apt-get install nvidia-driver
sudo reboot

# Verify
nvidia-smi
```

### Install CUDA Toolkit

```bash
# Download CUDA installer from NVIDIA
wget https://developer.download.nvidia.com/compute/cuda/repos/debian12/x86_64/cuda-keyring_1.0-1_all.deb
sudo dpkg -i cuda-keyring_1.0-1_all.deb
sudo apt-get update
sudo apt-get install cuda
```

### Install PyTorch with CUDA

```bash
cd /opt/artorize-processor
source venv/bin/activate
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
```

### Enable GPU in Configuration

```bash
# Edit .env
GPU_ENABLED=true
CUDA_DEVICE=0
GPU_WORKERS=2

# Restart service
sudo systemctl restart artorize-gateway
```

---

## Security Checklist

- [ ] Firewall configured (ufw/iptables)
- [ ] SSL/TLS enabled
- [ ] Strong API authentication tokens
- [ ] `.env` file permissions (600)
- [ ] Regular security updates (`apt-get update && apt-get upgrade`)
- [ ] Fail2ban configured (optional)
- [ ] Backup strategy in place
- [ ] Monitoring and alerting enabled

---

## Support

For issues and questions:

- **Documentation**: See `CLAUDE.md` for development details
- **Issues**: Create an issue in the repository
- **Logs**: Always include relevant logs when reporting issues

---

## License

See LICENSE file in the repository.
