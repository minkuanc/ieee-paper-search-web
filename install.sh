#!/usr/bin/env bash
# ============================================================
# IEEE Paper Search — one-time setup script (macOS)
# Run once on a new machine:  bash install.sh
# ============================================================
set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[✗]${NC} $1"; exit 1; }

echo ""
echo "=================================================="
echo "  IEEE Paper Search — Installation"
echo "=================================================="
echo ""

# ── 1. Google Chrome ──────────────────────────────────────
if [ -d "/Applications/Google Chrome.app" ]; then
    info "Google Chrome found"
else
    error "Google Chrome is not installed.\nPlease download it from https://www.google.com/chrome/ and re-run this script."
fi

# ── 2. Python 3.10+ ───────────────────────────────────────
PYTHON=""
for cmd in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$cmd" &>/dev/null; then
        VER=$("$cmd" -c "import sys; print(sys.version_info[:2])")
        # Check >= (3, 10)
        if "$cmd" -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    error "Python 3.10 or newer is required.\nInstall it from https://www.python.org/downloads/ and re-run this script."
fi
info "Python found: $($PYTHON --version)"

# ── 3. Node.js 18+ ────────────────────────────────────────
if command -v node &>/dev/null; then
    NODE_VER=$(node -e "process.exit(parseInt(process.version.slice(1)) < 18 ? 1 : 0)" 2>/dev/null && echo ok || echo old)
    if [ "$NODE_VER" = "old" ]; then
        error "Node.js 18 or newer is required. Current: $(node --version)\nDownload from https://nodejs.org/"
    fi
    info "Node.js found: $(node --version)"
else
    error "Node.js is not installed.\nDownload it from https://nodejs.org/ (LTS version) and re-run this script."
fi

# ── 4. Python virtual environment ─────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/backend/venv"

if [ -d "$VENV_DIR" ]; then
    warn "Virtual environment already exists — skipping creation"
else
    info "Creating Python virtual environment..."
    "$PYTHON" -m venv "$VENV_DIR"
fi

# Activate and install
info "Installing Python dependencies..."
source "$VENV_DIR/bin/activate"
pip install --quiet --upgrade pip
pip install --quiet -r "$SCRIPT_DIR/backend/requirements.txt"
deactivate
info "Python dependencies installed"

# ── 5. Node / npm dependencies ────────────────────────────
info "Installing Node.js dependencies..."
cd "$SCRIPT_DIR/frontend"
npm install --silent
cd "$SCRIPT_DIR"
info "Node.js dependencies installed"

# ── 6. Pre-download ChromeDriver ──────────────────────────
info "Pre-downloading ChromeDriver for your Chrome version..."
source "$VENV_DIR/bin/activate"
"$PYTHON" - <<'EOF'
import subprocess, re, sys

# Detect Chrome version
try:
    out = subprocess.check_output(
        ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "--version"],
        stderr=subprocess.DEVNULL, text=True
    )
    m = re.search(r'(\d+)\.\d+\.\d+', out)
    version = int(m.group(1)) if m else None
except Exception:
    version = None

if not version:
    print("  Could not detect Chrome version — ChromeDriver will be downloaded on first run.")
    sys.exit(0)

print(f"  Chrome version detected: {version}")
try:
    import undetected_chromedriver as uc
    patcher = uc.Patcher(version_main=version)
    patcher.auto()
    print(f"  ChromeDriver ready at: {patcher.executable_path}")
except Exception as e:
    print(f"  Warning: could not pre-download ChromeDriver: {e}")
    print("  It will be downloaded automatically on first use.")
EOF
deactivate

echo ""
echo "=================================================="
echo "  Installation complete!"
echo ""
echo "  To start the app, run:"
echo "    bash start.sh"
echo ""
echo "  Then open:  http://localhost:5173"
echo "=================================================="
echo ""
