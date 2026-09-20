#!/bin/bash
# ============================================================
# SoundCloud Bot - Auto Setup Script
# Usage: bash setup.sh
# ============================================================

set -e  # Exit on error

echo "🚀 SoundCloud Bot Setup"
echo "========================"

# 1. Update package list
echo ""
echo "📦 [1/8] Updating package list..."
apt update -qq

# 2. Install system dependencies
echo ""
echo "📦 [2/8] Installing system dependencies..."
apt install -y -qq ffmpeg curl wget unzip > /dev/null 2>&1
echo "   ✅ ffmpeg, curl, wget, unzip installed"

# 3. Install Python dependencies
echo ""
echo "🐍 [3/8] Installing Python packages..."
pip3 install --break-system-packages -q \
    python-telegram-bot \
    python-dotenv \
    yt-dlp \
    mutagen \
    "requests[socks]" \
    Pillow \
    pytest \
    pytest-asyncio > /dev/null 2>&1
echo "   ✅ Python packages installed"

# 4. Install Xray
echo ""
echo "🔧 [4/8] Installing Xray-core..."
if ! command -v xray &> /dev/null; then
    bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install > /dev/null 2>&1
    echo "   ✅ Xray installed"
else
    echo "   ℹ️  Xray already installed"
fi

# 5. Create .env file
echo ""
echo "🔑 [5/8] Creating .env file..."
if [ ! -f .env ]; then
    if [ -z "$BOT_TOKEN" ]; then
        echo "   ⚠️  BOT_TOKEN not set in environment!"
        echo "   Please run: export BOT_TOKEN='your_token'"
        echo "   Then run this script again."
        exit 1
    fi
    echo "BOT_TOKEN=$BOT_TOKEN" > .env
    echo "   ✅ .env created"
else
    echo "   ℹ️  .env already exists"
fi

# 6. Create Xray config
echo ""
echo "⚙️  [6/8] Creating Xray config..."
if [ ! -f /usr/local/etc/xray/config.json ] || [ ! -s /usr/local/etc/xray/config.json ]; then
    echo "   ⚠️  Xray config not found!"
    echo "   Please copy your config.json to /usr/local/etc/xray/config.json"
    echo "   Then run this script again."
    exit 1
fi
echo "   ✅ Xray config exists"

# 7. Create start script
echo ""
echo "📝 [7/8] Creating start script..."
cat > /home/daytona/start-bot.sh << 'STARTEOF'
#!/bin/bash
# Start Xray + Bot

# Start Xray
if ! pgrep -x "xray" > /dev/null; then
    nohup /usr/local/bin/xray run -c /usr/local/etc/xray/config.json > /var/log/xray.log 2>&1 &
    disown
    sleep 2
    echo "✅ Xray started"
else
    echo "ℹ️  Xray already running"
fi

# Start bot
cd "$(dirname "$0")"
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
echo "   ✅ /home/daytona/start-bot.sh created"

# 8. Run tests
echo ""
echo "🧪 [8/8] Running tests..."
python3 -m pytest tests/ -q 2>&1 | tail -3

echo ""
echo "================================"
echo "✅ Setup complete!"
echo ""
echo "To start the bot:"
echo "  /home/daytona/start-bot.sh"
echo ""
echo "To check status:"
echo "  ps aux | grep -E 'xray|bot.py' | grep -v grep"
echo "================================"
