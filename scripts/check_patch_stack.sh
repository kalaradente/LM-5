#!/bin/bash
#
# check_patch_stack.sh — early-warning drift check for patches/ (audit #9).
#
# Verifies the three patches apply cleanly, in wizard glob order, on:
#   (a) the PINNED upstream commit (UPSTREAM_COMMIT in setup_wizard.sh) —
#       must ALWAYS pass; a failure here means a patch was edited without
#       re-verifying, and a Pi bring-up would break today; and
#   (b) current upstream HEAD — allowed to fail, but a failure is the
#       T-3 signal (upstream moved under us): rebase the stack and bump
#       the pin ON YOUR SCHEDULE instead of discovering it on bring-up
#       day. (T-3 history: upstream merged PR #139 between our
#       verification and a fresh clone, and ui_redesign.patch silently
#       stopped applying — the wizard's patch loop warns-and-continues,
#       so the Pi would have served the STOCK UI.)
#
# Needs network. Exit codes: 0 = pin OK + HEAD OK; 1 = pin BROKEN;
# 2 = pin OK but HEAD drifted (rebase soon).
#
# Usage: ./scripts/check_patch_stack.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
UPSTREAM_URL="https://github.com/jewbetcha/openflight.git"
UPSTREAM_COMMIT="$(grep -m1 '^UPSTREAM_COMMIT=' "$SCRIPT_DIR/setup_wizard.sh" | cut -d'"' -f2)"
[ -n "$UPSTREAM_COMMIT" ] || { echo "[check] can't read UPSTREAM_COMMIT from setup_wizard.sh"; exit 1; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/patchcheck.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

apply_stack() {  # $1 = checkout dir; returns nonzero on first failing patch
    local ok=0
    for PATCH in "$REPO_ROOT"/patches/*.patch; do
        [ -f "$PATCH" ] || continue
        if git -C "$1" apply "$PATCH" 2>/dev/null; then
            echo "  applied  $(basename "$PATCH")"
        else
            echo "  FAILED   $(basename "$PATCH")"
            ok=1
        fi
    done
    return $ok
}

fetch_at() {  # $1 = dir, $2 = ref/sha
    git init -q "$1"
    git -C "$1" remote add origin "$UPSTREAM_URL"
    git -C "$1" fetch -q --depth 1 origin "$2"
    git -C "$1" checkout -q FETCH_HEAD
}

echo "[check] (a) pinned commit ${UPSTREAM_COMMIT:0:7}"
fetch_at "$WORK/pin" "$UPSTREAM_COMMIT"
PIN_OK=0
apply_stack "$WORK/pin" || PIN_OK=1

echo "[check] (b) upstream HEAD"
fetch_at "$WORK/head" "HEAD"
HEAD_SHA="$(git -C "$WORK/head" rev-parse --short HEAD)"
echo "  HEAD is $HEAD_SHA"
HEAD_OK=0
if [ "$(git -C "$WORK/head" rev-parse HEAD)" = "$UPSTREAM_COMMIT" ]; then
    echo "  HEAD == pin; nothing to drift"
else
    apply_stack "$WORK/head" || HEAD_OK=1
fi

if [ "$PIN_OK" -ne 0 ]; then
    echo "[check] RESULT: PIN BROKEN — a patch no longer applies on the pinned"
    echo "        commit. Fix before any Pi bring-up; something was edited"
    echo "        without re-verifying the stack."
    exit 1
elif [ "$HEAD_OK" -ne 0 ]; then
    echo "[check] RESULT: pin OK, but upstream HEAD ($HEAD_SHA) has DRIFTED past"
    echo "        the stack. No urgency for the Pi (the wizard clones the pin),"
    echo "        but rebase + re-verify + bump the pin soon — audit #9 T-3."
    exit 2
fi
echo "[check] RESULT: all green — stack applies at the pin and at HEAD ($HEAD_SHA)."
