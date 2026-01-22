#!/bin/bash
# Script to create a macOS app bundle for the GUI

cd "$(dirname "$0")"

APP_NAME="Slack Reconciliation"
APP_DIR="${APP_NAME}.app"
CONTENTS_DIR="${APP_DIR}/Contents"
MACOS_DIR="${CONTENTS_DIR}/MacOS"
RESOURCES_DIR="${CONTENTS_DIR}/Resources"

# Create app bundle structure
mkdir -p "${MACOS_DIR}"
mkdir -p "${RESOURCES_DIR}"

# Create Info.plist
cat > "${CONTENTS_DIR}/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>launcher</string>
    <key>CFBundleIdentifier</key>
    <string>com.candidatelabs.slackrecon</string>
    <key>CFBundleName</key>
    <string>${APP_NAME}</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.13</string>
</dict>
</plist>
EOF

# Create launcher script
cat > "${MACOS_DIR}/launcher" <<'EOF'
#!/bin/bash
# Get the directory containing the app bundle (project root)
APP_BUNDLE_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PROJECT_DIR="$(dirname "$APP_BUNDLE_DIR")"
cd "$PROJECT_DIR"

# Open Terminal window to show output
osascript <<APPLESCRIPT
tell application "Terminal"
    activate
    do script "cd \"$PROJECT_DIR\" && echo 'Starting Slack Reconciliation Dashboard...' && echo '' && source .venv/bin/activate && PYTHONPATH=src python serve_dashboard.py"
end tell
APPLESCRIPT
EOF

chmod +x "${MACOS_DIR}/launcher"

echo "App bundle created: ${APP_DIR}"
echo "You can now drag this app to your Applications folder or Desktop"

