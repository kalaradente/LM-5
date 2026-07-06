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

# ---- 0. Vendor openflight_upstream + apply our patches --------------------

log "Step 0: upstream OpenFlight checkout"
if [ -d "$UPSTREAM_DIR" ]; then
    log "$UPSTREAM_DIR already present, leaving the checkout as-is."
else
    log "Cloning $UPSTREAM_URL -> $UPSTREAM_DIR ..."
    git clone --depth 1 "$UPSTREAM_URL" "$UPSTREAM_DIR"
    log "Cloned."
fi
# Re-apply our upstream changes: every patch in patches/, all additive and
# order-independent (disjoint contexts, verified applying both ways):
#   simulate_custom_shot.patch -- the mock-only injection handler that
#       shot_simulator.py --live needs.
#   session_mode.patch -- set/get_session_mode SocketIO events + the web
#       UI's 3-way mode picker (indoor/outdoor/speed) and speed-training
#       swing view. Without it the hardware still runs; the picker just
#       never appears and swings render as 0-mph shot cards.
# Checked on EVERY run, not just fresh clones: the "safe to re-run" promise
# has to cover a manually-cloned or interrupted checkout too, or these
# features break silently later.
for PATCH in "$REPO_ROOT"/patches/*.patch; do
    [ -f "$PATCH" ] || continue
    PATCH_NAME="$(basename "$PATCH")"
    if git -C "$UPSTREAM_DIR" apply --reverse --check "$PATCH" 2>/dev/null; then
        log "$PATCH_NAME already applied."
    elif git -C "$UPSTREAM_DIR" apply --check "$PATCH" 2>/dev/null; then
        git -C "$UPSTREAM_DIR" apply "$PATCH"
        log "Applied $PATCH_NAME."
    else
        warn "$PATCH_NAME neither applied nor appliable (upstream may have"
        warn "moved on). The feature it carries may not work until it's"
        warn "re-applied by hand; run_iwr6843.py and offline sims are"
        warn "unaffected."
    fi
done

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

log "Step 3: HiFiBerry kernel overlay (DAC2 ADC Pro, or the older DAC+ ADC Pro -- same overlay)"
BOOT_CONFIG=""
for candidate in /boot/firmware/config.txt /boot/config.txt; do
    [ -f "$candidate" ] && BOOT_CONFIG="$candidate" && break
done
if [ -z "$BOOT_CONFIG" ]; then
    warn "No /boot/firmware/config.txt or /boot/config.txt -- not on a Pi, skipping."
else
    if grep -q "^dtoverlay=hifiberry-dacplusadcpro" "$BOOT_CONFIG" 2>/dev/null; then
        log "hifiberry-dacplusadcpro overlay already enabled in $BOOT_CONFIG."
    else
        log "Adding dtoverlay=hifiberry-dacplusadcpro to $BOOT_CONFIG (needs sudo)."
        echo "dtoverlay=hifiberry-dacplusadcpro" | sudo tee -a "$BOOT_CONFIG" >/dev/null
        NEED_REBOOT=1
    fi
    # Pi 5 specific: the card's onboard ID EEPROM can conflict with the
    # dtoverlay line above and silently prevent it from loading. Confirmed
    # against HiFiBerry's own docs/forum for DAC2 ADC Pro on Pi 5.
    if grep -q "^force_eeprom_read=0" "$BOOT_CONFIG" 2>/dev/null; then
        log "force_eeprom_read=0 already set in $BOOT_CONFIG."
    else
        log "Adding force_eeprom_read=0 to $BOOT_CONFIG (Pi 5 + HiFiBerry EEPROM/overlay conflict workaround, needs sudo)."
        echo "force_eeprom_read=0" | sudo tee -a "$BOOT_CONFIG" >/dev/null
        NEED_REBOOT=1
    fi
    if [ "$NEED_REBOOT" -eq 1 ]; then
        warn "REBOOT REQUIRED before the HiFiBerry card will show up in aplay -l."
    fi
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
# The standalone ISK's USB runs through a SiLabs CP2105 dual-UART bridge
# (SWRU546E section 3.8), so it enumerates as /dev/ttyUSB* on Linux -- no
# driver install needed, cp210x is built into Raspberry Pi OS. (Windows
# needs the SiLabs CP210x VCP driver.) ttyACM* is also globbed below ONLY
# for the case of an MMWAVEICBOOST carrier (whose XDS110 probe is CDC-ACM
# class) -- not our topology, but harmless to check.
# (not `mapfile` -- bash 3.2 on macOS doesn't have it; this works on both
# that and the Pi's modern bash)
PORTS=()
while IFS= read -r line; do
    [ -n "$line" ] && PORTS+=("$line")
done < <(ls /dev/ttyACM* /dev/ttyUSB* 2>/dev/null || true)

if [ ${#PORTS[@]} -eq 0 ]; then
    error "No /dev/ttyUSB*/ttyACM* devices found. Plug in the IWR6843ISK and re-run."
    error "(cp210x is built into Raspberry Pi OS -- if lsusb sees a Silicon Labs"
    error "CP2105 [10c4:ea70] but no /dev/ttyUSB* appears, check dmesg for the"
    error "cp210x driver binding; also confirm the ISK's S1.5 switch is OFF so the"
    error "user UART is routed to the USB connector J5, not the 60-pin header.)"
    CLI_PORT=""
    GEOM_PORT=""
elif [ ${#PORTS[@]} -ne 2 ]; then
    error "Expected exactly 2 ports (IWR6843 CLI+data), found ${#PORTS[@]}: ${PORTS[*]}"
    error "The 'no other USB serial devices' assumption doesn't hold here --"
    error "falling back to asking, since guessing wrong silently misconfigures capture."
    for i in "${!PORTS[@]}"; do echo "  [$i] ${PORTS[$i]}"; done
    read -r -p "Which index is the CLI port (115200 baud)? " cli_idx
    read -r -p "Which index is the DATA port (921600 baud)? " geom_idx
    # Validate before indexing: a typo here would either crash the wizard
    # (set -e + bad subscript) or silently write an empty port to
    # hardware.env, which is exactly the misconfiguration this fallback
    # exists to prevent.
    if ! [[ "$cli_idx" =~ ^[0-9]+$ ]] || ! [[ "$geom_idx" =~ ^[0-9]+$ ]] ||
            [ "$cli_idx" -ge ${#PORTS[@]} ] || [ "$geom_idx" -ge ${#PORTS[@]} ] ||
            [ "$cli_idx" = "$geom_idx" ]; then
        error "Invalid selection: need two DIFFERENT indices in 0-$(( ${#PORTS[@]} - 1 ))."
        error "Re-run the wizard and try again."
        exit 1
    fi
    CLI_PORT="${PORTS[$cli_idx]}"
    GEOM_PORT="${PORTS[$geom_idx]}"
else
    # Exactly 2 ports, nothing else expected on the bus: assume both belong
    # to the ISK's CP2105 bridge, which exposes two UART interfaces off one
    # composite USB device ("Enhanced" = interface 0, "Standard" =
    # interface 1). Per TI's UniFlash doc the Enhanced port is the
    # CFG/User UART (our CLI port) and the Standard port is the data port
    # -- matching the interface-number sort below. Printed so it's
    # checkable against rung 1 (TI Demo Visualizer) rather than a silent
    # black box.
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
    # Input routing FIRST (DAC2 ADC Pro datasheet, mixer-controls table):
    # the ADC input mux must be pointed at the single-ended onboard input
    # (VINL1[SE]/VINR1[SE]) for our unbalanced K-MC1 wiring -- if it's left
    # on the balanced {VINxP,VINxM}[DIFF] pair, capture reads nothing and
    # it looks exactly like a dead radar. Mic bias must stay OFF: it would
    # inject DC into the K-MC1's outputs (also keep the board's mic-bias
    # jumpers open -- that half is hardware, see docs/kmc1-harness.md).
    log "Routing ADC inputs to the single-ended onboard input (datasheet: VINL1/VINR1[SE])..."
    amixer -c "$CARD_INDEX" sset "ADC Mic Bias" "Mic Bias off" >/dev/null 2>&1 || \
        warn "Couldn't set 'ADC Mic Bias' -- check control names with: amixer -c $CARD_INDEX controls"
    amixer -c "$CARD_INDEX" sset "ADC Left Input" "VINL1[SE]" >/dev/null 2>&1 || \
        warn "Couldn't set 'ADC Left Input' -- capture may read the wrong input pins."
    amixer -c "$CARD_INDEX" sset "ADC Right Input" "VINR1[SE]" >/dev/null 2>&1 || \
        warn "Couldn't set 'ADC Right Input' -- capture may read the wrong input pins."
    log "Mixer controls on card $CARD_INDEX:"
    python3 -m openflight_iwr6843.gain list --card "$CARD_INDEX" 2>&1 || \
        warn "gain.py couldn't list controls (pyalsaaudio installed? on Linux?)."
    read -r -p "Capture gain control name (datasheet examples use 'ADC'): " GAIN_CONTROL
    read -r -p "Initial gain in dB, -12 to +32 (suggest 0: the K-MC1 clips internally before the ADC does at 0dB, so negative gain buys nothing): " GAIN_DB
    if [ -n "$GAIN_CONTROL" ] && [ -n "$GAIN_DB" ]; then
        python3 -m openflight_iwr6843.gain set "$GAIN_DB" \
            --card "$CARD_INDEX" --control "$GAIN_CONTROL" 2>&1 || \
            warn "Could not set gain -- verify control name/card by hand."
    fi
    # Persist the mixer state NOW: ALSA only restores what alsa-restore
    # saved at the last CLEAN shutdown -- a power-yanked Pi boots with
    # driver defaults, and a reverted input mux is the exact "silent
    # capture that looks like a dead radar" trap from audit D-6.
    # (Belt and braces: run_iwr6843.py also re-asserts the routing from
    # hardware.env at every startup.)
    if command -v alsactl >/dev/null 2>&1; then
        if sudo alsactl store 2>/dev/null; then
            log "Mixer state stored (alsactl) -- survives hard power cuts."
        else
            warn "alsactl store failed -- mixer settings may not survive a"
            warn "power cut (run_iwr6843.py re-asserts them at startup anyway)."
        fi
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
# HiFiBerry ALSA card/gain: run_iwr6843.py re-asserts the ADC input mux,
# mic-bias-off, and (if GAIN_DB is set) capture gain on this card at every
# startup, so a power-yanked Pi can't boot into the wrong-mux/silent-capture
# state (audit D-6).
HIFIBERRY_CARD=$CARD_INDEX
GAIN_CONTROL=$GAIN_CONTROL
GAIN_DB=$GAIN_DB
EOF
log "Wrote $ENV_FILE"

echo
if [ "$NEED_REBOOT" -eq 1 ]; then
    warn "REBOOT (or at least log out/in) before running run_iwr6843.py --"
    warn "the HiFiBerry overlay and/or dialout group change needs a fresh session."
fi
echo
log "Hardware checklist -- things software CANNOT check (docs/kmc1-harness.md):"
log "  [ ] K-MC1 Pin 1 (/Enable) hardwired to GND. Internal 10k PULLUP:"
log "      a floating pin = radar silently OFF, no error anywhere."
log "  [ ] HiFiBerry mic-bias JUMPERS left open (the 'ADC Mic Bias off'"
log "      mixer control above is only the software half)."
log "  [ ] K-MC1 rotated so its 25-deg beam axis is VERTICAL (audit D-8 --"
log "      wrong rotation clips high wedge launches)."
log "  [ ] IWR6843 SOP switches back at functional mode 001 (S1.1 OFF) and"
log "      S1.5 OFF after flashing -- see docs/firmware-flashing.md."
echo
log "Next: bring-up ladder in openflight_iwr6843/README.md -- TI Demo"
log "Visualizer sanity check first, THEN run_iwr6843.py."
