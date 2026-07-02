#!/usr/bin/env python3
#
# catalog-logs.py - merge trsextract per-disk logs into one browsable catalog.
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
# Companion to generate-logs.sh.
#
# Usage:
#   python3 catalog-logs.py [LOG_DIR] > Disk_Catalog.md
#   python3 catalog-logs.py [LOG_DIR] --find PATTERN
#   python3 catalog-logs.py [LOG_DIR] --json > catalog.json
#       LOG_DIR   directory of <disk>.log files (default: ./logs)
#       --find    reverse index: which disk(s) hold a file whose NAME/EXT
#                 contains PATTERN (case-insensitive substring)
#       --json    dump the parsed catalog as JSON (machine interface for
#                 GUI front-ends such as TRS80Extract's Catalog tab)
#
# Reads the listing each log contains (the list_directory() output: a few
# header lines, then a "Filename Attr LRL EOFoff Extents" table), and emits a
# single Markdown document:
#   - a summary table (one row per disk: format, geometry, file count, flags)
#   - a per-disk section with the full file list, NON-STANDARD files marked
#
# "Jog memory" is the design goal: routine system files (BOOT/SYS, DIR/SYS,
# SYS0..SYS21, the standard utilities) are the same on every NEWDOS disk and
# carry no identity. The files that are unique to a disk - a named BASIC
# program, an odd extension, a personal tool - are what you'll recognise. Those
# are surfaced in a dedicated "distinctive files" line per disk and counted in
# the summary so you can skim for the disks worth opening.
#
# -----------------------------------------------------------------------------
# VERSION HISTORY
# -----------------------------------------------------------------------------
# 1.4  (2026-07-02)  Refresh hint in the generated Markdown header now points
#        at the single-command generate-logs.sh 1.1 (which renders both
#        Disk_Catalog.md and catalog.json in one run) instead of the old
#        two-command sequence. No functional change.
# 1.3  (2026-07-02)  Search and machine interface. New --find PATTERN mode:
#        reverse index (file -> disks) over the parsed listings, case-
#        insensitive substring match on NAME/EXT, results grouped by file with
#        the disks that carry it; error-flagged disks are reported separately
#        as unsearchable. New --json mode: dumps the full parsed catalog
#        (per-disk geometry, error state, file tuples with attr and
#        is-standard flag) for GUI front-ends -- TRS80Extract's Catalog tab
#        reads this instead of re-implementing log parsing, so the Python
#        parser and the standard-file filter rules stay the single source of
#        truth. The JSON source field carries the image basename only (same
#        privacy rule as 1.2). Argument handling moved to argparse; default
#        Markdown rendering unchanged.
# 1.2  (2026-06-30)  PRIVACY: emit only the image basename in Disk_Catalog.md,
#        never the absolute host path. The catalog is committed to a public
#        repo; the old `### source:` passthrough exposed the account name and
#        local directory tree (/Users/<name>/.../esnd-01.dmk). Sanitised at
#        build time, so rebuilding from existing logs cleans the markdown.
# 1.1  (2026-06-30)  FIX: false "damaged" flag on disks containing ERRORS/DAT.
#        Error detection matched the bare substring "ERROR" anywhere in a log,
#        so a disk whose directory simply lists a file named ERRORS/DAT
#        (esnd-15, esnd-25) was wrongly flagged and its row blanked. Detection
#        now requires a real trsextract error line -- "ERROR:" (incl. the
#        HD-volume notice) or "ERROR reading"/"ERROR writing" -- so genuine
#        failures (e.g. GAMES.DSK HD volume) still flag while the ERRORS/DAT
#        filename does not. esnd-15/25 now catalog as clean DMK (63 / 58 files).
# 1.0  (2026-06-29)  First release. Merges per-disk trsextract logs into a
#        single Markdown catalog: summary table (format, geometry, file count,
#        distinctive-file count, error flags) plus a per-disk section with the
#        full file list. Standard system furniture (BOOT/SYS, DIR/SYS,
#        SYS0-SYS21, common utilities) is filtered from the "distinctive files"
#        line so disk-identifying content stands out. Natural disk-name sort;
#        error logs surface as flagged rows. Output carries a self-documenting
#        header (auto-generated notice, refresh command, cross-reference to the
#        hand-maintained Disk_Inventory.md). First sweep: 69 images, 66 clean,
#        3 flagged.
# -----------------------------------------------------------------------------

__version__ = "1.4"

import argparse
import json
import os
import re
import sys
from collections import Counter

# ---- what counts as "standard / uninteresting" ----------------------------
# Routine NEWDOS/80 + G-DOS system and toolkit files present on most disks.
# A file matching these is system furniture, not a memory cue.
STD_NAMES = {
    "BOOT", "DIR", "BASIC", "BASICR",
    "INHALT", "GDOS",                       # G-DOS directory/system markers
}
STD_NAME_RE = [
    re.compile(r"^SYS\d{1,2}$"),            # SYS0..SYS21 overlays
]
# Standard utility programs (name/ext) seen across many disks.
STD_FULL = {
    "BUGOUT/CMD", "SUPERZAP/CMD", "DISASSEM/CMD", "EDTASM/CMD",
    "LMOFFSET/CMD", "LLIST80/CMD", "DIRCHECK/CMD", "ASPOOL/MAS",
    "FORMAT/CMD", "COPY/CMD", "CHAINBLD/BAS", "CHAINTST/JCL",
}
# Extensions that are inherently "content" (a user made these) -> distinctive.
CONTENT_EXTS = {
    "BAS", "ASM", "TXT", "DAT", "REL", "SAV", "DUM", "ASC", "JCL",
    "VC", "DRW", "HRG", "ILF", "PAS", "SRC", "OBJ", "SP",
}


def is_standard(name, ext):
    full = f"{name}/{ext}" if ext else name
    if full in STD_FULL:
        return True
    if not ext and name in STD_NAMES:
        return True
    if ext == "SYS":                        # all /SYS overlays & markers
        return True
    for rx in STD_NAME_RE:
        if rx.match(name):
            return True
    return False


# ---- log parsing -----------------------------------------------------------

HEADER_KEYS = ("trsextract", "Sides:", "Directory track:")


def parse_log(path):
    """Return dict(disk, fmt, tracks, sides, dirtrack, note, files=[(name,ext,attr)],
    error=str|None)."""
    disk = os.path.splitext(os.path.basename(path))[0]
    info = dict(disk=disk, fmt="?", tracks="?", sides="?", dirtrack="?",
                note="", files=[], error=None, source="")
    in_table = False
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            s = line.rstrip("\n")
            if s.startswith("### source:"):
                info["source"] = s.split(":", 1)[1].strip()
                continue
            # A genuine trsextract failure prints a line beginning with
            # "ERROR:" (e.g. "ERROR: no sectors decoded...", the HD-volume
            # notice "ERROR: no directory found...") or "ERROR reading/writing".
            # NOTE: a bare startswith("ERROR") is NOT enough -- the filename
            # ERRORS/DAT (on esnd-15 / esnd-25) also starts with those letters
            # and appears in the directory table. Require the colon or the
            # reading/writing verb so a real message is matched but a filename
            # is not.
            st = s.lstrip()
            if (st.startswith("ERROR:") or st.startswith("ERROR reading")
                    or st.startswith("ERROR writing")) and info["error"] is None:
                info["error"] = s.strip()
            m = re.search(r"trsextract\s+\S+\s+Format:\s+(\S+)\s+Tracks:\s+(\d+)", s)
            if m:
                info["fmt"], info["tracks"] = m.group(1), m.group(2)
                nm = re.search(r"\(note:.*?\)", s)
                if nm:
                    info["note"] = "over-read?"
                continue
            m = re.search(r"Sides:\s+(\d+)", s)
            if m:
                info["sides"] = m.group(1)
            m = re.search(r"Directory track:\s+(\d+(?:\s+side\s+\d+)?)", s)
            if m:
                info["dirtrack"] = m.group(1)
            if s.startswith("---"):
                in_table = True
                continue
            if s.startswith("Filename"):
                continue
            if re.match(r"\s*\d+\s+entries\.", s):
                in_table = False
                continue
            if in_table and s.strip():
                # "NAME/EXT  attr lrl eof extents"
                parts = s.split()
                if not parts:
                    continue
                fn = parts[0]
                name, _, ext = fn.partition("/")
                attr = parts[1] if len(parts) > 1 else ""
                info["files"].append((name, ext, attr))
    return info


# ---- rendering -------------------------------------------------------------

def render(infos):
    out = []
    out.append("# TRS-80 Disk Image Catalog\n")
    out.append("> **Auto-generated — do not edit by hand.** This is a machine "
               "file index produced by `catalog-logs.py` from per-disk "
               "extraction logs. For curated context (provenance, German "
               "annotations, damaged-disk notes, duplicate findings), see "
               "**`Disk_Inventory.md`**, which is the hand-maintained companion "
               "to this file.\n")
    out.append("> _Refresh:_ from the `trsextract` folder, "
               "`./generate-logs.sh <image-dir> ./logs <this-repo>` — renders "
               "this file and `catalog.json` in one run.\n")
    out.append(f"_Generated from {len(infos)} extraction log(s)._\n")
    out.append("Standard system files (BOOT/SYS, DIR/SYS, SYS0–SYS21, common "
               "utilities) are hidden from the **distinctive files** line so the "
               "content that identifies each disk stands out. The full file "
               "list per disk is below the summary.\n")

    # ---- summary table ----
    out.append("## Summary\n")
    out.append("| Disk | Fmt | Trk | Sides | Dir | Files | Distinctive | Notes |")
    out.append("|---|---|---|---|---|---|---|---|")
    for i in infos:
        if i["error"]:
            out.append(f"| **{i['disk']}** | — | — | — | — | — | — | "
                       f"⚠️ {i['error'][:48]} |")
            continue
        distinct = [(n, e) for (n, e, a) in i["files"] if not is_standard(n, e)]
        note = i["note"]
        out.append(f"| {i['disk']} | {i['fmt']} | {i['tracks']} | {i['sides']} "
                   f"| {i['dirtrack']} | {len(i['files'])} | "
                   f"{len(distinct)} | {note} |")
    out.append("")

    # ---- per-disk detail ----
    out.append("## Per-disk detail\n")
    for i in infos:
        out.append(f"### {i['disk']}\n")
        if i["source"]:
            # Show only the image filename, never the absolute host path.
            # Disk_Catalog.md is committed to a public repo; emitting the full
            # path (e.g. /Users/<name>/Documents/github/.../esnd-01.dmk) would
            # expose the user's account name and local directory structure.
            out.append(f"`{os.path.basename(i['source'])}`\n")
        if i["error"]:
            out.append(f"> ⚠️ **{i['error']}**\n")
            out.append("")
            continue
        out.append(f"- Format **{i['fmt']}**, {i['tracks']} tracks, "
                   f"{i['sides']} side(s), directory track {i['dirtrack']}"
                   + (f"  _(track count suggests an imaging over-read)_"
                      if i["note"] else "") + "\n")

        distinct = [(n, e) for (n, e, a) in i["files"] if not is_standard(n, e)]
        if distinct:
            shown = ", ".join(f"`{n}/{e}`" if e else f"`{n}`"
                              for n, e in distinct)
            out.append(f"- **Distinctive files ({len(distinct)}):** {shown}\n")
        else:
            out.append("- **Distinctive files:** none — looks like a plain "
                       "system/boot disk\n")

        # extension histogram (quick character of the disk)
        exts = Counter(e or "(none)" for _, e, _ in i["files"])
        hist = ", ".join(f"{e}×{c}" for e, c in exts.most_common())
        out.append(f"- File types: {hist}\n")

        # full list, collapsed
        full = " · ".join(f"{n}/{e}" if e else n for n, e, _ in i["files"])
        out.append("<details><summary>Full file list "
                   f"({len(i['files'])})</summary>\n")
        out.append(f"\n{full}\n\n</details>\n")
    return "\n".join(out)


# ---- search (--find) -------------------------------------------------------

def render_find(infos, pattern):
    """Reverse index: file -> disks. Case-insensitive substring on NAME/EXT."""
    pat = pattern.lower()
    hits = {}                               # "NAME/EXT" -> [disk, ...]
    skipped = []                            # error-flagged disks (unsearchable)
    for i in infos:
        if i["error"]:
            skipped.append(i["disk"])
            continue
        for n, e, _ in i["files"]:
            full = f"{n}/{e}" if e else n
            if pat in full.lower():
                hits.setdefault(full, []).append(i["disk"])
    out = []
    if not hits:
        out.append(f"No file matching '{pattern}' in {len(infos)} disk(s).")
    else:
        width = max(len(f) for f in hits)
        for full in sorted(hits, key=_natkey):
            out.append(f"{full:<{width}}  ->  {', '.join(hits[full])}")
        n_disks = len({d for ds in hits.values() for d in ds})
        out.append(f"\n{len(hits)} file(s) on {n_disks} disk(s).")
    if skipped:
        out.append(f"Not searched (extraction errors): {', '.join(skipped)}")
    return "\n".join(out)


# ---- machine interface (--json) ---------------------------------------------

def to_json(infos):
    """Full parsed catalog as JSON, for GUI front-ends. One object per disk;
    file tuples carry the is_standard() verdict so a GUI can offer the same
    distinctive-files view without duplicating the filter rules. The source
    field is the image basename only -- catalog.json may be committed or
    shared, so the 1.2 privacy rule (no absolute host paths) applies here
    exactly as it does to Disk_Catalog.md."""
    disks = []
    for i in infos:
        disks.append({
            "disk": i["disk"],
            "source": os.path.basename(i["source"]) if i["source"] else "",
            "error": i["error"],
            "format": i["fmt"],
            "tracks": i["tracks"],
            "sides": i["sides"],
            "dirtrack": i["dirtrack"],
            "note": i["note"],
            "files": [
                {"name": n, "ext": e, "attr": a,
                 "standard": is_standard(n, e)}
                for n, e, a in i["files"]
            ],
        })
    return json.dumps({"generator": f"catalog-logs.py {__version__}",
                       "disks": disks}, indent=2)


def main():
    ap = argparse.ArgumentParser(
        description="Merge trsextract per-disk logs into one browsable "
                    "catalog, search them, or dump them as JSON.")
    ap.add_argument("log_dir", nargs="?", default="./logs",
                    help="directory of <disk>.log files (default: ./logs)")
    ap.add_argument("--find", metavar="PATTERN",
                    help="reverse index: disks holding a file whose NAME/EXT "
                         "contains PATTERN (case-insensitive)")
    ap.add_argument("--json", action="store_true",
                    help="dump parsed catalog as JSON (for GUI front-ends)")
    args = ap.parse_args()

    if not os.path.isdir(args.log_dir):
        print(f"ERROR: log dir not found: {args.log_dir}", file=sys.stderr)
        sys.exit(1)
    logs = sorted(
        (os.path.join(args.log_dir, f) for f in os.listdir(args.log_dir)
         if f.endswith(".log")),
        key=lambda p: _natkey(os.path.basename(p)),
    )
    if not logs:
        print(f"ERROR: no .log files in {args.log_dir}", file=sys.stderr)
        sys.exit(1)
    infos = [parse_log(p) for p in logs]

    if args.find:
        print(render_find(infos, args.find))
    elif args.json:
        print(to_json(infos))
    else:
        print(render(infos))


def _natkey(s):
    return [int(t) if t.isdigit() else t.lower()
            for t in re.split(r"(\d+)", s)]


if __name__ == "__main__":
    main()