#!/usr/bin/env bash
set -euo pipefail

if command -v dwg2dxf >/dev/null 2>&1 && command -v dxf2dwg >/dev/null 2>&1; then
  echo "DWG import/export support is already available."
  echo "Import: $(command -v dwg2dxf)"
  echo "Export: $(command -v dxf2dwg)"
  exit 0
fi

sudo apt-get update
if apt-cache show libredwg-tools >/dev/null 2>&1; then
  sudo apt-get install -y libredwg-tools
else
  echo "libredwg-tools is not available from the configured Ubuntu repositories." >&2
  echo "Install LibreDWG manually, then set DWG2DXF_BIN and DXF2DWG_BIN." >&2
  exit 1
fi

command -v dwg2dxf >/dev/null 2>&1 && command -v dxf2dwg >/dev/null 2>&1 || {
  echo "Installation completed but dwg2dxf or dxf2dwg is still not in PATH." >&2
  exit 1
}
echo "DWG import installed: $(command -v dwg2dxf)"
echo "DWG export installed: $(command -v dxf2dwg)"
