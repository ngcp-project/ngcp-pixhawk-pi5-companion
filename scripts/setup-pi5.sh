#!/usr/bin/env bash
# ============================================================================
# setup-pi5.sh — NGCP MRA Pi 5 Companion Computer Provisioning Script
# ============================================================================
#
# PURPOSE:
#   Fully automated setup of a fresh Raspberry Pi 5 running Ubuntu 24.04
#   Desktop for the NGCP MRA telemetry pipeline. Reconstructs the entire
#   development environment so a new SD card is flight-ready in one command.
#
# USAGE:
#   curl -fsSL <raw-github-url>/scripts/setup-pi5.sh | bash
#   — or —
#   git clone https://github.com/ngcp-project/ngcp-pixhawk-pi5-companion.git ~/work/ngcp-pixhawk-pi5-companion
#   cd ~/work/ngcp-pixhawk-pi5-companion
#   ./scripts/setup-pi5.sh
#
# ASSUMPTIONS:
#   - Running on a Raspberry Pi 5 with Ubuntu 24.04 Desktop
#   - User has sudo access
#   - Internet connectivity is available
#   - The target user is the currently logged-in user
#
# WHAT THIS SCRIPT DOES (in order):
#   Phase 1: System packages (git, python3, pipx, etc.)
#   Phase 2: UART overlay for Pixhawk serial communication
#   Phase 3: MAVProxy + pymavlink via pipx
#   Phase 4: Repository clone + submodule init
#   Phase 5: GCS infrastructure library editable installs
#   Phase 6: MAVProxy autostart installation
#   Phase 7: Tailscale VPN
#   Phase 8: Smoke test
#
# IDEMPOTENT: Safe to re-run. Each phase checks for existing state before
#             making changes.
#
# ============================================================================
set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────────────
REPO_URL="https://github.com/ngcp-project/ngcp-pixhawk-pi5-companion.git"
REPO_BRANCH="ChadFeatureRequest"
WORK_DIR="${HOME}/work"
REPO_DIR="${WORK_DIR}/ngcp-pixhawk-pi5-companion"
BOOT_CONFIG="/boot/firmware/config.txt"

# Terminal colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# ── Helper Functions ───────────────────────────────────────────────────────

banner() {
    echo ""
    echo -e "${CYAN}╔══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${NC} ${BOLD}$1${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

info()    { echo -e "  ${GREEN}✔${NC} $1"; }
warn()    { echo -e "  ${YELLOW}⚠${NC} $1"; }
error()   { echo -e "  ${RED}✖${NC} $1"; }
step()    { echo -e "  ${CYAN}→${NC} $1"; }

check_root() {
    if [[ $EUID -eq 0 ]]; then
        error "Do not run this script as root. Run as your normal user (sudo will be invoked as needed)."
        exit 1
    fi
}

confirm_pi5() {
    if [[ -f /proc/device-tree/model ]]; then
        local model
        model=$(tr -d '\0' < /proc/device-tree/model)
        info "Detected hardware: ${model}"
    else
        warn "Cannot detect hardware model. Proceeding anyway."
    fi
}

# ── Phase 0: Pre-flight Checks ────────────────────────────────────────────

banner "Phase 0: Pre-flight Checks"
check_root
confirm_pi5
info "User: $(whoami)"
info "Home: ${HOME}"
info "Target repo: ${REPO_DIR}"

# ── Phase 1: System Packages ──────────────────────────────────────────────

banner "Phase 1: System Packages"

step "Updating apt package index..."
sudo apt update -qq

PACKAGES=(
    git
    python3
    python3-pip
    python3-venv
    pipx
    curl
    wget
    build-essential
    libxml2-dev
    libxslt1-dev
    libffi-dev
    libssl-dev
    openssh-server
    firefox
)

step "Installing required packages..."
sudo apt install -y -qq "${PACKAGES[@]}"
info "System packages installed."

# Ensure pipx is on PATH for the current session
step "Configuring pipx PATH..."
pipx ensurepath 2>/dev/null || true
# Source the updated PATH immediately
export PATH="${HOME}/.local/bin:${PATH}"
info "pipx configured."

# Enable SSH server
if systemctl is-active --quiet ssh 2>/dev/null; then
    info "SSH server already running."
else
    step "Enabling SSH server..."
    sudo systemctl enable --now ssh
    info "SSH server enabled and started."
fi

# ── Phase 2: UART Configuration ───────────────────────────────────────────

banner "Phase 2: UART Configuration (Pixhawk Serial)"

UART_CONFIGURED=false

if [[ -f "${BOOT_CONFIG}" ]]; then
    # Check if UART overlay is already configured
    if grep -q "^dtoverlay=uart0" "${BOOT_CONFIG}" 2>/dev/null || \
       grep -q "^enable_uart=1" "${BOOT_CONFIG}" 2>/dev/null; then
        info "UART overlay already configured in ${BOOT_CONFIG}."
        UART_CONFIGURED=true
    else
        step "Adding UART overlay to ${BOOT_CONFIG}..."
        sudo tee -a "${BOOT_CONFIG}" > /dev/null <<'UART_OVERLAY'

# ── NGCP MRA: Enable UART for Pixhawk TELEM2 connection ──
# The Cube Orange flight controller connects via TELEM2 (Serial2) to the
# Pi 5's GPIO UART pins. This overlay enables /dev/ttyAMA0.
# Pixhawk params: SERIAL2_PROTOCOL=2, SERIAL2_BAUD=57
dtoverlay=uart0
enable_uart=1
UART_OVERLAY
        info "UART overlay added. A reboot is required for this to take effect."
        UART_CONFIGURED=true
    fi
else
    warn "${BOOT_CONFIG} not found. If this is not a Pi 5 with Ubuntu, UART must be configured manually."
fi

# Disable serial console on ttyAMA0 (if active) — this conflicts with MAVProxy
if grep -q "console=serial0" /proc/cmdline 2>/dev/null; then
    step "Disabling serial console on ttyAMA0 (conflicts with MAVProxy)..."
    sudo sed -i 's/console=serial0,[0-9]* //g' /boot/firmware/cmdline.txt 2>/dev/null || true
    warn "Serial console disabled. Reboot required."
fi

# ── Phase 3: MAVProxy Installation ────────────────────────────────────────

banner "Phase 3: MAVProxy & pymavlink (via pipx)"

if command -v mavproxy.py >/dev/null 2>&1; then
    info "MAVProxy already installed: $(mavproxy.py --version 2>&1 | head -1)"
else
    step "Installing MAVProxy via pipx..."
    pipx install MAVProxy
    info "MAVProxy installed."
fi

# Verify pymavlink is available (it comes as a MAVProxy dependency)
step "Verifying pymavlink..."
if python3 -c "from pymavlink import mavutil; print('pymavlink OK')" 2>/dev/null; then
    info "pymavlink available in system Python."
elif "${HOME}/.local/share/pipx/venvs/mavproxy/bin/python" -c \
     "from pymavlink import mavutil; print('pymavlink OK')" 2>/dev/null; then
    info "pymavlink available in MAVProxy pipx venv."
else
    warn "pymavlink not detected. It should have been installed with MAVProxy."
    warn "Try: pipx inject mavproxy pymavlink"
fi

# ── Phase 4: Repository Clone & Submodules ─────────────────────────────────

banner "Phase 4: Repository Clone & Submodules"

mkdir -p "${WORK_DIR}"

if [[ -d "${REPO_DIR}/.git" ]]; then
    info "Repository already exists at ${REPO_DIR}."
    step "Fetching latest changes..."
    cd "${REPO_DIR}"
    git fetch origin
    git checkout "${REPO_BRANCH}" 2>/dev/null || git checkout -b "${REPO_BRANCH}" "origin/${REPO_BRANCH}"
    git pull origin "${REPO_BRANCH}" --ff-only || warn "Pull failed (possibly local changes). Skipping."
else
    step "Cloning repository..."
    git clone "${REPO_URL}" "${REPO_DIR}"
    cd "${REPO_DIR}"
    step "Checking out branch ${REPO_BRANCH}..."
    git checkout "${REPO_BRANCH}" 2>/dev/null || git checkout -b "${REPO_BRANCH}" "origin/${REPO_BRANCH}"
fi

step "Initialising git submodules..."
git submodule update --init --recursive
info "Submodules initialised:"
info "  lib/gcs-infrastructure"
info "  lib/gcs-packet"
info "  lib/xbee-python"

# ── Phase 5: GCS Infrastructure Library (editable installs) ───────────────

banner "Phase 5: GCS Infrastructure Libraries"

# The gcs_translator.py shebang points directly at the MAVProxy pipx venv's
# Python interpreter. We need to install the GCS libraries into that same venv
# so that the imports resolve correctly at runtime.

PIPX_PYTHON="${HOME}/.local/share/pipx/venvs/mavproxy/bin/python"
PIPX_PIP="${HOME}/.local/share/pipx/venvs/mavproxy/bin/pip"

if [[ -x "${PIPX_PYTHON}" ]]; then
    step "Installing GCS libraries into MAVProxy pipx venv (editable mode)..."

    # gcs-infrastructure (Application/ directory — provides InfrastructureInterface)
    if [[ -d "${REPO_DIR}/lib/gcs-infrastructure" ]]; then
        "${PIPX_PIP}" install -e "${REPO_DIR}/lib/gcs-infrastructure" 2>/dev/null && \
            info "gcs-infrastructure installed." || \
            warn "gcs-infrastructure install failed — check pyproject.toml"
    fi

    # gcs-packet (Packet/ directory — provides Telemetry, Command, Enum)
    if [[ -d "${REPO_DIR}/lib/gcs-packet" ]]; then
        "${PIPX_PIP}" install -e "${REPO_DIR}/lib/gcs-packet" 2>/dev/null && \
            info "gcs-packet installed." || \
            warn "gcs-packet install failed — check pyproject.toml"
    fi

    # xbee-python (src/ directory — XBee serial driver)
    if [[ -d "${REPO_DIR}/lib/xbee-python" ]]; then
        "${PIPX_PIP}" install -e "${REPO_DIR}/lib/xbee-python" 2>/dev/null && \
            info "xbee-python installed." || \
            warn "xbee-python install failed — check pyproject.toml"
    fi
else
    error "MAVProxy pipx venv not found at ${PIPX_PYTHON}."
    error "Cannot install GCS libraries. Run Phase 3 first."
fi

# ── Phase 6: MAVProxy Autostart ────────────────────────────────────────────

banner "Phase 6: MAVProxy Autostart & Launcher Scripts"

cd "${REPO_DIR}"

# Make scripts executable (git may not preserve permissions on fresh clone)
step "Setting script permissions..."
chmod +x scripts/ngcp-mavproxy-telemetry.sh
chmod +x scripts/ngcp-mavproxy-autostart.sh
chmod +x scripts/install-mavproxy-autostart.sh
chmod +x scripts/gcs_translator.py
chmod +x scripts/gui_server.py
info "Script permissions set."

# Run the autostart installer
step "Installing autostart entries..."
./scripts/install-mavproxy-autostart.sh
info "Autostart installed:"
info "  ~/.local/bin/ngcp-mavproxy-telemetry"
info "  ~/.local/bin/ngcp-mavproxy-autostart"
info "  ~/.config/autostart/ngcp-mavproxy.desktop"

# ── Phase 7: Tailscale VPN ─────────────────────────────────────────────────

banner "Phase 7: Tailscale VPN (Optional)"

if command -v tailscale >/dev/null 2>&1; then
    info "Tailscale already installed."
    TS_STATUS=$(tailscale status 2>&1 || true)
    if echo "${TS_STATUS}" | grep -q "Logged out"; then
        warn "Tailscale is installed but not authenticated."
        warn "Run: sudo tailscale up"
    else
        info "Tailscale status: connected."
    fi
else
    step "Installing Tailscale..."
    curl -fsSL https://tailscale.com/install.sh | sh
    info "Tailscale installed."
    warn "Authenticate with: sudo tailscale up"
    warn "This requires interactive login — skipping automatic auth."
fi

# ── Phase 8: Smoke Test ───────────────────────────────────────────────────

banner "Phase 8: Smoke Test"

PASS=0
FAIL=0
WARN_COUNT=0

# Test 1: MAVProxy binary
if command -v mavproxy.py >/dev/null 2>&1; then
    info "[PASS] mavproxy.py found on PATH"
    ((PASS++))
else
    error "[FAIL] mavproxy.py not found"
    ((FAIL++))
fi

# Test 2: pymavlink import
if "${PIPX_PYTHON}" -c "from pymavlink import mavutil" 2>/dev/null; then
    info "[PASS] pymavlink importable in MAVProxy venv"
    ((PASS++))
else
    error "[FAIL] pymavlink not importable"
    ((FAIL++))
fi

# Test 3: GCS infrastructure import
if "${PIPX_PYTHON}" -c "from Infrastructure.InfrastructureInterface import LaunchVehicleXBee" 2>/dev/null; then
    info "[PASS] InfrastructureInterface importable"
    ((PASS++))
else
    warn "[WARN] InfrastructureInterface not importable (may need manual install)"
    ((WARN_COUNT++))
fi

# Test 4: Telemetry import (correct namespace)
if "${PIPX_PYTHON}" -c "from Telemetry.Telemetry import Telemetry" 2>/dev/null; then
    info "[PASS] Telemetry class importable (correct namespace)"
    ((PASS++))
else
    warn "[WARN] Telemetry class not importable (check gcs-packet install)"
    ((WARN_COUNT++))
fi

# Test 5: UART device
if [[ -e /dev/ttyAMA0 ]]; then
    info "[PASS] /dev/ttyAMA0 exists"
    ((PASS++))
else
    warn "[WARN] /dev/ttyAMA0 not found (reboot may be required for UART overlay)"
    ((WARN_COUNT++))
fi

# Test 6: Autostart files
if [[ -x "${HOME}/.local/bin/ngcp-mavproxy-telemetry" ]] && \
   [[ -f "${HOME}/.config/autostart/ngcp-mavproxy.desktop" ]]; then
    info "[PASS] Autostart entries installed"
    ((PASS++))
else
    error "[FAIL] Autostart entries missing"
    ((FAIL++))
fi

# Test 7: Git submodules populated
if [[ -f "${REPO_DIR}/lib/gcs-infrastructure/README.md" ]] || \
   [[ -d "${REPO_DIR}/lib/gcs-infrastructure/Application" ]]; then
    info "[PASS] gcs-infrastructure submodule populated"
    ((PASS++))
else
    error "[FAIL] gcs-infrastructure submodule empty"
    ((FAIL++))
fi

# Test 8: SSH server
if systemctl is-active --quiet ssh 2>/dev/null; then
    info "[PASS] SSH server running"
    ((PASS++))
else
    warn "[WARN] SSH server not running"
    ((WARN_COUNT++))
fi

# Test 9: Web GUI files
if [[ -f "${REPO_DIR}/web/index.html" ]] && \
   [[ -f "${REPO_DIR}/web/app.js" ]] && \
   [[ -f "${REPO_DIR}/web/style.css" ]]; then
    info "[PASS] Web GUI files present"
    ((PASS++))
else
    error "[FAIL] Web GUI files missing"
    ((FAIL++))
fi

# ── Summary ────────────────────────────────────────────────────────────────

banner "Setup Complete — Summary"

echo -e "  ${GREEN}Passed:${NC}  ${PASS}"
echo -e "  ${YELLOW}Warnings:${NC} ${WARN_COUNT}"
echo -e "  ${RED}Failed:${NC}  ${FAIL}"
echo ""

if [[ ${FAIL} -eq 0 ]]; then
    echo -e "  ${GREEN}${BOLD}All critical checks passed!${NC}"
else
    echo -e "  ${RED}${BOLD}${FAIL} critical check(s) failed. Review the output above.${NC}"
fi

echo ""
echo -e "${CYAN}────────────────────────────────────────────────────────────────${NC}"
echo -e "${BOLD}Next Steps:${NC}"
echo ""

if ! ${UART_CONFIGURED:-false} || [[ ! -e /dev/ttyAMA0 ]]; then
    echo -e "  ${YELLOW}1.${NC} Reboot to activate UART overlay:"
    echo -e "     ${CYAN}sudo reboot${NC}"
    echo ""
fi

echo -e "  ${YELLOW}2.${NC} Connect Pixhawk TELEM2 to Pi 5 GPIO UART (TX→RX, RX→TX, GND→GND)"
echo -e "  ${YELLOW}3.${NC} Plug XBee XR 900 MHz radio into USB"
echo -e "  ${YELLOW}4.${NC} Test manually:"
echo -e "     ${CYAN}mavproxy.py --master=/dev/ttyAMA0 --baudrate=57600${NC}"
echo -e "  ${YELLOW}5.${NC} If Tailscale needed: ${CYAN}sudo tailscale up${NC}"
echo -e "  ${YELLOW}6.${NC} Reboot and the full pipeline will auto-launch!"
echo ""
echo -e "${CYAN}────────────────────────────────────────────────────────────────${NC}"
echo -e "${BOLD}Repo:${NC}     ${REPO_DIR}"
echo -e "${BOLD}Branch:${NC}   ${REPO_BRANCH}"
echo -e "${BOLD}Pipeline:${NC} MAVProxy → gcs_translator.py → XBee XR → GCS"
echo -e "${CYAN}────────────────────────────────────────────────────────────────${NC}"
