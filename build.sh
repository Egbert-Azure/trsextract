#!/bin/bash
# build.sh - build TRS80Extract.app (SwiftUI wrapper for trsextract.py)
#
# Flat repo layout: trsextract.py, build.sh, Info.plist and Sources/ all live
# at the repository root. Uses swiftc with -parse-as-library (required because
# main.swift uses the @main attribute), then assembles a minimal .app bundle
# and copies trsextract.py into Resources so the app finds it at runtime.
#
# Usage:
#   ./build.sh                 # build using ./trsextract.py
#   ./build.sh /path/to/trsextract.py
#
# -----------------------------------------------------------------------------
# VERSION HISTORY
# -----------------------------------------------------------------------------
# 1.1  (2026-07-02)  Install step. After assembling the bundle, the app is now
#        copied into /Applications (or ~/Applications if /Applications is not
#        writable; no sudo), replacing any previous installed copy, so
#        Spotlight, Launchpad, and the Dock always launch the current build.
#        Quit a running instance before rebuilding.
# 1.0  (2026-06-28)  First release. Compiles Sources/main.swift with swiftc
#        (-parse-as-library for @main), assembles the minimal .app bundle, and
#        copies trsextract.py into Resources so the app is self-contained.
# -----------------------------------------------------------------------------
#
set -euo pipefail

APP_NAME="TRS80Extract"
BUNDLE="${APP_NAME}.app"
SRC="Sources/main.swift"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTOOL="${1:-${SCRIPT_DIR}/trsextract.py}"
PLIST="${SCRIPT_DIR}/Info.plist"

if [[ ! -f "$PYTOOL" ]]; then
    echo "ERROR: trsextract.py not found at: $PYTOOL"
    echo "Pass its path as the first argument if it lives elsewhere."
    exit 1
fi
if [[ ! -f "$PLIST" ]]; then
    echo "ERROR: Info.plist not found next to build.sh."
    exit 1
fi

echo "Building ${APP_NAME} ..."

# 1. Compile the Swift source.
mkdir -p build
swiftc -parse-as-library -O \
    -o "build/${APP_NAME}" \
    "$SRC"

# 2. Assemble the .app bundle.
rm -rf "$BUNDLE"
mkdir -p "${BUNDLE}/Contents/MacOS"
mkdir -p "${BUNDLE}/Contents/Resources"

cp "build/${APP_NAME}" "${BUNDLE}/Contents/MacOS/${APP_NAME}"
cp "$PYTOOL"           "${BUNDLE}/Contents/Resources/trsextract.py"
cp "$PLIST"            "${BUNDLE}/Contents/Info.plist"

echo "Done: ${BUNDLE}"

# 3. Install into /Applications (fall back to ~/Applications if not writable)
#    so Spotlight, Launchpad, and the Dock always see the current build.
if [[ -w "/Applications" ]]; then
    DEST="/Applications/${BUNDLE}"
else
    mkdir -p "$HOME/Applications"
    DEST="$HOME/Applications/${BUNDLE}"
fi
rm -rf "$DEST"
cp -R "$BUNDLE" "$DEST"
echo "Installed: ${DEST}"
echo "Run with:  open \"${DEST}\"   (or Spotlight / Dock)"
echo
echo "Note: this wrapper shells out to python3. The system needs Python 3"
echo "(stock macOS python3, or 'brew install python')."