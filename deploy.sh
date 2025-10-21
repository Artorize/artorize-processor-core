#!/bin/bash
###########################################
# Artorize Processor - Production Deployment
# Debian 12 / Ubuntu 22.04+ Compatible
#
# Usage: curl -fsSL https://raw.githubusercontent.com/Artorize/artorize-processor-core/main/deploy.sh | sudo bash
###########################################

set -e  # Exit on error
set -u  # Exit on undefined variable

# Configuration
PYTHON_VERSION="3.12"
REPO_URL="https://github.com/Artorize/artorize-processor-core.git"
APP_USER="artorize"
APP_DIR="/opt/artorize-processor"
VENV_DIR="${APP_DIR}/venv"
LOG_DIR="/var/log/artorize"
GATEWAY_SERVICE="artorize-processor-gateway"
RUNNER_SERVICE="artorize-processor-runner"

# Color output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# Check root
[[ $EUID -ne 0 ]] && error "This script must be run as root (use sudo)"

info "Starting Artorize Processor deployment..."

###########################################
# 1. System Dependencies
###########################################
info "Installing system dependencies..."

apt-get update
apt-get install -y \
    software-properties-common \
    build-essential \
    git \
    curl \
    wget \
    libjpeg-dev \
    libpng-dev \
    libtiff-dev \
    python3-dev \
    python3-pip \
    python3-venv \
    libffi-dev \
    libssl-dev

###########################################
# 2. Python 3.12 Installation
###########################################
info "Checking Python 3.12 installation..."

if ! command -v python3.12 &> /dev/null; then
    info "Python 3.12 not found. Installing..."

    # Try deadsnakes PPA first (Ubuntu)
    if grep -q "Ubuntu" /etc/os-release 2>/dev/null; then
        add-apt-repository -y ppa:deadsnakes/ppa
        apt-get update
        apt-get install -y python3.12 python3.12-venv python3.12-dev
    else
        # Build from source (Debian)
        info "Building Python 3.12 from source..."
        cd /tmp
        wget -q https://www.python.org/ftp/python/3.12.10/Python-3.12.10.tgz
        tar -xf Python-3.12.10.tgz
        cd Python-3.12.10
        ./configure --enable-optimizations --quiet
        make -j$(nproc) --quiet
        make altinstall --quiet
        cd / && rm -rf /tmp/Python-3.12.10*
    fi
fi

# Verify Python 3.12
python3.12 --version &> /dev/null || error "Python 3.12 installation failed"
PY_VER=$(python3.12 --version | awk '{print $2}' | cut -d. -f1,2)
[[ "$PY_VER" != "3.12" ]] && error "Python 3.12.x required (found: $PY_VER)"

info "Python 3.12 installed: $(python3.12 --version)"

###########################################
# 3. Application User
###########################################
info "Setting up application user..."

if ! id -u $APP_USER &> /dev/null; then
    useradd -r -m -d /home/$APP_USER -s /bin/bash $APP_USER
    info "Created user: $APP_USER"
else
    info "User $APP_USER already exists"
fi

###########################################
# 4. Clone Repository
###########################################
info "Cloning repository to $APP_DIR..."

# Backup .env if exists
ENV_BACKUP=""
if [ -f "$APP_DIR/.env" ]; then
    ENV_BACKUP=$(mktemp)
    cp "$APP_DIR/.env" "$ENV_BACKUP"
    info "Backed up existing .env"
fi

# Backup data directories
for dir in outputs gateway_jobs input; do
    if [ -d "$APP_DIR/$dir" ]; then
        mv "$APP_DIR/$dir" "/tmp/artorize-$dir-backup" 2>/dev/null || true
    fi
done

# Clone fresh copy
rm -rf "$APP_DIR"
git clone --depth 1 "$REPO_URL" "$APP_DIR"

# Restore data directories
for dir in outputs gateway_jobs input; do
    if [ -d "/tmp/artorize-$dir-backup" ]; then
        mv "/tmp/artorize-$dir-backup" "$APP_DIR/$dir"
    else
        mkdir -p "$APP_DIR/$dir"
    fi
done

# Restore .env
if [ -n "$ENV_BACKUP" ] && [ -f "$ENV_BACKUP" ]; then
    cp "$ENV_BACKUP" "$APP_DIR/.env"
    rm "$ENV_BACKUP"
    info "Restored .env configuration"
fi

# Create log directory
mkdir -p "$LOG_DIR"
chown -R $APP_USER:$APP_USER "$APP_DIR" "$LOG_DIR"

###########################################
# 5. Python Virtual Environment
###########################################
info "Creating Python 3.12 virtual environment..."

# Remove old venv
rm -rf "$VENV_DIR"

# Create new venv with Python 3.12
sudo -u $APP_USER python3.12 -m venv "$VENV_DIR"

# Verify venv Python version
VENV_PY_VER=$($VENV_DIR/bin/python --version | awk '{print $2}' | cut -d. -f1,2)
[[ "$VENV_PY_VER" != "3.12" ]] && error "Virtual environment not using Python 3.12 (found: $VENV_PY_VER)"

info "Installing Python dependencies..."
sudo -u $APP_USER $VENV_DIR/bin/pip install --quiet --upgrade pip setuptools wheel
sudo -u $APP_USER $VENV_DIR/bin/pip install --quiet -r $APP_DIR/requirements.txt

# Verify critical imports
sudo -u $APP_USER $VENV_DIR/bin/python -c "import blockhash, PIL, fastapi" || \
    error "Failed to import critical dependencies"

info "Virtual environment ready"

###########################################
# 6. Environment Configuration
###########################################
if [ ! -f "$APP_DIR/.env" ]; then
    info "Creating default .env configuration..."
    cat > "$APP_DIR/.env" << 'EOF'
# Artorize Processor Configuration
# Protection Pipeline Settings
ARTORIZE_RUNNER__enable_fawkes=true
ARTORIZE_RUNNER__enable_photoguard=true
ARTORIZE_RUNNER__enable_mist=true
ARTORIZE_RUNNER__enable_nightshade=true
ARTORIZE_RUNNER__watermark_strategy=invisible-watermark
ARTORIZE_RUNNER__enable_c2pa_manifest=true
ARTORIZE_RUNNER__enable_poison_mask=true

# Gateway Configuration
GATEWAY_PORT=8765
GATEWAY_HOST=0.0.0.0
GATEWAY_WORKERS=4

# Storage (local/s3/cdn)
STORAGE_TYPE=local

# Performance
MAX_CONCURRENT_JOBS=4
GPU_ENABLED=false

# Logging
LOG_LEVEL=INFO
EOF
    chown $APP_USER:$APP_USER "$APP_DIR/.env"
fi

###########################################
# 7. Systemd Services
###########################################
info "Creating systemd services..."

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

# Security
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$APP_DIR/outputs $APP_DIR/gateway_jobs $LOG_DIR

# Resources
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF

# Runner service (optional - gateway has internal workers)
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
# Note: Gateway has internal workers. This service is optional for batch processing.
# Disable with: systemctl disable ${RUNNER_SERVICE}
ExecStart=$VENV_DIR/bin/python -m artorize_runner.protection_pipeline_gpu
Restart=on-failure
RestartSec=10
StandardOutput=append:$LOG_DIR/runner.log
StandardError=append:$LOG_DIR/runner-error.log

# Security
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$APP_DIR/outputs $APP_DIR/input $APP_DIR/gateway_jobs $LOG_DIR

# Resources
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable $GATEWAY_SERVICE
# Enable runner optionally (gateway has internal workers)
systemctl enable $RUNNER_SERVICE

info "Services created and enabled"

###########################################
# 8. Start Services
###########################################
info "Starting services..."

systemctl restart $GATEWAY_SERVICE
systemctl restart $RUNNER_SERVICE
sleep 3

# Check gateway status
if systemctl is-active --quiet $GATEWAY_SERVICE; then
    info "✓ Gateway service started"
else
    warn "✗ Gateway service failed. Check: journalctl -u ${GATEWAY_SERVICE} -n 50"
    exit 1
fi

# Check runner status (non-fatal)
if systemctl is-active --quiet $RUNNER_SERVICE; then
    info "✓ Runner service started"
else
    warn "✗ Runner service failed. Check: journalctl -u ${RUNNER_SERVICE} -n 50"
    warn "Note: Runner is optional if using gateway's internal workers"
fi

# Health check
info "Running health check..."
sleep 2
if curl -f http://localhost:8765/health &> /dev/null; then
    info "✓ Health check passed"
else
    warn "Health check failed (service may still be starting)"
fi

###########################################
# Deployment Complete
###########################################
echo ""
info "================================================"
info "Artorize Processor Deployment Complete!"
info "================================================"
echo ""
info "Services:"
echo "  Gateway: http://localhost:8765"
echo "  Status:  systemctl status ${GATEWAY_SERVICE}"
echo "  Logs:    journalctl -u ${GATEWAY_SERVICE} -f"
echo ""
info "File Locations:"
echo "  App:     $APP_DIR"
echo "  Config:  $APP_DIR/.env"
echo "  Logs:    $LOG_DIR"
echo ""
info "Service Management:"
echo "  systemctl restart ${GATEWAY_SERVICE}"
echo "  systemctl restart ${RUNNER_SERVICE}"
echo "  journalctl -u ${GATEWAY_SERVICE} -f"
echo ""
info "Test API: curl http://localhost:8765/health"
echo ""
