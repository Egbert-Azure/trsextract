# Changelog

All notable changes to **trsextract** (the Python tool) and **TRS80Extract**
(the SwiftUI wrapper) are recorded here. The Python tool's detailed,
disk-by-disk validation history also lives in the header of `trsextract.py`.

## trsextract.py

### 1.5
- Fix: directory mis-read on builds whose entries do not start in sector 0 of
  the directory track. `decode_directory` concatenated every directory-track
  sector into one blob and strode 32 bytes from offset 0; when GAT/HIT/system
  data sits ahead of the entries (esnd-15 / esnd-25 keep them in sectors
  10-17), the stride misaligned and GAT/HIT bytes passed as phantom entries —
  the "damaged directory pair" in `Disk_Catalog.md`.
- Now each directory sector is parsed independently in 8 fixed 32-byte slots
  (NEWDOS/80 & G-DOS FPDE/FXDE records never span a sector boundary). A
  GAT/HIT/system sector yields no valid entries and is skipped wherever it
  sits, so the leading-sector count is irrelevant.
- The two disks are intact, not damaged: confirmed against Jens Günther's
  cw2dmk dumps (40 trk, 2 sides, 18 sec/trk DD + 5-sector SD track 0) and his
  NEWDOS `DIR` listings. esnd-15 → 63 entries / 63 extracted (HRGPAS volume),
  esnd-25 → 58 / 58 (PASCAL volume); user-file sets match his listings exactly.
- Regression: esnd-23 unchanged (22 entries, self-test PASS); SIDEKICK.JV1
  still → JV1.
- Catalog note: clear the esnd-15 / esnd-25 "damaged directory" flag on the
  next `generate-logs.sh` sweep.
- thanks to [Jens Gunther](https://gitlab.com/jengun) hinting something is wrong

### 1.4
- Fix: a headerless JV1 image was mis-detected as JV3. A 200 KB JV1 disk
  (`SIDEKICK.JV1`, 80×10×256) has no header, so its first ~8.7 KB of program
  bytes parsed as plausible JV3 sector descriptors and the JV3 branch won —
  yielding garbage (`Format: JV3, Tracks: 255, dir track 126`).
- Detection now routes on file extension as a first guess, then validates by
  directory score. DMK has a real header and is trusted when it verifies.
  JV1 and JV3 are headerless and byte-ambiguous, so the extension only sets
  the JV tie-break order; the format actually chosen is whichever yields the
  higher directory score (`_best_dir_score`). A mislabelled JV1/JV3 — or a JV1
  named `.dsk` — self-corrects. Unknown/missing extension falls back to the
  prior content order (DMK header first, then JV tie-break).
- `-v` now prints the per-format directory score, so the detection decision is
  auditable rather than asserted.
- Validated: `SIDEKICK.JV1` → JV1 (dir score 89 vs JV3 23), directory
  auto-located at track 17 (its DDSL) with no `--track` needed, 47/47 files
  extracted; `esnd-23.dmk` still → DMK, self-test PASS, 22/22 files (DMK path
  unchanged); a JV1 renamed `.dsk` → JV1.

### 1.3
- Multi-extent write. A contiguous granule run longer than 32 granules is
  encoded as up to four extent pairs (each extent's granule count is a 5-bit
  field, max 32); the allocation stays a single contiguous run, only its
  directory description is split. Files needing more than four extents are
  rejected (would require FXDE continuation entries).
- Validated at scale on real NEWDOS in sdltrs: `ALIEN/Z80`, 99 673 bytes
  (390 sectors / 78 granules), written from the host as a 3-extent file,
  appears in NEWDOS `DIR` on a real boot — confirming multi-extent encoding
  and GAT marking across the whole run, not just the single-extent case.
- Corrects the 1.2 note: write handles up to four extents, not "one extent of
  ≤ 32 granules".

### 1.2
- Write support. Validated end-to-end against real NEWDOS/80 in sdltrs
  (`LOAD`, `LIST`, `RUN` all succeed on written files).
- `--write-basic SRC.bas [--as NAME/EXT]` tokenises an ASCII BASIC source into
  the exact byte stream NEWDOS BASIC `SAVE` produces and writes it into a copy
  of the image.
- `--write-file SRC [--as NAME/EXT]` writes any host file verbatim (`/CMD`,
  `/TXT`, data, source). EOF encoding validated against `SARGON/CMD`
  (9032 bytes → eof_byte `0x48`, rel-sector 36, exact).
- Multi-lump allocation: a file larger than one lump is placed in a contiguous
  run of free granules and described by a single extent spanning lumps
  (granules are numbered continuously across the disk, as NEWDOS does); GAT
  bits are marked across every spanned lump. `SARGON0/CMD` (8 granules across
  lumps) written to a blank disk loads and runs.
- Built from Klaus Kämpf's `newdos.rb` and the NEWDOS/TRSDOS directory spec:
  the HIT byte lives at offset == the Directory Entry Code `dec = (rrr<<5)+sssss`
  (not a linear slot); entry byte 3 = EOF byte, 20-21 = EOF rel-sector, 16-19 =
  update/access hash, 22+ = extent pairs; `newdos_hashcode()` is an XOR-rotate
  over the 11-byte name+ext; DMK data CRC = CRC-16-CCITT preset `0xFFFF` over
  `A1 A1 A1` + DAM + data (validated against 2880 NEWDOS-written sectors).
- Write scope: append into free space, on a copy. Needs a single contiguous
  free-granule run (no fragmented multi-extent / FXDE yet); single extent of
  ≤ 32 granules; no overwrite / delete / defragment; NEWDOS/80 DSDD geometry.

### 1.1
- Full geometry auto-detection, including G-DOS and single-density disks.
- Generalized the sector model to all tested geometries:
  `start = (lump * GPL + startgran) * 5 + offset`, mapping to physical
  `(track, side, sector)` by detected sides and sectors-per-track.
- `detect_geometry()` observes sides and sectors-per-track from the image and
  solves GPL + offset from the directory marker (`DIR/SYS` for NEWDOS,
  `INHALT/SYS` for G-DOS).
- G-DOS extraction now validated (previously listing-only).
- Validated 34/34 reference files against TRSTools across three geometries
  (G-DOS SS-SD; NEWDOS DS-DD at GPL 2 and 6).

### 1.0
- Geometry-general extraction with automatic GPL detection.
- Unified mapping `start = (lump * GPL + startgran) * 5 + 36`.
- Validated against TRSTools: esnd-23 (GPL 6) 12/12, esnd-05 (GPL 2) 10/10.

### 0.9
- Cross-checked against Klaus Kämpf's `newdos.rb`.
- Correct file-size calculation (EOF sector count with the EOF-byte
  adjustment); fixed FXDE continuation scan.
- esnd-23 extraction 12/12 against TRSTools.
- Documented why type-bit / HIT liveness tests are not used (they wrongly drop
  genuine G-DOS files); listing stays permissive.

### 0.8
- Follow FXDE continuation entries so files with more than four extents read
  fully (e.g. WC/BAS).

### 0.7
- First end-to-end extraction: extent-to-sector resolution, multi-extent
  concatenation, EOF trimming. Validated byte-exact on esnd-23.

### 0.6
- GPLv3 license header. Validated extraction engine driven by a known start
  sector (`--extract-at`); `--self-test`.

### 0.5
- DMK sector-decode fix: locate the MFM data address mark via its `A1 A1 A1`
  sync preamble (previously a stray mark in the IDAM gap could be picked,
  corrupting one sector per track).

### 0.4
- Directory-side handling (directories on side 1, e.g. esnd-01).
- Reject uniform gap-fill phantom entries.
- Hard-disk volume detection and reporting.
- `--version` flag and version history.

### 0.1 – 0.3
- DMK header + IDAM/DAM sector decoder; JV1/JV3 readers.
- 32-byte NEWDOS/80 + G-DOS directory decode.
- All-track directory scan scored by known extensions (no fixed track 17
  assumption); track-count over-read note.

## TRS80Extract (SwiftUI wrapper)

### 1.2
- Redesigned start screen with two side-by-side intents: **Read a disk**
  (drop a `.dmk`/`.dsk` to list and extract) and **Write a file to a disk**
  (choose/drop a target disk, then drop the file to add). The two intents are
  explicit, so a drop is never ambiguous.
- Write flow: dropping the payload opens a naming sheet (pre-filled
  `NAME/EXT`, with a *Tokenize as BASIC* toggle auto-selected for `.bas`
  sources). Writing goes into a COPY (`<target>.out.dsk`); the original is
  never modified. After writing, the app loads the listing from the new image
  and reveals it in Finder.
- Reads/writes via `trsextract.py` 1.3 (`--write-file` / `--write-basic`).
- Fix: the Write button could stay disabled until an unrelated control was
  toggled, because the filename field and the sheet were set in the same
  synchronous pass; sheet presentation is now deferred one runloop tick so the
  field commits first.

### 1.1
- Cosmetic fixes to the initial wrapper (button layout / labels).

### 1.0
- Initial wrapper: drag-and-drop a `.dmk`/`.dsk`, directory table, Extract All
  with folder picker and log viewer. Read and extract only. Shells out to
  `python3 trsextract.py`.

## Catalog tools (generate-logs.sh, catalog-logs.py)

Batch companions to `trsextract.py` for cataloguing a whole disk-image
collection in one pass. Read-only over the images (listing only, no `-o`).

### 1.0
- `generate-logs.sh [IMAGE_DIR] [LOG_DIR]` runs the `trsextract.py` listing
  over every `.dmk`/`.dsk`/`.jv1`/`.jv3` under a directory tree and saves one
  `<disk>.log` per image (full listing plus `-v` diagnostics). Locates
  `trsextract.py` next to itself or in `$PWD`. Flags any disk whose log
  contains `ERROR` (hard-disk volumes, damaged directories) without stopping.
- `catalog-logs.py [LOG_DIR] > Disk_Catalog.md` merges the per-disk logs into a
  single Markdown index: a summary table (format, geometry, file count,
  distinctive-file count, notes) and a per-disk section with the full file
  list. Standard system furniture (BOOT/SYS, DIR/SYS, SYS0–SYS21, common
  utilities) is hidden from the **distinctive files** line so the content that
  identifies each disk stands out. Disks are sorted naturally (esnd-2 before
  esnd-10); error logs surface as flagged rows.
- Output carries a self-documenting header (auto-generated notice, refresh
  command, cross-reference to the hand-maintained `Disk_Inventory.md`).
- First run swept 69 images: 66 listed cleanly, 3 flagged (GAMES.DSK as an HD
  volume; esnd-15 / esnd-25 as a damaged directory pair).