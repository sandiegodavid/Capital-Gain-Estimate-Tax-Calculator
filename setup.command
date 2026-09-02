#!/bin/zsh
set -e
APP_DIR="${0:A:h}"
cd "$APP_DIR"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This setup script is intended for macOS."
  exit 1
fi

if [[ "$(uname -m)" != "arm64" ]]; then
  echo "This Mac is not running natively on Apple silicon. The app may still work, but this setup is optimized for Apple silicon."
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required but was not found."
  echo "Install Apple's Command Line Tools by running: xcode-select --install"
  echo "Then run setup.command again."
  exit 1
fi

PYTHON="$(command -v python3)"
if ! "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "Python 3.10 or newer is required. Found: $($PYTHON --version)"
  echo "Install a current Apple-silicon Python with Homebrew: brew install python"
  exit 1
fi

echo "Using: $($PYTHON --version)"
"$PYTHON" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -c 'import google.genai, xlsxwriter, yaml; print(f"Dependencies installed: XlsxWriter {xlsxwriter.__version__}, Google GenAI SDK, PyYAML {yaml.__version__}")'
echo
echo "Setup complete. Double-click launch.command to start the app."
read "REPLY?Press Return to close this window."
