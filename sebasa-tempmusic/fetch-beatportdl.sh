#!/bin/sh
# Descarga el binario de Linux de beatportdl (última release) para la arquitectura actual.
set -eu
arch="${1:-}"
if [ -z "$arch" ]; then
  case "$(uname -m)" in
    x86_64) arch=amd64 ;;
    aarch64|arm64) arch=arm64 ;;
    *) echo "arquitectura no soportada: $(uname -m)"; exit 1 ;;
  esac
fi

api=https://api.github.com/repos/unspok3n/beatportdl/releases/latest
url=$(curl -fsSL "$api" \
  | grep -o '"browser_download_url": *"[^"]*"' | cut -d'"' -f4 \
  | grep -i linux | grep -i "$arch" | head -n1)
[ -n "$url" ] || { echo "No encontré un asset linux/$arch en la release"; exit 1; }
echo "Descargando $url"

mkdir -p /opt/beatportdl /tmp/bp && cd /tmp/bp
curl -fsSL -o asset "$url"
case "$url" in
  *.zip) unzip -o asset ;;
  *.tar.gz|*.tgz) tar xzf asset ;;
  *) cp asset beatportdl ;;
esac
bin=$(find . -maxdepth 3 -type f -name 'beatportdl*' ! -name '*.yml' ! -name '*.json' | head -n1)
[ -n "$bin" ] || { echo "No encontré el binario dentro del asset"; exit 1; }
install -m755 "$bin" /opt/beatportdl/beatportdl
rm -rf /tmp/bp
