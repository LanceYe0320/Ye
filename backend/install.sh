#!/usr/bin/env bash
# YE AI Coding Assistant — Linux/macOS installer
# Usage: curl -fsSL https://raw.githubusercontent.com/.../install.sh | bash
#   or:  bash install.sh

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
DIM='\033[2m'
BOLD='\033[1m'
RESET='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR"
VENV_DIR="$BACKEND_DIR/.venv"
ENV_FILE="$BACKEND_DIR/.env"

info()  { echo -e "${CYAN}[YE]${RESET} $*"; }
ok()    { echo -e "${GREEN}[YE]${RESET} $*"; }
warn()  { echo -e "${YELLOW}[YE]${RESET} $*"; }
err()   { echo -e "${RED}[YE]${RESET} $*" >&2; }

# ── 1. Check Python ──────────────────────────────────────────────────────────
check_python() {
    local py=""
    for cmd in python3 python python3.12 python3.11 python3.10; do
        if command -v "$cmd" &>/dev/null; then
            local ver
            ver=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
            local major minor
            major=$(echo "$ver" | cut -d. -f1)
            minor=$(echo "$ver" | cut -d. -f2)
            if [ "$major" -gt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -ge 10 ]; }; then
                py="$cmd"
                break
            fi
        fi
    done

    if [ -z "$py" ]; then
        err "Python >= 3.10 not found."
        echo ""
        info "Install Python 3.10+:"
        info "  macOS:  brew install python@3.12"
        info "  Ubuntu: sudo apt install python3.12 python3.12-venv"
        info "  Fedora: sudo dnf install python3.12"
        exit 1
    fi

    PY="$py"
    ok "Found Python: $PY ($($PY --version 2>&1))"
}

# ── 2. Create venv ───────────────────────────────────────────────────────────
create_venv() {
    if [ -d "$VENV_DIR" ]; then
        info "Virtual environment already exists at $VENV_DIR"
        return
    fi
    info "Creating virtual environment..."
    "$PY" -m venv "$VENV_DIR"
    ok "Virtual environment created."
}

# ── 3. Install dependencies ──────────────────────────────────────────────────
install_deps() {
    info "Installing dependencies (this may take a minute)..."
    "$VENV_DIR/bin/pip" install --upgrade pip --quiet
    "$VENV_DIR/bin/pip" install -e "$BACKEND_DIR"
    ok "Dependencies installed."
}

# ── 4. Setup .env ────────────────────────────────────────────────────────────
setup_env() {
    if [ -f "$ENV_FILE" ]; then
        # Check if ZHIPU_API_KEY is already set
        if grep -q "^ZHIPU_API_KEY=.\+" "$ENV_FILE" 2>/dev/null; then
            ok ".env already configured with API key."
            return
        fi
    fi

    echo ""
    warn "ZHIPU_API_KEY is required to use YE."
    info "Get your API key from: https://open.bigmodel.cn/"
    echo ""
    read -rp "$(echo -e "${CYAN}[YE]${RESET} Enter your ZHIPU_API_KEY (or press Enter to skip): ")" api_key

    cat > "$ENV_FILE" << EOF
# YE AI Coding Assistant Configuration
# Get your API key from https://open.bigmodel.cn/

ZHIPU_API_KEY=${api_key:-your-api-key-here}
ZHIPU_MODEL=glm-5.1
ZHIPU_BASE_URL=https://open.bigmodel.cn/api/coding/paas/v4/

# Server
HOST=0.0.0.0
PORT=8765

# Security (change in production)
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))" 2>/dev/null || echo "change-me-in-production")

# Data directory
DATA_DIR=./data
EOF

    if [ -z "$api_key" ]; then
        warn "No API key provided. Edit $ENV_FILE before running ye."
    else
        ok ".env configured."
    fi
}

# ── 5. Print success ─────────────────────────────────────────────────────────
print_success() {
    echo ""
    echo -e "${BOLD}${GREEN}  ╔══════════════════════════════════════╗${RESET}"
    echo -e "${BOLD}${GREEN}  ║     YE installed successfully!       ║${RESET}"
    echo -e "${BOLD}${GREEN}  ╚══════════════════════════════════════╝${RESET}"
    echo ""
    echo -e "  Start YE:"
    echo -e "    ${CYAN}cd $BACKEND_DIR${RESET}"
    echo -e "    ${CYAN}source .venv/bin/activate${RESET}"
    echo -e "    ${CYAN}ye${RESET}"
    echo ""
    echo -e "  Or directly:"
    echo -e "    ${CYAN}$VENV_DIR/bin/ye${RESET}"
    echo ""
    echo -e "  Quick test:"
    echo -e "    ${CYAN}ye -p \"Hello, introduce yourself\"${RESET}"
    echo ""

    if [ ! -f "$ENV_FILE" ] || grep -q "your-api-key-here" "$ENV_FILE" 2>/dev/null; then
        echo -e "  ${YELLOW}Don't forget to set ZHIPU_API_KEY in $ENV_FILE${RESET}"
        echo ""
    fi
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
    echo -e "${DIM}──────────────────────────────────────────────────${RESET}"
    echo -e "  ${BOLD}YE${RESET} ${DIM}AI Coding Assistant — Installer${RESET}"
    echo -e "${DIM}──────────────────────────────────────────────────${RESET}"
    echo ""

    check_python
    create_venv
    install_deps
    setup_env
    print_success
}

main "$@"
