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

# Check BOT_TOKEN
if [ -z "$BOT_TOKEN" ]; then
    echo "❌ BOT_TOKEN not set!"
    echo ""
    echo "Usage:"
    echo "  export BOT_TOKEN='your_bot_token'"
    echo "  bash quick-setup.sh"
    exit 1
fi

# 1. Install system dependencies
echo ""
echo "📦 [1/6] Installing dependencies..."
apt update -qq
apt install -y -qq ffmpeg curl wget unzip git > /dev/null 2>&1
echo "   ✅ System deps installed"

# 2. Install Python packages
echo ""
echo "🐍 [2/6] Installing Python packages..."
pip3 install --break-system-packages -q \
    python-telegram-bot python-dotenv yt-dlp mutagen \
    "requests[socks]" Pillow pytest pytest-asyncio > /dev/null 2>&1
echo "   ✅ Python packages installed"

# 3. Install Xray
echo ""
echo "🔧 [3/6] Installing Xray-core..."
if ! command -v xray &> /dev/null; then
    bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install > /dev/null 2>&1
    echo "   ✅ Xray installed"
else
    echo "   ℹ️  Xray already installed"
fi

# 4. Clone repo
echo ""
echo "📥 [4/6] Cloning repository..."
if [ -d "$INSTALL_DIR" ]; then
    cd "$INSTALL_DIR"
    git pull origin main > /dev/null 2>&1
    echo "   ✅ Repository updated"
else
    git clone "$REPO_URL" "$INSTALL_DIR" > /dev/null 2>&1
    cd "$INSTALL_DIR"
    echo "   ✅ Repository cloned"
fi

# 5. Create .env
echo ""
echo "🔑 [5/6] Creating .env..."
echo "BOT_TOKEN=$BOT_TOKEN" > .env
echo "   ✅ .env created"

# 6. Check Xray config
echo ""
echo "⚙️  [6/6] Checking Xray config..."
if [ ! -f /usr/local/etc/xray/config.json ] || [ ! -s /usr/local/etc/xray/config.json ]; then
    echo "   ⚠️  Xray config not found!"
    echo ""
    echo "   Please run these commands manually:"
    echo "   ---"
    echo "   mkdir -p /usr/local/etc/xray"
    echo "   cat > /usr/local/etc/xray/config.json << 'EOF'"
    echo "   <PASTE YOUR XRAY CONFIG HERE>"
    echo "   EOF"
    echo "   ---"
    echo ""
    echo "   Then run: /home/daytona/start-bot.sh"
    exit 1
fi
echo "   ✅ Xray config exists"

# 7. Create start script
echo ""
echo "📝 Creating start script..."
cat > /home/daytona/start-bot.sh << 'STARTEOF'
#!/bin/bash
# Start Xray + Bot

if ! pgrep -x "xray" > /dev/null; then
    nohup /usr/local/bin/xray run -c /usr/local/etc/xray/config.json > /var/log/xray.log 2>&1 &
    disown
    sleep 2
    echo "✅ Xray started"
else
    echo "ℹ️  Xray already running"
fi

cd /home/daytona/soundcloud-bot
if ! pgrep -f "bot.py" > /dev/null; then
    nohup python3 bot.py > bot.log 2>&1 &
    disown
    sleep 3
    echo "✅ Bot started"
else
    echo "ℹ️  Bot already running"
fi
STARTEOF
chmod +x /home/daytona/start-bot.sh

# 8. Start
echo ""
echo "🚀 Starting bot..."
/home/daytona/start-bot.sh

echo ""
echo "================================"
echo "✅ Setup complete!"
echo ""
echo "Check status:"
echo "  ps aux | grep -E 'xray|bot.py' | grep -v grep"
echo ""
echo "View logs:"
echo "  tail -f /home/daytona/soundcloud-bot/bot.log"
echo "================================"
