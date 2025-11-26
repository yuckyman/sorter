#!/bin/bash
# Deploy sorter to yuckbox
# Run this script locally after pushing to GitHub

set -e

REMOTE="ian@yuckbox"
REPO_URL="$1"
INSTALL_DIR="/home/ian/scripts/sorter"

if [ -z "$REPO_URL" ]; then
    echo "Usage: ./deploy.sh <github-repo-url>"
    echo "Example: ./deploy.sh git@github.com:username/sorter.git"
    exit 1
fi

echo "==> Deploying to yuckbox..."

ssh $REMOTE << EOF
set -e

# Clone or update repo
if [ -d "$INSTALL_DIR" ]; then
    echo "==> Updating existing installation..."
    cd $INSTALL_DIR
    git pull
else
    echo "==> Cloning repository..."
    mkdir -p ~/scripts
    cd ~/scripts
    git clone $REPO_URL sorter
    cd sorter
fi

# Setup venv
echo "==> Setting up Python environment..."
python3 -m venv venv
source venv/bin/activate
pip install -q -r requirements.txt

# Check for .env.local
if [ ! -f .env.local ]; then
    echo ""
    echo "==> WARNING: .env.local not found!"
    echo "Create it with:"
    echo "  cat > $INSTALL_DIR/.env.local << 'ENVEOF'"
    echo "IMMICH_URL=http://100.114.1.102:2283/api"
    echo "IMMICH_API_KEY=your-api-key-here"
    echo "ENVEOF"
    echo ""
fi

# Install systemd service
echo "==> Installing systemd service..."
sudo cp sorter.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable sorter
sudo systemctl restart sorter

echo ""
echo "==> Done! Service status:"
sudo systemctl status sorter --no-pager -l

echo ""
echo "Access at: http://yuckbox:8050"
EOF

