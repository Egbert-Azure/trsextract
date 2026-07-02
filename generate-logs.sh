#!/usr/bin/env bash
#
# generate-logs.sh - run trsextract listing over every disk image in a tree
# and save one log file per disk. Companion to catalog-logs.py.
# Copyright (C) 2026  Egbert Schroeer
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
# Usage:
#   ./generate-logs.sh [IMAGE_DIR] [LOG_DIR] [OUT_DIR]
#
#   IMAGE_DIR  directory to search for .dmk/.dsk/.jv1/.jv3 (default: .)
#   LOG_DIR    where to write per-disk .log files     (default: ./logs)
#   OUT_DIR    where to write Disk_Catalog.md and catalog.json
#              (default: . -- point this at your TRS80M1 checkout)
#
# Each disk's full listing (stdout) and the directory-scan diagnostics
# (stderr, via -v) are saved to LOG_DIR/<diskstem>.log. The listing is what
# catalog-logs.py reads; verbose stderr is kept for manual inspection.
#
# After the sweep, catalog-logs.py is run twice over LOG_DIR to render both
# catalog outputs into OUT_DIR: Disk_Catalog.md (browsable Markdown) and
# catalog.json (machine interface for TRS80Extract's Catalog tab). One
# command refreshes everything, so the two outputs can never drift apart.
#
# This does NOT extract files (no -o), so nothing is written to your disks or
# anywhere except LOG_DIR and OUT_DIR. Read-only over your collection.
#
# -----------------------------------------------------------------------------
# VERSION HISTORY
# -----------------------------------------------------------------------------
# 1.1  (2026-07-02)  One-command refresh. New optional OUT_DIR argument; after
#        the log sweep the script now runs catalog-logs.py (located next to
#        this script, like trsextract.py) twice to render Disk_Catalog.md and
#        catalog.json into OUT_DIR. Requires catalog-logs.py >= 1.3 (--json).
#        Logs remain intermediates in LOG_DIR; only the two catalog files are
#        written to OUT_DIR.
# 1.0  (2026-06-29)  First release. Recurses a directory tree for DMK/DSK/JV1/
#        JV3 images, runs the trsextract.py listing (-v) on each, and saves one
#        <diskstem>.log per image into LOG_DIR. Locates trsextract.py next to
#        this script or in $PWD. Flags any disk whose log contains ERROR
#        (hard-disk volumes, damaged directories) without stopping the run, and
#        prints an ok/flagged summary. Read-only over the image collection
#        (listing only, no -o). First sweep: 69 images, 66 clean, 3 flagged.
# -----------------------------------------------------------------------------

set -u

IMAGE_DIR="${1:-.}"
LOG_DIR="${2:-./logs}"
OUT_DIR="${3:-.}"

# locate trsextract.py: next to this script, else current dir
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if   [ -f "$SCRIPT_DIR/trsextract.py" ]; then TRS="$SCRIPT_DIR/trsextract.py"
elif [ -f "./trsextract.py" ];          then TRS="./trsextract.py"
else echo "ERROR: trsextract.py not found next to this script or in \$PWD." >&2; exit 1
fi

# locate catalog-logs.py the same way (needed for the catalog render step)
if   [ -f "$SCRIPT_DIR/catalog-logs.py" ]; then CAT="$SCRIPT_DIR/catalog-logs.py"
elif [ -f "./catalog-logs.py" ];          then CAT="./catalog-logs.py"
else echo "ERROR: catalog-logs.py not found next to this script or in \$PWD." >&2; exit 1
fi

PY="$(command -v python3 || true)"
[ -z "$PY" ] && { echo "ERROR: python3 not found in PATH." >&2; exit 1; }

mkdir -p "$LOG_DIR"

# collect images (case-insensitive, null-delimited for spaces in paths)
count=0; ok=0; fail=0
while IFS= read -r -d '' img; do
    count=$((count+1))
    stem="$(basename "$img")"; stem="${stem%.*}"
    log="$LOG_DIR/$stem.log"
    {
        echo "### trsextract listing"
        echo "### source: $img"
        echo "### generated: $(date '+%Y-%m-%d %H:%M:%S')"
        echo
        "$PY" "$TRS" "$img" -v
    } > "$log" 2>&1
    if grep -q "ERROR" "$log"; then
        fail=$((fail+1)); echo "  [warn] $stem -> see $log"
    else
        ok=$((ok+1));     echo "  [ok]   $stem"
    fi
done < <(find "$IMAGE_DIR" -type f \
            \( -iname '*.dmk' -o -iname '*.dsk' -o -iname '*.jv1' -o -iname '*.jv3' \) \
            -print0 | sort -z)

echo
echo "Done. $count image(s): $ok listed cleanly, $fail flagged (ERROR in log)."
echo "Logs in: $LOG_DIR"

# render both catalog outputs from the fresh logs.
# Write to temp files first and move into place only on success, so a failed
# render (e.g. empty LOG_DIR) never clobbers an existing catalog.
mkdir -p "$OUT_DIR"
echo "Rendering catalog into: $OUT_DIR"
if "$PY" "$CAT" "$LOG_DIR"        > "$OUT_DIR/Disk_Catalog.md.tmp" \
&& "$PY" "$CAT" "$LOG_DIR" --json > "$OUT_DIR/catalog.json.tmp"; then
    mv "$OUT_DIR/Disk_Catalog.md.tmp" "$OUT_DIR/Disk_Catalog.md"
    mv "$OUT_DIR/catalog.json.tmp"    "$OUT_DIR/catalog.json"
    echo "  $OUT_DIR/Disk_Catalog.md"
    echo "  $OUT_DIR/catalog.json   (Reload in TRS80Extract's Catalog tab)"
else
    rm -f "$OUT_DIR/Disk_Catalog.md.tmp" "$OUT_DIR/catalog.json.tmp"
    echo "ERROR: catalog render failed; existing catalog files left untouched." >&2
    exit 1
fi