#!/bin/bash

###########################################
# Artorize Processor - Debian 12 Auto-Deployment Script
#
# This script automates the deployment of the Artorize image protection
# processor and gateway on Debian 12 servers.
#
# Usage:
#   sudo ./deploy.sh [--production|--development]
#
# Options:
#   --production   Deploy for production (systemd service, nginx)
#   --development  Deploy for development (no systemd, manual start)
###########################################

set -e  # Exit on error
set -u  # Exit on undefined variable

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
DEPLOY_MODE="${1:-production}"
PYTHON_VERSION="3.12"
APP_USER="artorize"
APP_DIR="/opt/artorize-processor"
VENV_DIR="${APP_DIR}/venv"
GATEWAY_SERVICE="artorize-gateway"
RUNNER_SERVICE="artorize-runner"
GATEWAY_PORT="8765"
LOG_DIR="/var/log/artorize"

echo_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

echo_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

echo_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo_error "This script must be run as root (use sudo)"
   exit 1
fi

# Verify Debian 12
if ! grep -q "Debian GNU/Linux 12" /etc/os-release 2>/dev/null; then
    echo_warn "This script is designed for Debian 12. Your system may not be compatible."
    read -p "Continue anyway? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo_info "Starting Artorize Processor deployment in ${DEPLOY_MODE} mode..."

###########################################
# 1. System Dependencies
###########################################
echo_info "Installing system dependencies..."

apt-get update
apt-get install -y \
    software-properties-common \
    build-essential \
    git \
    curl \
    wget \
    nginx \
    supervisor \
    rsync \
    libjpeg-dev \
    libpng-dev \
    libtiff-dev \
    libavcodec-dev \
    libavformat-dev \
    libswscale-dev \
    libv4l-dev \
    libxvidcore-dev \
    libx264-dev \
    libatlas-base-dev \
    libopenblas-dev \
    liblapack-dev \
    gfortran \
    python3-dev \
    python3-pip \
    python3-venv \
    libffi-dev \
    libssl-dev \
    zlib1g-dev \
    libbz2-dev \
    libreadline-dev \
    libsqlite3-dev \
    libncurses5-dev \
    libncursesw5-dev \
    xz-utils \
    tk-dev \
    libxml2-dev \
    libxmlsec1-dev

###########################################
# 2. Python 3.12 Installation
###########################################
echo_info "Checking Python 3.12 installation..."

if ! command -v python3.12 &> /dev/null; then
    echo_info "Python 3.12 not found. Installing from deadsnakes PPA..."

    # Add deadsnakes PPA for Python 3.12
    apt-get install -y software-properties-common
    add-apt-repository -y ppa:deadsnakes/ppa || {
        echo_warn "PPA not available for Debian. Building from source..."

        cd /tmp
        wget https://www.python.org/ftp/python/3.12.10/Python-3.12.10.tgz
        tar -xf Python-3.12.10.tgz
        cd Python-3.12.10
        ./configure --enable-optimizations
        make -j$(nproc)
        make altinstall
        cd /
        rm -rf /tmp/Python-3.12.10*
    }

    apt-get update
    apt-get install -y python3.12 python3.12-venv python3.12-dev || true
fi

# Verify Python 3.12
if ! python3.12 --version &> /dev/null; then
    echo_error "Python 3.12 installation failed"
    exit 1
fi

PYTHON_VERSION=$(python3.12 --version 2>&1 | awk '{print $2}')
PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

if [ "$PYTHON_MAJOR" != "3" ] || [ "$PYTHON_MINOR" != "12" ]; then
    echo_error "Python 3.12.x is required for blockhash compatibility (Python 3.13+ is incompatible)"
    echo_error "Found: Python $PYTHON_VERSION"
    exit 1
fi

echo_info "Python 3.12 installed: $(python3.12 --version)"
echo_info "✓ Python version check passed"

###########################################
# 3. Application User Setup
###########################################
echo_info "Setting up application user..."

if ! id -u $APP_USER &> /dev/null; then
    useradd -r -m -d /home/$APP_USER -s /bin/bash $APP_USER
    echo_info "Created user: $APP_USER"
else
    echo_info "User $APP_USER already exists"
fi

###########################################
# 4. Application Directory Setup
###########################################
echo_info "Setting up application directory..."

mkdir -p $APP_DIR
mkdir -p $LOG_DIR
mkdir -p $APP_DIR/input
mkdir -p $APP_DIR/outputs
mkdir -p $APP_DIR/gateway_jobs

# Copy application files
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo_info "Copying files from $SCRIPT_DIR to $APP_DIR..."

rsync -av --exclude='venv' \
          --exclude='outputs' \
          --exclude='gateway_jobs' \
          --exclude='__pycache__' \
          --exclude='*.pyc' \
          --exclude='.git' \
          --exclude='.DS_Store' \
          "$SCRIPT_DIR/" "$APP_DIR/"

# Set ownership
chown -R $APP_USER:$APP_USER $APP_DIR
chown -R $APP_USER:$APP_USER $LOG_DIR

###########################################
# 5. Virtual Environment Setup
###########################################
echo_info "Creating Python virtual environment..."

if [ -d "$VENV_DIR" ]; then
    echo_warn "Virtual environment exists. Removing..."
    rm -rf $VENV_DIR
fi

sudo -u $APP_USER python3.12 -m venv $VENV_DIR

echo_info "Installing Python dependencies..."
sudo -u $APP_USER $VENV_DIR/bin/pip install --upgrade pip setuptools wheel
sudo -u $APP_USER $VENV_DIR/bin/pip install -r $APP_DIR/requirements.txt

echo_info "Verifying blockhash compatibility..."
if ! sudo -u $APP_USER $VENV_DIR/bin/python -c "import blockhash" 2>/dev/null; then
    echo_error "blockhash import failed. Python 3.12 is required for compatibility."
    echo_error "Note: pytineye has been removed from requirements (incompatible with Python 3.12+)."
    exit 1
fi

###########################################
# 6. Configuration Files
###########################################
echo_info "Setting up configuration..."

# Create environment file if it doesn't exist
if [ ! -f "$APP_DIR/.env" ]; then
    cat > "$APP_DIR/.env" << EOF
# Artorize Processor Configuration
# Protection Pipeline Settings
ARTORIZE_RUNNER__enable_fawkes=true
ARTORIZE_RUNNER__enable_photoguard=true
ARTORIZE_RUNNER__enable_mist=true
ARTORIZE_RUNNER__enable_nightshade=true
ARTORIZE_RUNNER__watermark_strategy=invisible-watermark
ARTORIZE_RUNNER__watermark_text=artscraper
ARTORIZE_RUNNER__enable_c2pa_manifest=true
ARTORIZE_RUNNER__enable_poison_mask=true
ARTORIZE_RUNNER__poison_mask_filter_id=poison-mask
ARTORIZE_RUNNER__poison_mask_css_class=poisoned-image
ARTORIZE_RUNNER__max_stage_dim=512
ARTORIZE_RUNNER__include_hash_analysis=true
ARTORIZE_RUNNER__include_tineye=false

# Gateway Server Configuration
GATEWAY_PORT=$GATEWAY_PORT
GATEWAY_HOST=0.0.0.0
GATEWAY_WORKERS=4
GATEWAY_DEBUG=false

# Storage Configuration
STORAGE_TYPE=local
# For S3: STORAGE_TYPE=s3, S3_BUCKET=your-bucket, S3_REGION=us-east-1
# For CDN: STORAGE_TYPE=cdn, CDN_BASE_URL=https://cdn.example.com

# Backend Upload Configuration (optional)
# BACKEND_URL=https://api.artorize.com
# BACKEND_AUTH_TOKEN=your-token-here
# BACKEND_TIMEOUT=30.0

# Logging Configuration
LOG_LEVEL=INFO
LOG_FORMAT=text

# Performance Settings
MAX_CONCURRENT_JOBS=4
JOB_TIMEOUT=300
REQUEST_TIMEOUT=60
MAX_UPLOAD_SIZE_MB=100

# GPU Configuration (set to true if GPU available)
GPU_ENABLED=false
CUDA_DEVICE=0

# Application Environment
APP_ENV=production
EOF
    chown $APP_USER:$APP_USER "$APP_DIR/.env"
    echo_info "Created default .env file"
else
    echo_info ".env file already exists (keeping existing configuration)"
fi

###########################################
# 7. Systemd Services (Production Mode)
###########################################
if [ "$DEPLOY_MODE" = "production" ] || [ "$DEPLOY_MODE" = "--production" ]; then
    echo_info "Setting up systemd services..."

    # Gateway service
    cat > "/etc/systemd/system/${GATEWAY_SERVICE}.service" << EOF
[Unit]
Description=Artorize Image Protection Gateway
After=network.target

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
Environment="PATH=$VENV_DIR/bin"
EnvironmentFile=$APP_DIR/.env
ExecStart=$VENV_DIR/bin/python -m artorize_gateway
Restart=always
RestartSec=10
StandardOutput=append:$LOG_DIR/gateway.log
StandardError=append:$LOG_DIR/gateway-error.log

# Security settings
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$APP_DIR/outputs $APP_DIR/gateway_jobs $LOG_DIR

# Resource limits
LimitNOFILE=65536
TasksMax=4096

[Install]
WantedBy=multi-user.target
EOF

    # Runner service (for background processing)
    cat > "/etc/systemd/system/${RUNNER_SERVICE}.service" << EOF
[Unit]
Description=Artorize Image Protection Pipeline Runner
After=network.target

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
Environment="PATH=$VENV_DIR/bin"
EnvironmentFile=$APP_DIR/.env
ExecStart=$VENV_DIR/bin/python -m artorize_runner.protection_pipeline_gpu
Restart=always
RestartSec=10
StandardOutput=append:$LOG_DIR/runner.log
StandardError=append:$LOG_DIR/runner-error.log

# Security settings
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$APP_DIR/outputs $APP_DIR/input $APP_DIR/gateway_jobs $LOG_DIR

# Resource limits
LimitNOFILE=65536
TasksMax=4096

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable $GATEWAY_SERVICE
    systemctl enable $RUNNER_SERVICE

    echo_info "Systemd services created:"
    echo_info "  - ${GATEWAY_SERVICE}.service (HTTP API gateway)"
    echo_info "  - ${RUNNER_SERVICE}.service (Background pipeline runner)"
fi

###########################################
# 8. Nginx Configuration (Production Mode)
###########################################
if [ "$DEPLOY_MODE" = "production" ] || [ "$DEPLOY_MODE" = "--production" ]; then
    echo_info "Setting up Nginx reverse proxy..."

    cat > "/etc/nginx/sites-available/artorize" << EOF
upstream artorize_gateway {
    server 127.0.0.1:$GATEWAY_PORT;
}

server {
    listen 80;
    server_name _;

    client_max_body_size 100M;

    location / {
        proxy_pass http://artorize_gateway;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;

        # Timeouts for long-running image processing
        proxy_connect_timeout 300s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
    }

    location /health {
        proxy_pass http://artorize_gateway/health;
        access_log off;
    }
}
EOF

    ln -sf /etc/nginx/sites-available/artorize /etc/nginx/sites-enabled/
    rm -f /etc/nginx/sites-enabled/default

    nginx -t && systemctl restart nginx
    echo_info "Nginx configured and restarted"
fi

###########################################
# 9. Firewall Configuration
###########################################
if command -v ufw &> /dev/null; then
    echo_info "Configuring firewall..."
    ufw allow 80/tcp
    ufw allow 443/tcp
    ufw allow 22/tcp
    echo_info "Firewall rules updated"
fi

###########################################
# 10. GPU Support (Optional)
###########################################
if lspci | grep -i nvidia &> /dev/null; then
    echo_info "NVIDIA GPU detected. To enable GPU support:"
    echo_info "  1. Install NVIDIA drivers: apt-get install nvidia-driver"
    echo_info "  2. Install CUDA toolkit"
    echo_info "  3. Install PyTorch with CUDA support in the virtualenv"
else
    echo_info "No NVIDIA GPU detected. Deployment will use CPU-only mode."
fi

###########################################
# 11. Start Services (Production Mode)
###########################################
if [ "$DEPLOY_MODE" = "production" ] || [ "$DEPLOY_MODE" = "--production" ]; then
    echo_info "Starting services..."

    systemctl restart $GATEWAY_SERVICE
    systemctl restart $RUNNER_SERVICE
    sleep 3

    GATEWAY_STATUS="✓"
    RUNNER_STATUS="✓"

    if systemctl is-active --quiet $GATEWAY_SERVICE; then
        echo_info "✓ Gateway service started successfully"
    else
        echo_error "✗ Gateway service failed to start. Check logs:"
        echo "  journalctl -u ${GATEWAY_SERVICE} -n 50"
        GATEWAY_STATUS="✗"
    fi

    if systemctl is-active --quiet $RUNNER_SERVICE; then
        echo_info "✓ Runner service started successfully"
    else
        echo_warn "✗ Runner service failed to start. Check logs:"
        echo "  journalctl -u ${RUNNER_SERVICE} -n 50"
        RUNNER_STATUS="✗"
    fi

    if [ "$GATEWAY_STATUS" = "✗" ]; then
        exit 1
    fi
fi

###########################################
# 12. Post-Deployment Verification
###########################################
echo_info "Running post-deployment verification..."

# Verify Python version in virtual environment
VENV_PYTHON_VERSION=$($VENV_DIR/bin/python --version 2>&1 | awk '{print $2}')
echo_info "Virtual environment Python version: $VENV_PYTHON_VERSION"

# Verify critical dependencies
echo_info "Verifying critical dependencies..."
if ! sudo -u $APP_USER $VENV_DIR/bin/python -c "import blockhash" 2>/dev/null; then
    echo_error "blockhash import failed. Installation may be incomplete."
    exit 1
fi

if ! sudo -u $APP_USER $VENV_DIR/bin/python -c "import PIL" 2>/dev/null; then
    echo_error "Pillow import failed. Installation may be incomplete."
    exit 1
fi

if ! sudo -u $APP_USER $VENV_DIR/bin/python -c "import fastapi" 2>/dev/null; then
    echo_error "FastAPI import failed. Installation may be incomplete."
    exit 1
fi

echo_info "✓ All critical dependencies verified"

# Health check (production mode only)
if [ "$DEPLOY_MODE" = "production" ] || [ "$DEPLOY_MODE" = "--production" ]; then
    echo_info "Running health check..."
    sleep 3

    if curl -f http://localhost:$GATEWAY_PORT/health &> /dev/null; then
        echo_info "✓ Health check passed!"
    else
        echo_warn "Health check failed. Service may still be starting..."
        echo_warn "Check logs: journalctl -u ${GATEWAY_SERVICE} -n 50"
    fi
fi

###########################################
# Deployment Summary
###########################################
echo ""
echo_info "================================================"
echo_info "Artorize Processor Deployment Complete!"
echo_info "================================================"
echo ""
echo_info "Application Directory: $APP_DIR"
echo_info "Virtual Environment: $VENV_DIR"
echo_info "Log Directory: $LOG_DIR"
echo ""

if [ "$DEPLOY_MODE" = "production" ] || [ "$DEPLOY_MODE" = "--production" ]; then
    echo_info "Service Management:"
    echo ""
    echo "  Gateway Service:"
    echo "    Start:   systemctl start ${GATEWAY_SERVICE}"
    echo "    Stop:    systemctl stop ${GATEWAY_SERVICE}"
    echo "    Restart: systemctl restart ${GATEWAY_SERVICE}"
    echo "    Status:  systemctl status ${GATEWAY_SERVICE}"
    echo "    Logs:    journalctl -u ${GATEWAY_SERVICE} -f"
    echo ""
    echo "  Runner Service:"
    echo "    Start:   systemctl start ${RUNNER_SERVICE}"
    echo "    Stop:    systemctl stop ${RUNNER_SERVICE}"
    echo "    Restart: systemctl restart ${RUNNER_SERVICE}"
    echo "    Status:  systemctl status ${RUNNER_SERVICE}"
    echo "    Logs:    journalctl -u ${RUNNER_SERVICE} -f"
    echo ""
    echo_info "Gateway running at: http://localhost:$GATEWAY_PORT"
    echo_info "Access via Nginx: http://your-server-ip/"
    echo_info "Runner: Processes images from input/ directory automatically"
else
    echo_info "Development Mode - Manual Start:"
    echo "  cd $APP_DIR"
    echo "  source venv/bin/activate"
    echo "  # Start gateway:"
    echo "  python -m artorize_gateway"
    echo "  # Start runner (in another terminal):"
    echo "  python -m artorize_runner.protection_pipeline_gpu"
fi

echo ""
echo_info "Configuration file: $APP_DIR/.env"
echo_info "Test the API: curl http://localhost:$GATEWAY_PORT/health"
echo ""
echo_info "Next steps:"
echo "  1. Review and update $APP_DIR/.env for your environment"
echo "  2. Configure SSL/TLS with Let's Encrypt (production)"
echo "  3. Set up monitoring and log rotation"
echo "  4. Configure CDN/S3 storage credentials if needed"
echo "  5. Review DEPLOYMENT.md for detailed operational guidance"
echo ""

###########################################
# Quick Reference Card
###########################################
if [ "$DEPLOY_MODE" = "production" ] || [ "$DEPLOY_MODE" = "--production" ]; then
    echo_info "Quick Reference:"
    echo ""
    echo "  Service Control:"
    echo "    systemctl status ${GATEWAY_SERVICE}    # Check gateway status"
    echo "    systemctl status ${RUNNER_SERVICE}     # Check runner status"
    echo "    systemctl restart ${GATEWAY_SERVICE}   # Restart gateway"
    echo "    systemctl restart ${RUNNER_SERVICE}    # Restart runner"
    echo "    journalctl -u ${GATEWAY_SERVICE} -f    # Follow gateway logs"
    echo "    journalctl -u ${RUNNER_SERVICE} -f     # Follow runner logs"
    echo ""
    echo "  Testing:"
    echo "    curl http://localhost:$GATEWAY_PORT/health"
    echo ""
    echo "  File Locations:"
    echo "    Application:  $APP_DIR"
    echo "    Logs:         $LOG_DIR"
    echo "    Config:       $APP_DIR/.env"
    echo "    Outputs:      $APP_DIR/outputs"
    echo "    Input:        $APP_DIR/input  (monitored by runner)"
    echo ""
fi
