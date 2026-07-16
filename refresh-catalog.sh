#!/usr/bin/env bash
#
# refresh-catalog.sh - one-command refresh of the published TRS80M1 disk
# catalog. Copyright (C) 2026  Egbert Schroeer
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# Thin wrapper around generate-logs.sh with this machine's fixed paths, so
# the day-to-day refresh needs no arguments and never requires copying
# Disk_Catalog.md / catalog.json into TRS80M1 by hand -- generate-logs.sh
# already renders straight into OUT_DIR.
#
# Usage:
#   ./refresh-catalog.sh                # use the defaults below
#   ./refresh-catalog.sh IMAGE_DIR OUT_DIR
#
#   IMAGE_DIR  disk-image collection (default: ../TRS80 Disks/diskimages)
#   OUT_DIR    TRS80M1 checkout's diskimages/ (default: ../TRS80M1/diskimages)
#
# Logs always go to ./logs next to this script (gitignored, never published).
#
# -----------------------------------------------------------------------------
# VERSION HISTORY
# -----------------------------------------------------------------------------
# 1.0  (2026-07-16)  First release. Fixes generate-logs.sh's three positional
#        arguments to this machine's sibling checkouts (trsextract, TRS80
#        Disks, TRS80M1) so the routine catalog refresh is a single
#        no-argument command instead of retyping paths / copying files by hand.
# -----------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

IMAGE_DIR="${1:-$SCRIPT_DIR/../TRS80 Disks/diskimages}"
OUT_DIR="${2:-$SCRIPT_DIR/../TRS80M1/diskimages}"
LOG_DIR="$SCRIPT_DIR/logs"

exec "$SCRIPT_DIR/generate-logs.sh" "$IMAGE_DIR" "$LOG_DIR" "$OUT_DIR"
