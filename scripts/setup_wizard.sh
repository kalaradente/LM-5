#!/bin/bash
#
# setup_wizard.sh — one-time hardware bring-up for the IWR6843 + K-MC1
# build, modeled on openflight_upstream's own scripts/setup/setup.sh (same
# idea: discover/configure real hardware, safe to re-run) but scoped to
# this rig instead of OPS243/K-LD7.
#
# Does NOT create a second venv -- reuses the repo-root .venv that
# shot_simulator.py and run_iwr6843.py already share with openflight.server's
# Flask/SocketIO stack. (openflight_upstream/scripts/setup/setup.sh makes its
# own separate .venv inside openflight_upstream/ -- deliberately not used
# here, to avoid two venvs with subtly different packages.)
#
# Assumes the ONLY USB serial devices on the bus are the IWR6843's two
# ports (CLI + data) -- if that's not true, port detection falls back to
# an interactive prompt instead of guessing.
#
# Steps (0-4 automatic, no prompts; 5-7 need a human judgment call; safe
# to re-run any time):
#   0. Clone openflight_upstream if missing
#   1. Python deps (repo-root .venv, requirements.txt)
#   2. Node.js/npm (via nvm) + React UI deps (openflight_upstream/ui)
#   3. HiFiBerry kernel overlay (/boot/firmware/config.txt, needs a reboot)
#   4. Serial port permissions (dialout group, needs logout/reboot)
#   5. IWR6843 CLI/data port auto-detect + persistent udev symlinks
#   6. alsa-utils (aplay/arecord/alsamixer) + HiFiBerry card + gain control
#      (needs your judgment on levels)
#   7. sounddevice input selection
#   8. write hardware.env for run_iwr6843.py to read as defaults
#
# Usage: ./scripts/setup_wizard.sh
# (fresh clone of this repo -> this is the one command to run)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$REPO_ROOT/hardware.env"
UPSTREAM_DIR="$REPO_ROOT/openflight_upstream"
UPSTREAM_URL="https://github.com/jewbetcha/openflight.git"
NEED_REBOOT=0

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log()  { echo -e "${GREEN}[wizard]${NC} $1"; }
warn() { echo -e "${YELLOW}[wizard]${NC} $1"; }
error(){ echo -e "${RED}[wizard]${NC} $1"; }

ask_yn() {
    read -r -p "$1 [y/N] " reply
    [[ "$reply" =~ ^[Yy]$ ]]
}

# ---- 0. Vendor openflight_upstream ---------------------------------------

log "Step 0: upstream OpenFlight checkout"
if [ -d "$UPSTREAM_DIR" ]; then
    log "$UPSTREAM_DIR already present, leaving it as-is."
else
    log "Cloning $UPSTREAM_URL -> $UPSTREAM_DIR ..."
    git clone --depth 1 "$UPSTREAM_URL" "$UPSTREAM_DIR"
    log "Cloned."
fi

# ---- 1. Python deps -------------------------------------------------------

log "Step 1: Python dependencies"
if [ ! -d "$REPO_ROOT/.venv" ]; then
    python3 -m venv "$REPO_ROOT/.venv"
    log "Created $REPO_ROOT/.venv"
fi
# shellcheck disable=SC1091
source "$REPO_ROOT/.venv/bin/activate"
pip install -q -r "$REPO_ROOT/requirements.txt"
log "Python dependencies installed."

# ---- 2. Node.js/npm + React UI deps --------------------------------------

log "Step 2: Node.js/npm + React UI dependencies"
export NVM_DIR="$HOME/.nvm"
if command -v npm >/dev/null 2>&1; then
    log "npm already on PATH ($(npm --version))."
elif [ -s "$NVM_DIR/nvm.sh" ]; then
    # shellcheck disable=SC1091
    . "$NVM_DIR/nvm.sh"
else
    log "Installing Node via nvm (no sudo, no dependence on apt package age)..."
    curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
    # shellcheck disable=SC1091
    . "$NVM_DIR/nvm.sh"
    nvm install --lts
fi
if [ -d "$UPSTREAM_DIR/ui" ]; then
    ( cd "$UPSTREAM_DIR/ui" && npm install )
    log "React UI dependencies installed."
else
    warn "$UPSTREAM_DIR/ui not found -- skipping npm install."
fi

# ---- 3. HiFiBerry kernel overlay ------------------------------------------

log "Step 3: HiFiBerry kernel overlay"
BOOT_CONFIG=""
for candidate in /boot/firmware/config.txt /boot/config.txt; do
    [ -f "$candidate" ] && BOOT_CONFIG="$candidate" && break
done
if [ -z "$BOOT_CONFIG" ]; then
    warn "No /boot/firmware/config.txt or /boot/config.txt -- not on a Pi, skipping."
elif grep -q "^dtoverlay=hifiberry-dacplusadcpro" "$BOOT_CONFIG" 2>/dev/null; then
    log "hifiberry-dacplusadcpro overlay already enabled in $BOOT_CONFIG."
else
    log "Adding dtoverlay=hifiberry-dacplusadcpro to $BOOT_CONFIG (needs sudo)."
    echo "dtoverlay=hifiberry-dacplusadcpro" | sudo tee -a "$BOOT_CONFIG" >/dev/null
    warn "REBOOT REQUIRED before the HiFiBerry card will show up in aplay -l."
    NEED_REBOOT=1
fi

# ---- 4. Serial port permissions (dialout group) --------------------------

log "Step 4: serial port permissions"
if ! command -v usermod >/dev/null 2>&1; then
    warn "usermod not found -- not on Linux, skipping."
elif groups "$USER" 2>/dev/null | grep -qw dialout; then
    log "$USER is already in the dialout group."
else
    log "Adding $USER to the dialout group (needs sudo)."
    sudo usermod -aG dialout "$USER"
    warn "LOG OUT/IN (or reboot) required before serial port access works without sudo."
    NEED_REBOOT=1
fi

# ---- 5. IWR6843 serial ports (automatic) ---------------------------------

log "Step 5: IWR6843 serial ports"
# (not `mapfile` -- bash 3.2 on macOS doesn't have it; this works on both
# that and the Pi's modern bash)
PORTS=()
while IFS= read -r line; do
    [ -n "$line" ] && PORTS+=("$line")
done < <(ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || true)

if [ ${#PORTS[@]} -eq 0 ]; then
    error "No /dev/ttyUSB*/ttyACM* devices found. Plug in the IWR6843ISK and re-run."
    CLI_PORT=""
    GEOM_PORT=""
elif [ ${#PORTS[@]} -ne 2 ]; then
    error "Expected exactly 2 ports (IWR6843 CLI+data), found ${#PORTS[@]}: ${PORTS[*]}"
    error "The 'no other USB serial devices' assumption doesn't hold here --"
    error "falling back to asking, since guessing wrong silently misconfigures capture."
    for i in "${!PORTS[@]}"; do echo "  [$i] ${PORTS[$i]}"; done
    read -r -p "Which index is the CLI port (115200 baud)? " cli_idx
    read -r -p "Which index is the DATA port (921600 baud)? " geom_idx
    CLI_PORT="${PORTS[$cli_idx]}"
    GEOM_PORT="${PORTS[$geom_idx]}"
else
    # Exactly 2 ports, nothing else expected on the bus: assume both belong
    # to the IWR6843's onboard XDS110 debug probe, which exposes two UART
    # interfaces off one composite USB device. Convention (not a datasheet
    # guarantee): interface 0 = Application/User UART = our CLI port,
    # interface 1 = Auxiliary Data Port = our streaming data port. Printed
    # below so it's checkable against rung 1 (TI Demo Visualizer) rather
    # than a silent black box.
    declare -A IFACE_NUM
    for p in "${PORTS[@]}"; do
        n=""
        if command -v udevadm >/dev/null 2>&1; then
            n=$(udevadm info -a "$p" 2>/dev/null \
                | grep -m1 'ATTRS{bInterfaceNumber}' \
                | grep -o '"[0-9]*"' | tr -d '"')
        fi
        IFACE_NUM["$p"]="${n:-?}"
    done

    sorted=$(for p in "${PORTS[@]}"; do echo "${IFACE_NUM[$p]} $p"; done | sort)
    CLI_PORT=$(echo "$sorted" | sed -n '1p' | awk '{print $2}')
    GEOM_PORT=$(echo "$sorted" | sed -n '2p' | awk '{print $2}')

    log "Detected: CLI_PORT=$CLI_PORT (interface ${IFACE_NUM[$CLI_PORT]}),"
    log "          GEOM_PORT=$GEOM_PORT (interface ${IFACE_NUM[$GEOM_PORT]})"
    warn "This is a convention-based guess, not verified against your specific"
    warn "board -- confirm against the TI mmWave Demo Visualizer (rung 1) the"
    warn "first time before trusting it for real captures."

    # Persistent naming: without this, hardware.env's raw /dev/ttyUSBn paths
    # can silently point at the wrong physical port after a reboot/replug,
    # since USB enumeration order isn't guaranteed.
    if command -v udevadm >/dev/null 2>&1 && [ -n "$BOOT_CONFIG" ]; then
        serial=$(udevadm info -a "$CLI_PORT" 2>/dev/null \
            | grep -m1 '{serial}' | grep -o '"[^"]*"' | tr -d '"')
        if [ -n "$serial" ] && [ "${IFACE_NUM[$CLI_PORT]}" != "?" ]; then
            log "Writing persistent udev rule (serial=$serial, needs sudo)..."
            sudo tee /etc/udev/rules.d/99-iwr6843.rules >/dev/null <<RULES
SUBSYSTEM=="tty", ATTRS{serial}=="$serial", ATTRS{bInterfaceNumber}=="${IFACE_NUM[$CLI_PORT]}", SYMLINK+="iwr6843_cli"
SUBSYSTEM=="tty", ATTRS{serial}=="$serial", ATTRS{bInterfaceNumber}=="${IFACE_NUM[$GEOM_PORT]}", SYMLINK+="iwr6843_data"
RULES
            sudo udevadm control --reload-rules
            sudo udevadm trigger
            if [ -e /dev/iwr6843_cli ] && [ -e /dev/iwr6843_data ]; then
                CLI_PORT=/dev/iwr6843_cli
                GEOM_PORT=/dev/iwr6843_data
                log "Persistent symlinks active: $CLI_PORT, $GEOM_PORT"
            else
                warn "Symlinks didn't appear yet (may need a replug). Using raw"
                warn "device paths for now -- re-run the wizard after replugging."
            fi
        else
            warn "Couldn't read a USB serial number/interface attr for a udev"
            warn "rule -- using raw device paths (not stable across reboots)."
        fi
    fi
fi

# ---- 6. HiFiBerry card + gain --------------------------------------------

log "Step 6: HiFiBerry capture card"
# alsa-utils gives aplay/arecord (bench captures) and alsamixer/amixer (the
# interactive "soundcard settings" TUI, alongside our programmatic gain.py).
# Not guaranteed on a fresh Raspberry Pi OS Lite image, and the rest of this
# step + the K-MC1 bench ladder assume it, so ensure it up front.
if command -v apt-get >/dev/null 2>&1 && ! command -v aplay >/dev/null 2>&1; then
    log "alsa-utils not present -- installing (needs sudo)..."
    sudo apt-get update -qq && sudo apt-get install -y -qq alsa-utils
fi
if command -v aplay >/dev/null 2>&1; then
    aplay -l 2>&1 || true
else
    warn "aplay not found (not on the Pi / couldn't install alsa-utils) -- skipping."
fi
read -r -p "HiFiBerry card index (blank to skip): " CARD_INDEX
if [ -n "$CARD_INDEX" ]; then
    log "Mixer controls on card $CARD_INDEX:"
    python3 -m openflight_iwr6843.gain list --card "$CARD_INDEX" 2>&1 || \
        warn "gain.py couldn't list controls (pyalsaaudio installed? on Linux?)."
    read -r -p "Capture gain control name (e.g. 'ADC Capture Volume'): " GAIN_CONTROL
    read -r -p "Initial gain in dB, -12 to +32 (suggest -12 for first bench test): " GAIN_DB
    if [ -n "$GAIN_CONTROL" ] && [ -n "$GAIN_DB" ]; then
        python3 -m openflight_iwr6843.gain set "$GAIN_DB" \
            --card "$CARD_INDEX" --control "$GAIN_CONTROL" 2>&1 || \
            warn "Could not set gain -- verify control name/card by hand."
    fi
else
    warn "Skipped -- set gain later with: python -m openflight_iwr6843.gain"
fi

# ---- 7. sounddevice input for AudioRing ----------------------------------

log "Step 7: audio input device (for shot_fusion.AudioRing / sounddevice)"
python3 -c "import sounddevice; print(sounddevice.query_devices())" 2>&1 || \
    warn "sounddevice not available in this venv -- install it if AudioRing needs it."
read -r -p "Audio device name or index for AUDIO_DEVICE (blank = sounddevice default): " AUDIO_DEVICE

# ---- 8. write hardware.env ------------------------------------------------

log "Step 8: writing $ENV_FILE"
cat > "$ENV_FILE" <<EOF
# Written by scripts/setup_wizard.sh -- read by run_iwr6843.py as defaults.
# Re-run the wizard any time hardware changes.
CLI_PORT=$CLI_PORT
GEOM_PORT=$GEOM_PORT
AUDIO_DEVICE=$AUDIO_DEVICE
# For reference only (gain.py takes --card/--control explicitly, doesn't
# read this file yet):
# HIFIBERRY_CARD=$CARD_INDEX
# GAIN_CONTROL=$GAIN_CONTROL
EOF
log "Wrote $ENV_FILE"

echo
if [ "$NEED_REBOOT" -eq 1 ]; then
    warn "REBOOT (or at least log out/in) before running run_iwr6843.py --"
    warn "the HiFiBerry overlay and/or dialout group change needs a fresh session."
fi
log "Next: bring-up ladder in openflight_iwr6843/README.md -- TI Demo"
log "Visualizer sanity check first, THEN run_iwr6843.py."
