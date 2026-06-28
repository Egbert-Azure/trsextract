#!/bin/bash
# build.sh - build TRS80Extract.app (SwiftUI wrapper for trsextract.py)
#
# Mirrors the TRS80Launcher build approach: swiftc with -parse-as-library
# (required because main.swift uses the @main attribute), then assemble a
# minimal .app bundle and copy trsextract.py into Resources so the app can
# find it at runtime.
#
# Usage:
#   ./build.sh                 # build using ./trsextract.py
#   ./build.sh /path/to/trsextract.py
#
set -euo pipefail

APP_NAME="TRS80Extract"
BUNDLE="${APP_NAME}.app"
SRC="Sources/main.swift"

# Where is the Python tool? Argument 1, or the repo-root ../trsextract.py
# (one level up from this TRS80Extract/ folder). A single canonical copy lives
# at the repo root; this wrapper does not keep its own duplicate.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTOOL="${1:-${SCRIPT_DIR}/../trsextract.py}"

if [[ ! -f "$PYTOOL" ]]; then
    echo "ERROR: trsextract.py not found at: $PYTOOL"
    echo "Pass its path as the first argument, e.g.:"
    echo "   ./build.sh ../TRS80M1/diskimages/NewDos/trsextract.py"
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
cp "$PYTOOL"          "${BUNDLE}/Contents/Resources/trsextract.py"

# 3. Info.plist
cat > "${BUNDLE}/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>            <string>${APP_NAME}</string>
  <key>CFBundleDisplayName</key>     <string>TRS-80 Disk Extract</string>
  <key>CFBundleIdentifier</key>      <string>de.schroeer.trs80extract</string>
  <key>CFBundleVersion</key>         <string>1.1</string>
  <key>CFBundleShortVersionString</key><string>1.1</string>
  <key>CFBundlePackageType</key>     <string>APPL</string>
  <key>CFBundleExecutable</key>      <string>${APP_NAME}</string>
  <key>LSMinimumSystemVersion</key>  <string>12.0</string>
  <key>NSHighResolutionCapable</key> <true/>
</dict>
</plist>
PLIST

echo "Done: ${BUNDLE}"
echo "Run with:  open ${BUNDLE}"
echo
echo "Note: this wrapper shells out to python3. The system needs Python 3"
echo "(stock macOS python3, or 'brew install python')."
