#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"
APP_NAME="FFarm"
APP_BUNDLE="$DIST_DIR/${APP_NAME}.app"

mkdir -p "$DIST_DIR"
rm -rf "$APP_BUNDLE"

mkdir -p "$APP_BUNDLE/Contents/MacOS"
mkdir -p "$APP_BUNDLE/Contents/Resources"

cat > "$APP_BUNDLE/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>
  <string>FFarm</string>
  <key>CFBundleDisplayName</key>
  <string>FFarm</string>
  <key>CFBundleIdentifier</key>
  <string>com.kimgroth.ffarm</string>
  <key>CFBundleVersion</key>
  <string>1.0.0</string>
  <key>CFBundleShortVersionString</key>
  <string>1.0.0</string>
  <key>CFBundleExecutable</key>
  <string>FFarm</string>
  <key>LSMinimumSystemVersion</key>
  <string>12.0</string>
  <key>NSHighResolutionCapable</key>
  <true/>
</dict>
</plist>
PLIST

cp "$ROOT_DIR/scripts/ffarm_app_launcher.sh" "$APP_BUNDLE/Contents/MacOS/FFarm"
chmod +x "$APP_BUNDLE/Contents/MacOS/FFarm"

echo "[ffarm] Built $APP_BUNDLE"
