#!/data/data/com.termux/files/usr/bin/bash
# orchestra-tx installer for Termux.
# Usage: sh install-termux.sh [--with-orchestra]
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
WITH_ORCHESTRA=0
for arg in "$@"; do
  case "$arg" in
    --with-orchestra) WITH_ORCHESTRA=1 ;;
    -h|--help)
      echo "usage: sh install-termux.sh [--with-orchestra]"
      exit 0
      ;;
    *)
      echo "unknown option: $arg" >&2
      exit 2
      ;;
  esac
done

if [ -d "/data/data/com.termux/files/usr" ] && [ "${PREFIX:-}" = "" ]; then
  echo "This does not look like a Termux shell (PREFIX is unset)." >&2
  echo "Run it from the Termux app: sh install-termux.sh" >&2
  exit 1
fi

echo "==> checking python"
if ! command -v python >/dev/null 2>&1; then
  echo "==> installing python"
  pkg install -y python
fi
python -c 'import sys; assert sys.version_info >= (3, 9), "python 3.9+ required"'
echo "    python $(python -c 'import platform; print(platform.python_version())')"

echo "==> upgrading pip"
python -m pip install --upgrade --no-input pip >/dev/null

if [ "$WITH_ORCHESTRA" -eq 1 ] || ! command -v orchestra >/dev/null 2>&1; then
  echo "==> installing orchestra-cli"
  python -m pip install --no-input orchestra-cli || {
    echo "!! orchestra-cli install failed; install it later with: pip install orchestra-cli" >&2
  }
fi

echo "==> installing orchestra-tx from $HERE"
python -m pip install --no-input -e "$HERE"

echo "==> verifying"
if command -v orchestra-tx >/dev/null 2>&1; then
  orchestra-tx --version
else
  echo "!! orchestra-tx is not on PATH. Add \$PREFIX/bin to PATH or run:" >&2
  echo "   python -m orchestra_tx --version" >&2
fi

cat <<'EOF'

Installed. Quick start:

  cd ~/projects/my-pipeline
  orchestra-tx init --goal "Ship the pipeline"
  orchestra-tx plan new "Ship the pipeline" --step "Validate YAML" --step "Run it"
  orchestra-tx session start
  orchestra-tx memory add "Uses ORCHESTRA_API_KEY from ~/.orchestra.env" -t auth
  orchestra-tx run -- pipeline validate pipeline.yaml
  orchestra-tx display README.txt

Tip: add this to ~/.bashrc for a status line on every shell:

  orchestra-tx session status 2>/dev/null

EOF
