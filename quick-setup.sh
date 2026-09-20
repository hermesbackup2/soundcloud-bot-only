#!/bin/bash
# ============================================================
# SoundCloud Bot - Quick Setup
# Usage:
#   export BOT_TOKEN="your_bot_token"
#   bash quick-setup.sh
# ============================================================

set -e

REPO_URL="https://github.com/hermesbackup2/soundcloud-bot-only.git"
INSTALL_DIR="/home/daytona/soundcloud-bot"

echo "🚀 SoundCloud Bot - Quick Setup"
echo "================================"

if [ -z "$BOT_TOKEN" ]; then
    echo "❌ BOT_TOKEN not set!"
    echo ""
    echo "Usage:"
    echo "  export BOT_TOKEN='your_bot_token'"
    echo "  bash quick-setup.sh"
    exit 1
fi

echo ""
echo "📦 [1/6] Installing dependencies..."
apt update -qq
apt install -y -qq ffmpeg curl wget unzip git > /dev/null 2>&1

echo "🐍 [2/6] Installing Python packages..."
pip3 install --break-system-packages -q \
    python-telegram-bot python-dotenv yt-dlp mutagen \
    "requests[socks]" Pillow pytest pytest-asyncio > /dev/null 2>&1

echo "🔧 [3/6] Installing Xray-core..."
if ! command -v xray &> /dev/null; then
    bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install > /dev/null 2>&1
fi

echo "📥 [4/6] Cloning repository..."
if [ -d "$INSTALL_DIR" ]; then
    cd "$INSTALL_DIR"
    git pull origin main > /dev/null 2>&1 || true
else
    git clone "$REPO_URL" "$INSTALL_DIR" > /dev/null 2>&1
    cd "$INSTALL_DIR"
fi

echo "🔑 [5/6] Creating .env..."
echo "BOT_TOKEN=$BOT_TOKEN" > .env

echo "⚙️  [6/6] Checking Xray config..."
if [ ! -f /usr/local/etc/xray/config.json ] || [ ! -s /usr/local/etc/xray/config.json ]; then
    echo "   ⚠️  Xray config not found! Create it manually."
    exit 1
fi

echo ""
echo "📝 Creating start script..."
cat > /home/daytona/start-bot.sh << 'STARTEOF'
#!/bin/bash
if ! pgrep -x "xray" > /dev/null; then
    nohup /usr/local/bin/xray run -c /usr/local/etc/xray/config.json > /var/log/xray.log 2>&1 &
    disown
    sleep 2
fi
cd /home/daytona/soundcloud-bot
if ! pgrep -f "bot.py" > /dev/null; then
    nohup python3 bot.py > bot.log 2>&1 &
    disown
fi
echo "✅ Xray and Bot are running"
STARTEOF
chmod +x /home/daytona/start-bot.sh

echo ""
echo "🚀 Starting bot..."
/home/daytona/start-bot.sh

echo ""
echo "================================"
echo "✅ Setup complete!"
echo "================================"
