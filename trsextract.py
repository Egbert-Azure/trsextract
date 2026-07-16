#!/usr/bin/env python3
#
# trsextract.py - TRS-80 NEWDOS/80 & G-DOS disk image reader/extractor.
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
"""
trsextract.py - Extract files from TRS-80 NEWDOS/80 and G-DOS disk images.

Supports DMK (primary) and JV1/JV3 (.DSK) floppy formats. Locates the
directory track by scanning all tracks and scoring on known TRS-80 DOS
file extensions, decodes 32-byte directory entries, follows the granule
allocation chain to extract file contents, and optionally de-tokenizes
Level II / Disk BASIC programs.

Hard-disk volume images are NOT handled (directories sit at PDRIVE-defined
cylinders; floppy-track scanning does not apply); they are detected and
reported rather than mis-decoded.

Usage:
    python3 trsextract.py disk.dmk                 # list directory
    python3 trsextract.py disk.dmk -o outdir/      # extract all files
    python3 trsextract.py disk.dmk -o outdir/ --detokenize
    python3 trsextract.py disk.dmk --track N       # force directory track
    python3 trsextract.py disk.dmk -v              # verbose diagnostics
    python3 trsextract.py disk.dmk --write-basic prog.bas --as NAME/BAS -o out.dsk
                                                   # tokenize prog.bas and write
                                                   # it into a COPY of the image
    python3 trsextract.py disk.dmk --write-file foo.cmd --as FOO/CMD -o out.dsk
                                                   # write ANY host file verbatim
                                                   # (multi-lump ok) into a COPY
    python3 trsextract.py --version

This is a from-spec implementation. VERIFY its output against an
authoritative source before trusting it on new disks.

-----------------------------------------------------------------------------
VERSION HISTORY
-----------------------------------------------------------------------------
1.8  (2026-07-16)  Directory continuation: read past a full primary
       directory track onto the next one.
       - NEWDOS/80 addresses a directory slot as dec = (row<<5)+sector_index,
         a 5-bit sector_index -- room for up to 32 entry sectors, more than
         the handful that fit on one track. When a disk's live file count
         needs more than the primary track holds, the extra entries continue
         on the very next (track, side) in physical order (side 0 then side
         1 of a cylinder, then the next cylinder), with no GAT/HIT of their
         own -- the primary track's single HIT sector addresses all of them
         by sector_index. decode_directory now detects this from unexplained
         nonzero HIT bytes on the primary track and follows it
         (_decode_directory_continuation), accepting a continuation-track
         entry only when its computed DEC hashes to the expected HIT byte --
         unlike the primary track, structure alone is not enough signal, so
         unrelated data on an unconnected track cannot be mistaken for
         directory entries.
       - Found investigating a user report: WP/CMD (a live, runnable file on
         esnd-05) was missing from the listing. Its entry, and 10 siblings,
         sit on track 6 side 0, continuing directly from track 5 side 1's 64
         full entries (GAT 8 / HIT 9 / entries 10-17); all 11 HIT-hash at
         exactly the sector_index the DEC scheme predicts.
       - Swept the full 76-image collection: 26 disks gained entries this
         way (2 to 27 files each), including the esnd-23 reference disk
         itself (22 -> 28). self-test (WBEDIT/SAV, an unrelated fixed-sector
         extraction) still PASSES; entry counts only ever grew, never shrank,
         across the sweep. GAMES.DSK (HD volume) unaffected, still refused
         as before.
       - Write path (Newdos80Writer, --undelete) is NOT extended by this --
         they still only see the primary track. A file resurrected or
         written onto a disk with a continuation is unaffected either way,
         but --undelete cannot yet resurrect a dead entry that lives on a
         continuation track.

1.7  (2026-07-05)  Geometry-aware writer; write path no longer DSDD-only.
       - Newdos80Writer now locates directory track/side, GAT, HIT and entry
         sectors structurally (shared _locate_dir_structures with --undelete)
         and takes sides/spt/gpl/offset from detect_geometry. Removes the
         hardcoded DSDD assumptions (track 15 side 0, GAT 6, 2*18 spt) that
         made every write to an SS disk fail with "sector not formatted",
         and would have corrupted DSDD disks with non-standard directory
         placement (esnd-05: dir track 5 SIDE 1, GAT 8 / HIT 9 / entries
         10-17).
       - Same write gate as --undelete: DEC->HIT mapping must confirm
         against >= 2 live entries or the writer aborts.
       - Slot policy: virgin directory slots are preferred over KILLed
         entries, so a write does not destroy dead entries --undelete could
         still resurrect; live and system slots (attr 0x10 / 0x40) are never
         reused. Dead slots are taken only when no virgin slot remains.
       - Entry sectors run contiguously from the first entry sector to the
         end of the track (DEC's sssss counts from there); detection by
         content alone hid sectors holding only never-used slots and
         reported "directory full" with free slots present.
       - VALIDATED SS-SD (esnd-40): AUSWERT/CMD rebuild (5424 bytes, 22
         sectors, 5 granules) written to a copy, listed, extracted
         BYTE-EXACT; the dead FORMFILE entry on the same disk remains
         undeletable afterwards. Undelete regression unchanged (9-byte
         footprint). esnd-05: 64/64 HIT confirmations on the sectors-10-17
         layout; write correctly refused (directory genuinely full, 64/64
         live). DSDD POSITIVE write not re-run in this cycle - rerun the
         blank-disk ALIEN/Z80 validation before trusting DSDD writes.
       - Corrects 1.6 note: the esnd-15/25-style layout (entries 10-17) DOES
         pass the mapping self-check when GAT/HIT precede the entries;
         esnd-05 confirms.

1.6  (2026-07-04)  NEW --undelete NAME/EXT: geometry-aware resurrection of
       KILLed files, developed on esnd-40 (SS 10-spt, dir track 17).
       - A NEWDOS KILL clears the entry's active bit (0x10), removes its HIT
         hash, and frees its granules in the GAT, but leaves the 32-byte entry
         and (until reused) the data sectors intact. --undelete reverses all
         three, writing to a COPY (<image>.out.dsk) as always.
       - GAT and HIT are located structurally (the two sectors before the
         first entry sector), so both SS (GAT 0 / HIT 1 / entries 2+) and
         DSDD (GAT 6 / HIT 7 / entries 8+) layouts resolve without config.
       - SAFETY 1: refuses when the dead file's granules overlap any HIT-live
         file's granules (data partially overwritten; --force overrides with
         a corruption warning).
       - SAFETY 2: before writing, the DEC/HIT slot mapping
         (offset = entry_sector_index + 32*row) must confirm against >= 2
         live entries' hashes, else abort without touching the directory.
         This check exists because a mis-mapped HIT write corrupts OTHER
         files' liveness - the exact failure observed during development.
       - VALIDATED on esnd-40: FORMFILE undeleted with a 9-byte total image
         footprint (attr + HIT + GAT + 3 sector CRCs); the resurrected file
         extracts BYTE-IDENTICAL to an independently preserved copy. Overlap
         refusal verified on DTAST/ASS (granule reused by HRGDUM/ASS).
       - CONTEXT: on esnd-40 the entire DTA-Programmsystem source material
         (FORMFILE, TEST/ASS, WECKER/ASS, CODE/ASS, DTAST/ASS, TESTTEXT/CMD,
         BASIC/CMD) sits in KILLed entries; extraction had recovered it from
         dead slots. NEWDOS DIR hides these correctly - the DIR-vs-trsextract
         listing difference is by design (see the 0.9 liveness note).
       - FIX (found by the 1.6 validation suite): a DMK-content image named
         .dsk -- exactly what --write-file produces as <image>.out.dsk -- was
         claimed by a phantom JV1 parse (dir score 6 > 0) under the 1.4/1.5
         extension routing, so DMK was never tried. The .dsk branch now also
         scores the DMK candidate and the higher directory score wins
         (esnd-40.out.dsk: DMK 57 vs JV1 6 -> DMK). SIDEKICK.JV1 (no DMK
         header) and true JV .dsk images are unaffected.
       - KNOWN: layouts where GAT/HIT do not directly precede the entry
         sectors (cf. the esnd-15/25 builds with entries in sectors 10-17)
         may fail the self-check and be refused - safe, but not yet
         resurrectable. --write-file/--write-basic still assume DSDD
         (hardcoded track 15 / GAT 6); on SS disks they fail with "sector not
         formatted" AFTER creating the unmodified .out.dsk copy - fix planned.

1.5  (2026-06-30)  FIX: directory mis-read on builds with leading non-entry
       sectors (esnd-15 / esnd-25, the "damaged directory pair").
       - BUG: decode_directory concatenated ALL directory-track sectors into
         one blob and strode 32 bytes from offset 0. When the entries do not
         begin in sector 0 -- e.g. esnd-15/25 keep them in sectors 10-17, with
         GAT/HIT/system data ahead -- the stride misaligned and GAT/HIT bytes
         passed as phantom entries, so the disk looked damaged. Both disks are
         in fact intact (confirmed against Jens Guenther's cw2dmk dumps and
         NEWDOS DIR listings).
       - FIX: parse each directory sector independently in 8 fixed 32-byte
         slots (NEWDOS/80 & G-DOS FPDE/FXDE records never span a sector
         boundary). A GAT/HIT/system sector simply yields no valid entries and
         is skipped wherever it sits, so the leading-sector count no longer
         matters.
       - VALIDATED: esnd-15 -> 63 entries / 63 files extracted; esnd-25 -> 58
         / 58; user-file sets match Jens's HRGPAS and PASCAL listings exactly
         (RESCUE, PASCAL, CODEGEN ... ZEISATZ1; MAXWELL/SRC, CREF80, CRAM2).
         esnd-23 regression unchanged (22 entries, self-test PASS).
       - Note for the catalog: esnd-15 and esnd-25 are NOT a damaged pair; the
         Disk_Catalog.md flag should be cleared on the next sweep.

1.4  (2026-06-30)  FIX: JV1 mis-detected as JV3; extension-routed detection.
       - BUG: a headerless JV1 image (e.g. SIDEKICK.JV1, 200 KB = 80x10x256)
         was claimed by the JV3 parser, whose first ~8.7 KB of program bytes
         parsed as plausible sector descriptors. Result was garbage:
         "Format: JV3, Tracks: 255, dir track 126".
       - FIX: load_image now routes on file extension as a first guess, then
         VALIDATES by directory score. DMK has a real header and is trusted
         when its header verifies. JV1 and JV3 are headerless and byte-
         ambiguous, so the extension only sets the JV tie-break order; the
         actual choice is whichever format yields the higher directory score
         (_best_dir_score). A mislabelled JV1/JV3 (or .dsk-named JV1) is thus
         self-corrected. Unknown/missing extension falls back to DMK-header-
         first, then JV tie-break (old content-order behaviour).
       - VALIDATED: SIDEKICK.JV1 -> JV1 (dir score 89 vs JV3 23), directory
         auto-located at track 17 (DDSL) with NO --track needed; 47/47 files
         extracted. Mislabelled MISLABELED.dsk (JV1 content) also -> JV1.
       - NOTE: -v now prints the per-format directory score so the detection
         decision is auditable rather than asserted.

1.3  (2026-06-28)  Multi-EXTENT write, validated at scale on real NEWDOS.
       - A contiguous granule run longer than 32 granules is now encoded as up
         to four extent pairs (each extent's granule count is a 5-bit field,
         max 32). The allocation is still a single contiguous run; only its
         description in the directory entry is split. Files needing more than
         four extents are rejected (would require FXDE continuation entries).
       - Validated end-to-end in sdltrs: ALIEN/Z80, 99673 bytes (390 sectors /
         78 granules), written from the host as a 3-extent file, appears in
         NEWDOS DIR on a real boot. Confirms multi-extent encoding + GAT
         marking across the whole run, not just the single-extent case.
       - Corrects the 1.2 note: write handles up to four extents, not "one
         extent of <= 32 granules".

1.2  (2026-06-28)  WRITE SUPPORT (NEWDOS/80 DSDD), validated against real DOS.
       - NEW --write-basic SRC.bas [--as NAME/EXT]: tokenizes an ASCII BASIC
         source and writes it into a COPY of a NEWDOS/80 DSDD image. Verified
         end-to-end in sdltrs - the written file LOADs, LISTs and RUNs.
       - NEW --write-file SRC [--as NAME/EXT]: writes ANY host file verbatim
         (/CMD, /TXT, data, source). EOF encoding validated against SARGON/CMD
         (9032 bytes -> eof_byte 0x48, rel-sector 36, exact).
       - MULTI-LUMP allocation: files larger than one lump are placed in a
         contiguous run of free granules and described by a single extent that
         spans lumps (granules are numbered continuously across the disk, as
         NEWDOS does). GAT bits are marked across every spanned lump. Validated
         end-to-end: SARGON0/CMD (9032 bytes, 8 granules across lumps) written
         to a blank disk LOADs and RUNs in sdltrs. v1 still requires a single
         CONTIGUOUS free run (no fragmented multi-extent / FXDE yet) and one
         extent of <= 32 granules.
       - Built from Klaus Kaempf's newdos.rb (authoritative) + NEWDOS/TRSDOS
         directory spec. Key facts:
           * Directory Entry Code: dec = (rrr<<5)+sssss; the HIT byte sits at
             offset == DEC (not a linear slot index).
           * Entry: byte3=EOF-byte, 20-21=EOF rel-sector, 16-19=upd/acc hash,
             22+=extent pairs (lump, (startgran<<5)|(ngran-1)), 0xFF ends.
           * newdos_hashcode() (XOR-rotate over 11-byte name+ext) matches DOS.
           * DMK data CRC = CRC-16-CCITT preset 0xFFFF over A1 A1 A1 + DAM +
             data; validated against 2880 NEWDOS-written sectors.
       - v1 scope: append into free space, on a copy, single-lump files
         (<= 30 sectors). No overwrite / delete / defragment / multi-lump.
       - Read/list/extract unchanged (no regression).

1.1  (2026-06-27)  FULL geometry auto-detection incl. G-DOS / single-density.
       - Generalized the sector model to all tested geometries. The flat
         granule model is:
             flat_sector = (lump * gpl + startgran) * 5
             abs_sector  = flat_sector + offset
             SS: track = abs // spt;  DS: cyl = abs // (2*spt),
                 side = (abs % (2*spt)) // spt
       - NEW detect_geometry(): observes sides and sectors-per-track (spt)
         directly from the image, and solves gpl + offset from the directory
         marker (DIR/SYS for NEWDOS, INHALT/SYS for G-DOS). Single-density
         disks (10 sectors/track) are now handled - the prior code assumed 18.
       - G-DOS EXTRACTION now validated (was previously listing-only).
       - VALIDATED 34/34 reference files across THREE geometries:
             esnd-02  G-DOS SS-SD  (sides=1 spt=10 gpl=2 offset=0):  5/5
             esnd-05  NEWDOS DS-DD (sides=2 spt=18 gpl=2 offset=36): 10/10
             esnd-06  NEWDOS DS-DD (sides=2 spt=18 gpl=2 offset=36):  7/7
             esnd-23  NEWDOS DS-DD (sides=2 spt=18 gpl=6 offset=36): 12/12
         Spanning BASIC, tokenised, ASM, JCL, ILF, DAT, DRW, HRG, CMD, REL,
         SAV, DUM, TXT file types; many BYTE-EXACT, rest CR-EXACT.
       - All geometry parameters are now auto-detected; no manual config.

1.0  (2026-06-27)  GEOMETRY-GENERAL EXTRACTION. Validated on two geometries.
       - Unified the start-sector mapping across disk geometries:
             start_sector = (lump * GPL + startgran) * 5 + 36
         where startgran = (extent_byte >> 5), granule = 5 sectors, and GPL
         (granules per lump) is the only per-geometry variable. The earlier
         esnd-23-only "30*lump+36" was this same formula with GPL=6 folded in.
       - NEW: detect_gpl() recovers GPL automatically from the DIR/SYS entry
         (whose data is the directory itself, at a known sector), so no manual
         geometry selection is needed. esnd-23 -> GPL 6; esnd-04/05 -> GPL 2.
       - VALIDATED byte/CR-exact against TRSTools reference extractions on TWO
         geometries:
             esnd-23 (DS, GPL=6): 12/12 reference files
             esnd-05 (GPL=2):     10/10 reference files (HELP/CMD, HRG/CMD,
               HX1/CMD, KBDGER/CMD, LMOFFSET/CMD, MENUE1/CMD, HPRX/DAT,
               LINEDEMO/BAS, SCRIPSIT/SP, SCRIPSIT/CMD - many BYTE-EXACT)
             esnd-04 (GPL=2):     confirmed file (ZAPDUP2/JCL) extracts OK
       - This resolves the prior "extraction trustworthy only on esnd-23"
         limitation. Extraction now works across the tested NEWDOS geometries
         with automatic GPL detection.
       NOTE: the +36 offset and 5-sector granule are constant across all disks
         tested; should a disk with a different reserved-area layout appear,
         detect_gpl's DIR/SYS solve would still adapt GPL but the +36 may need
         confirming. G-DOS extraction not yet validated against refs.

0.9  (2026-06-27)  Klaus Kaempf's newdos.rb cross-check: size fix, FXDE,
                   and important negative results.
       - Reference: Klaus Kaempf's newdos.rb (a working NEWDOS/G-DOS/TRSDOS
         reader) and a Model III TRSDOS directory-format note. These confirmed
         the extent decode (startgran = (b>>5), grancount = (b&0x1f)+1) and
         supplied the correct file-size calculation.
       - FIX: file size now uses the spec formula - bytes 20-21 are the EOF
         relative sector count; if the EOF byte (byte 3) is non-zero, subtract
         one sector; length = eof_sector*256 + eof_byte. This corrected the
         W/BAS trailing-length edge.
       - FIX: FXDE continuation scan now covers byte 30 (the 0xFE link marker
         previously fell outside the loop bound).
       - RESULT: esnd-23 extraction now validates 12/12 against TRSTools refs
         (5 BYTE-EXACT binary/tokenised, 7 CR-EXACT ASCII).
       - WBEDIT/COM mystery resolved: that directory slot is a DELETED entry
         (type bit 4 clear, absent from the HIT). Its extent/length fields are
         stale; it is not a live file. Same for the 'PLANTS' slot. (The live
         demo file is 'PLANT', singular.)
       - NEGATIVE RESULTS (kept permissive on purpose): neither the type-byte
         bit-4 flag NOR HIT membership is a reliable cross-disk liveness test.
         Both correctly drop the esnd-23 deleted entries but WRONGLY drop many
         genuine G-DOS files (BASIC/CMD type 0x00; SYS*/SYS type 0x4F; G-DOS
         HIT layout/hash differs). So the lister still shows all structurally
         valid entries rather than risk hiding real files. A couple of stale
         entries on a NEWDOS disk are tolerated as the lesser harm.
       KNOWN: cross-GEOMETRY extraction is NOT yet correct. The start-sector
         mapping (start = 30*lump + 36, two-sided ordering) is an empirical fit
         to esnd-23 ALONE. It fails not only on single-sided disks (esnd-03)
         but also on other double-sided disks (esnd-04 extracts all-zero
         sectors) because the lump->sector base depends on each disk's actual
         directory placement / reserved area, which vary. The correct fix is to
         rebuild the resolver on Klaus's PHYSICAL model:
             sector = (lump * gpl + startgran) * secpergranule  (+ image offset)
         selecting gpl / secpergranule / sides / offset by disk geometry from
         his FORMATS table, with correct DMK logical-sector ordering. EXTRACTION
         is currently TRUSTWORTHY ONLY on esnd-23 (validated 12/12 vs TRSTools);
         do not trust extraction on other disks until the geometry-general
         resolver lands. Directory LISTING works across all geometries.

0.8  (2026-06-27)  FXDE continuation following; 7/8 TRSTools refs validate.
       - FIX bug #1: files with >4 extents now read fully. When an FPDE's
         byte 30 == 0xFE, byte 31 links to an FXDE (extended directory entry,
         attr 0x90) at index (byte31 >> 5) holding further extent pairs; the
         chain is now followed. WC/BAS (5 extents via FXDE) is now CR-EXACT
         against TRSTools, up from truncated.
       - Validated against TRSTools esnd-23 extraction:
             WBEDIT/REL, WBEDIT/SAV, WBEDIT/TXT   BYTE-EXACT
             W/BAS, WBEDIT/BAS, WC/ASC, WC/BAS     CR-EXACT
             WBEDIT/COM                            still DIFF (bug #2 below)
       REMAINING BUG #2: WBEDIT/COM (a compiled /CMD-class executable) is
         32429 bytes (~127 sectors) but its single extent encodes only ~55
         sectors and mismatches from byte 0. CMD/COM load-module files appear
         to use a different size/extent scheme than data/BASIC files - needs
         dedicated study. All non-executable files extract correctly.

0.7  (2026-06-27)  EXTRACTION SOLVED (esnd-23 geometry) and validated.
       - Cracked the directory-extent -> sector mapping:
             start_sector = 30*lump + 36 + (second_byte >> 5) * 5
         with granule = 5 sectors and granule-count = (second_byte & 0x1F)+1.
         Derived from byte-exact anchors at two different lumps (9 and 15).
       - NEW: extract_file() resolves and concatenates all extent runs;
         -o OUTDIR now extracts every file in the directory.
       - VALIDATED against an authoritative TRSTools extraction of esnd-23:
             WBEDIT/REL  BYTE-EXACT
             WBEDIT/SAV  BYTE-EXACT
             WBEDIT/TXT  BYTE-EXACT
             W/BAS       CR-EXACT
             WBEDIT/BAS  CR-EXACT
             WC/ASC      CR-EXACT
             DRUCK/BAS, TESTEN  CR-EXACT
         (CR-exact = identical once the TRSTools/editor CRLF line endings are
         normalised to the disk's native bare-CR.)
       KNOWN BUGS (TRSTools-confirmed, bounded, for next session):
         1. >4-extent files read short. An FPDE holds 4 extent pairs (bytes
            22-29); byte 30 == 0xFE links to an FXDE (extended dir entry) with
            more pairs. The FXDE link is not yet followed, so heavily
            fragmented files (e.g. WC/BAS, 5+ extents) are truncated.
         2. WBEDIT/COM: ref is 127 sectors but its single extent encodes only
            ~11 granules (55 sectors), and it mismatches from byte 0. CMD/COM
            executables may use a different size/extent encoding - needs study.
       GEOMETRY: constants (30, 36, 5) are calibrated on esnd-23 (DS 80-track)
         and must be confirmed for 40-track / single-sided disks.

0.6  (2026-06-27)  GPLv3 license; validated extraction ENGINE (start-driven).
       - LICENSE: now GPLv3 (see header).
       - NEW: read_file_from_start() - the byte-exact extraction engine
         (two-sided contiguous read + EOF trim), exposed via --extract-at
         START,NSEC,EOF for extracting any file whose start sector is known.
       - NEW: --self-test runs the WBEDIT/SAV regression on esnd-23.
       - HONEST SCOPE: automatic start-sector resolution from directory
         extent pairs is NOT yet implemented. Investigation this session
         proved the extent->sector mapping is not a simple formula and that
         content-scanning yields false anchors (a duplicate copy of WC/ASC
         text exists elsewhere on the disk). Correct resolution requires GAT
         decoding. The GAT was located (esnd-23: track 15 side 0, sector 6;
         allocation bytes 0x00-0x3F, lockout region follows) - decoding it is
         the next step. Until then, --extract-at needs an explicit start.

0.5  (2026-06-27)  DMK sector-decode fix; extraction mechanics proven.
       - FIX: _find_data DAM search. In MFM (double density) the data address
         mark is now located via its 0xA1 0xA1 0xA1 sync preamble instead of a
         bare F8-FB scan. Previously a stray F8-FB byte inside the IDAM CRC or
         gap could be mistaken for the DAM, returning gap-fill (0x4E) for one
         sector per track. This corrupted ~1 sector/track on DD disks.
         Result: WBEDIT/SAV now extracts BYTE-EXACT (15099/15099) vs an
         untouched reference, up from 58/59 sectors.
       - Extraction MECHANICS validated end to end (two-sided contiguous read +
         EOF trim) once a file's start sector is known. The remaining gap is
         resolving FPDE extent pairs to start sectors via the GAT (see TODO).

0.4  (2026-06-27)  Directory LISTING validated; extraction still WIP.
       - FIX: directory-side handling. find_directory_track now returns the
         winning (track, side); decoding previously always read side 0, which
         produced garbage on disks whose directory is on side 1 (e.g. esnd-01).
       - FIX: reject uniform gap-fill phantom entries (0x4E='N' runs) that
         passed the charset validator (seen as 'NNNNNNNN/NNN').
       - NEW: hard-disk volume detection. Images larger than a max floppy
         (~720 KB) with no scannable directory now report an actionable
         HD-volume message instead of a generic failure.
       - NEW: --version flag and this changelog.
       Validated (directory listing) against six real disks:
         esnd-23 NEWDOS/80 DS 80-trk (dir side 0)
         esnd-01 NEWDOS/80 DS 40-trk (dir side 1)   <- side fix
         esnd-02 G-DOS 2.2 SS 40-trk
         esnd-17 G-DOS 2.2 SS 40-trk
         GAMES.DSK HD volume  -> correctly identified & declined
         sargon.dsk           -> lists as normal 80-trk floppy (4 entries)

0.3  Strict directory-entry validation; track-count over-read note
       (35/40/80 + 1 = imaging over-read, flagged not silently corrected).

0.2  All-track directory scan scored by known extensions (no fixed track 17
       assumption); G-DOS INHALT/SYS + GDOS/SYS supported via generic scan.

0.1  DMK header + IDAM/DAM sector decoder; JV1/JV3 readers; 32-byte
       NEWDOS/80 + G-DOS directory decode.

KNOWN ISSUES / TODO
       - EXTRACTION: mechanics proven (byte-exact on WBEDIT/SAV). Remaining
         work is resolving FPDE extent pairs (lump, code) to a start sector.
         This is NOT a simple linear formula - extent bytes are granule
         references that must resolve through the GAT (Granule Allocation
         Table, the first sector of the directory). NEXT STEP: parse the GAT
         per the NEWDOS/80 v2 spec (lumps = GAT bytes; GPL granules/lump;
         SPG sectors/granule; this disk: GPL=2, SPG=9, 2-sided) and map each
         extent's granule run to absolute sectors, then read contiguously
         using the validated two-sided + EOF-trim mechanics.
       - HD volumes (GAMES.DSK) need PDRIVE geometry to read; only detected.
       - Raw JV-format .DSK files and damaged disks (esnd-13/13a/13b, esnd-20)
         not yet validated.
-----------------------------------------------------------------------------
"""

__version__ = "1.8"

import argparse
import os
import sys
import struct

KNOWN_EXTS = {b"SYS", b"CMD", b"BAS", b"ASM", b"DVR", b"HLP", b"TXT",
              b"JCL", b"DAT", b"DCT", b"OBJ", b"REL", b"FLT", b"DUM"}

GDOS_MARKERS = {b"INHALT/SYS", b"GDOS/SYS"}


# ---------------------------------------------------------------------------
# Sector-access abstraction. A "geometry" yields sector bytes addressed by
# (track, side, sector). DMK and JV1/JV3 each provide their own reader.
# ---------------------------------------------------------------------------

class DiskImage:
    """Base: subclasses populate self.sectors as {(track, side, sec): bytes}."""
    def __init__(self):
        self.sectors = {}
        self.ntracks = 0
        self.sides = 1
        self.sector_size = 256
        self.fmt = "?"

    def get(self, track, side, sector):
        return self.sectors.get((track, side, sector))

    def track_sectors(self, track, side=0):
        return {s: d for (t, sd, s), d in self.sectors.items()
                if t == track and sd == side}


# ---------------------------------------------------------------------------
# DMK parser
# ---------------------------------------------------------------------------

class DMKImage(DiskImage):
    def __init__(self, data, verbose=False):
        super().__init__()
        self.fmt = "DMK"
        self.verbose = verbose
        self._parse(data)

    def _parse(self, data):
        if len(data) < 16:
            raise ValueError("file too short to be a DMK image")
        write_protect = data[0]
        ntracks = data[1]
        track_len = struct.unpack_from("<H", data, 2)[0]
        flags = data[4]
        single_sided = bool(flags & 0x10)
        self.sides = 1 if single_sided else 2
        self.ntracks = ntracks

        if self.verbose:
            print(f"[dmk] tracks={ntracks} track_len={track_len} "
                  f"sides={self.sides} wp={write_protect:#x} flags={flags:#x}",
                  file=sys.stderr)

        HEADER = 16
        for track in range(ntracks):
            for side in range(self.sides):
                base = HEADER + (track * self.sides + side) * track_len
                if base + track_len > len(data):
                    continue
                tdata = data[base:base + track_len]
                self._parse_track(track, side, tdata)

    def _parse_track(self, track, side, tdata):
        # First 0x80 bytes: up to 64 IDAM pointers (little-endian 16-bit).
        # High bit of pointer = double-density (MFM); low 14 bits = offset
        # into the track data of the IDAM (0xFE) byte.
        idam_table = tdata[:0x80]
        for i in range(0, 0x80, 2):
            raw = struct.unpack_from("<H", idam_table, i)[0]
            if raw == 0:
                continue
            offset = raw & 0x3FFF
            double_density = bool(raw & 0x8000)
            if offset >= len(tdata) or tdata[offset] != 0xFE:
                continue
            # IDAM: FE, track, side, sector, sizecode, CRC(2)
            if offset + 5 > len(tdata):
                continue
            t = tdata[offset + 1]
            h = tdata[offset + 2]
            sec = tdata[offset + 3]
            sizecode = tdata[offset + 4]
            size = 128 << (sizecode & 0x03)
            data_bytes = self._find_data(tdata, offset + 5, double_density)
            if data_bytes is None:
                continue
            self.sectors[(t, h, sec)] = data_bytes[:size]
            self.sector_size = size

    def _find_data(self, tdata, start, double_density):
        # After the IDAM (FE,t,h,s,szc) come 2 CRC bytes, a gap, then the DAM
        # (data address mark, F8-FB). In MFM (double density) the DAM is
        # preceded by three 0xA1 sync bytes; requiring that preamble avoids
        # latching onto a stray F8-FB byte inside the IDAM's CRC or the gap
        # (which corrupted one sector per track and returned gap-fill 0x4E).
        # In FM (single density) there is no A1 preamble, so fall back to a
        # bare DAM scan but skip the first few bytes (the IDAM CRC).
        window = 80 if double_density else 45
        end = min(start + window, len(tdata))
        if double_density:
            # look for A1 A1 A1 <DAM>
            for p in range(start, end - 3):
                if (tdata[p] == 0xA1 and tdata[p + 1] == 0xA1
                        and tdata[p + 2] == 0xA1
                        and tdata[p + 3] in (0xF8, 0xF9, 0xFA, 0xFB)):
                    return tdata[p + 4:]
            # some images store only one or two A1 sync bytes; try A1 <DAM>
            for p in range(start, end - 1):
                if tdata[p] == 0xA1 and tdata[p + 1] in (0xF8, 0xF9, 0xFA, 0xFB):
                    return tdata[p + 2:]
            return None
        # FM: skip the 2 CRC bytes after the IDAM, then scan for the DAM.
        for p in range(start + 2, end):
            if tdata[p] in (0xF8, 0xF9, 0xFA, 0xFB):
                return tdata[p + 1:]
        return None


# ---------------------------------------------------------------------------
# JV1 / JV3 parser (.DSK)
# ---------------------------------------------------------------------------

class JV1Image(DiskImage):
    """JV1: pure 256-byte sectors, 10 sectors/track, single density, SS."""
    def __init__(self, data, verbose=False):
        super().__init__()
        self.fmt = "JV1"
        SEC = 256
        SPT = 10
        total = len(data) // SEC
        self.ntracks = total // SPT
        for idx in range(total):
            track = idx // SPT
            sec = idx % SPT
            self.sectors[(track, 0, sec)] = data[idx * SEC:(idx + 1) * SEC]


class JV3Image(DiskImage):
    """JV3: 2901-byte header of sector descriptors, then sector data."""
    HEADER_ENTRIES = 2901
    FREE = 0xFF

    def __init__(self, data, verbose=False):
        super().__init__()
        self.fmt = "JV3"
        self.verbose = verbose
        self._parse(data)

    def _parse(self, data):
        pos = 0
        offset = 3 * self.HEADER_ENTRIES + 1  # header size
        for i in range(self.HEADER_ENTRIES):
            track = data[i * 3]
            sec = data[i * 3 + 1]
            flags = data[i * 3 + 2]
            if track == self.FREE:
                continue
            sizecode = (flags & 0x03)
            size = (256, 128, 1024, 512)[sizecode]
            side = 1 if (flags & 0x10) else 0
            if offset + size > len(data):
                break
            self.sectors[(track, side, sec)] = data[offset:offset + size]
            self.sides = max(self.sides, side + 1)
            self.ntracks = max(self.ntracks, track + 1)
            offset += size


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------

def _best_dir_score(img):
    """Best directory-track score this parse achieves, used to judge whether a
    candidate format actually yields a decodable NEWDOS/80 / G-DOS directory.
    JV1 and JV3 have no header to distinguish them, so the only reliable signal
    of a correct parse is that *some* track decodes as a clean directory."""
    if img is None or not img.sectors:
        return -1
    best = 0
    for track in range(img.ntracks):
        for side in range(img.sides):
            s, _ = score_track_as_directory(img, track, side)
            if s > best:
                best = s
    return best


def _build_jv(data, verbose):
    """Construct both JV candidates and return the one whose best directory
    track scores higher. They are byte-ambiguous (no header), so we let the
    directory validator break the tie rather than trusting a size heuristic."""
    cands = []
    try:
        cands.append(JV3Image(data, verbose))
    except Exception:
        pass
    try:
        cands.append(JV1Image(data, verbose))
    except Exception:
        pass
    if not cands:
        return None
    scored = [(_best_dir_score(c), c) for c in cands]
    scored.sort(key=lambda t: t[0], reverse=True)
    if verbose:
        for sc, c in scored:
            print(f"[detect] {c.fmt}: best dir score {sc}", file=sys.stderr)
    return scored[0][1]


def load_image(path, verbose=False):
    """Pick a parser by file extension as a first guess, then validate by
    decoding a directory; on a weak result, retry the alternate format and keep
    whichever yields the better directory. DMK is header-verified and so is
    trusted directly; JV1 and JV3 are headerless and byte-ambiguous, so the
    extension only selects which to try first -- a mislabelled JV1/JV3 is
    corrected by the directory-score comparison."""
    import os
    with open(path, "rb") as f:
        data = f.read()
    ext = os.path.splitext(path)[1].lower()

    def try_dmk():
        if len(data) < 16:
            return None
        b0, b1 = data[0], data[1]
        track_len = struct.unpack_from("<H", data, 2)[0]
        if not (b0 in (0x00, 0xFF) and 30 <= b1 <= 96
                and 0x80 < track_len <= 0x3FFF):
            return None
        try:
            img = DMKImage(data, verbose)
            return img if img.sectors else None
        except Exception as e:
            if verbose:
                print(f"[detect] DMK parse failed: {e}", file=sys.stderr)
            return None

    # Extension routing. DMK has a real header, so when the name says DMK we
    # verify and trust it. .JV1/.DSK only steer the JV tie-break order; the
    # directory validator has final say either way.
    if ext == ".dmk":
        img = try_dmk()
        if img is not None:
            return img
        if verbose:
            print("[detect] .dmk header invalid; falling back to JV", file=sys.stderr)
        return _build_jv(data, verbose) or JV1Image(data, verbose)

    if ext in (".jv1", ".dsk", ".jv3"):
        img = _build_jv(data, verbose)
        jv_score = _best_dir_score(img)
        # A DMK renamed/copied to .dsk (e.g. the tool's own <image>.out.dsk
        # copies of DMK sources) must not be claimed by a phantom JV parse:
        # JV1 over DMK bytes can yield a small nonzero directory score. So the
        # DMK header path is evaluated too, and the HIGHER directory score
        # wins -- same final-arbiter principle as the JV tie-break itself.
        dmk = try_dmk()
        if dmk is not None:
            dmk_score = _best_dir_score(dmk)
            if verbose:
                print(f"[detect] DMK: best dir score {dmk_score}",
                      file=sys.stderr)
            if dmk_score > jv_score:
                return dmk
        if img is not None and jv_score > 0:
            return img
        return dmk or img or JV1Image(data, verbose)

    # Unknown / missing extension: fall back to content order -- DMK header
    # first (self-validating), then JV tie-break.
    img = try_dmk()
    if img is not None:
        return img
    return _build_jv(data, verbose) or JV1Image(data, verbose)


# ---------------------------------------------------------------------------
# Directory location and decoding (NEWDOS/80 + G-DOS)
# ---------------------------------------------------------------------------

ENTRY_SIZE = 32


def _valid_name_field(field):
    """A NEWDOS/80 filename/extension field: A-Z or 0-9, optionally space-
    padded on the right. No lowercase, no punctuation, no high-bit bytes,
    no embedded spaces. Must start with a letter and be non-empty."""
    stripped = field.rstrip(b" ")
    if not stripped:
        return False
    # right-padding only: nothing after the first trailing space
    if b" " in stripped:
        return False
    if not (0x41 <= stripped[0] <= 0x5A):  # must start A-Z
        return False
    for c in stripped:
        if not (0x41 <= c <= 0x5A or 0x30 <= c <= 0x39):
            return False
    return True


def _valid_entry(ent):
    """True for a structurally-valid NEWDOS/80 / G-DOS FPDE.

    NOTE on the type byte: bit 4 (0x10) is NOT a reliable universal
    "live file" flag across these disks. On esnd-23 (NEWDOS/80) the deleted
    slots happened to have bit 4 clear, but on the G-DOS disks many genuine
    files (BASIC/CMD type 0x00, SYS*/SYS type 0x4F, etc.) also have bit 4
    clear. So this function validates structure only; liveness is better
    determined via the HIT (see decode_directory, which drops entries absent
    from the HIT when a usable HIT is present). FXDE continuation entries
    (type & 0x90 == 0x90) are excluded as they are not files.
    """
    attr = ent[0]
    if attr == 0xFF:
        return False
    if (attr & 0x90) == 0x90:        # FXDE extended entry, not a file
        return False
    name = ent[5:13]
    ext = ent[13:16]
    if not _valid_name_field(name):
        return False
    # Reject phantom entries that are uniform gap-fill (e.g. 0x4E='N' repeated).
    nstripped = name.rstrip(b" ")
    if len(set(nstripped)) == 1 and len(nstripped) >= 6:
        return False
    es = ext.rstrip(b" ")
    if es and not _valid_name_field(ext):
        return False
    return True


def score_track_as_directory(img, track, side=0):
    """Score a track by how many CLEAN directory entries it yields. The real
    directory track maximises this; tracks holding file data score ~0 because
    tokenised BASIC text fails the strict entry validator."""
    secs = img.track_sectors(track, side)
    if not secs:
        return 0, []
    blob = b"".join(secs[s] for s in sorted(secs))
    score = 0
    names = []
    for off in range(0, len(blob) - ENTRY_SIZE, ENTRY_SIZE):
        ent = blob[off:off + ENTRY_SIZE]
        if not _valid_entry(ent):
            continue
        # weight known extensions higher so a directory track wins decisively
        ext = ent[13:16].rstrip(b" ")
        score += 2 if (ext in KNOWN_EXTS or not ext) else 1
        names.append((ent[5:13].rstrip(b" "), ext))
    return score, names


def find_directory_track(img, forced=None, verbose=False):
    if forced is not None:
        # forced track: still pick the better-scoring side
        best_side, best_score = 0, -1
        for side in range(img.sides):
            score, _ = score_track_as_directory(img, forced, side)
            if score > best_score:
                best_score, best_side = score, side
        return forced, best_side
    best_track, best_side, best_score = None, 0, 0
    for track in range(img.ntracks):
        for side in range(img.sides):
            score, _ = score_track_as_directory(img, track, side)
            if verbose and score:
                print(f"[dir] track {track} side {side}: score {score}",
                      file=sys.stderr)
            if score > best_score:
                best_score, best_track, best_side = score, track, side
    return best_track, best_side


class DirEntry:
    def __init__(self, name, ext, attr, eof_offset, lrl, extents, raw):
        self.name = name
        self.ext = ext
        self.attr = attr
        self.eof_offset = eof_offset
        self.lrl = lrl
        self.extents = extents  # list of (start_granule, ngranules) approx
        self.raw = raw

    @property
    def filename(self):
        n = self.name.decode("ascii", "replace").rstrip()
        e = self.ext.decode("ascii", "replace").rstrip()
        return f"{n}/{e}" if e else n


def _make_dir_entry(ent):
    # NEWDOS/80 dir entry layout (FPDE, approx):
    #   byte0  attributes
    #   byte2  EOF byte offset in last sector
    #   byte3  logical record length
    #   bytes5-12  filename (8)
    #   bytes13-15 extension (3)
    #   bytes22+   extent fields (granule allocation pairs)
    name = ent[5:13]
    ext = ent[13:16]
    eof_off = ent[2]
    lrl = ent[3]
    extents = _parse_extents(ent)
    return DirEntry(name, ext, attr=ent[0], eof_offset=eof_off,
                    lrl=lrl, extents=extents, raw=ent)


def _next_track_side(img, track, side):
    """Physical (track, side) that immediately follows in standard TRS-80
    controller order: side 0 then side 1 of a cylinder before stepping to
    the next cylinder. Matches DMK's own track/side layout formula and the
    order NEWDOS/80 continues a directory in (see
    _decode_directory_continuation)."""
    if side + 1 < img.sides:
        return track, side + 1
    return track + 1, 0


def _decode_directory_continuation(img, track, side, verbose=False):
    """Find and decode directory entries that overflow onto a continuation
    track, beyond the primary directory track (track, side).

    NEWDOS/80 addresses a directory slot as dec = (row << 5) + sector_index,
    a 5-bit sector_index field -- room for up to 32 entry sectors, more than
    the handful that fit on one track (esnd-05: 8, sectors 10-17). When a
    disk's live file count needs more than the primary track holds, the
    extra entry sectors continue on the next (track, side) in physical
    order (_next_track_side), with no extra GAT/HIT of their own -- the
    single HIT sector on the primary track addresses all of them by
    sector_index. Confirmed on esnd-05: 11 files (WP/CMD and 10 others) sit
    on track 6 side 0, continuing directly from track 5 side 1's 64 (GAT 8 /
    HIT 9 / entries 10-17); every one of the 11 HIT-hashes at exactly the
    sector_index the DEC scheme predicts.

    Detected from the primary track's own HIT bytes: any nonzero HIT byte at
    a sector_index beyond what the primary track provides means a live
    file's entry lives on a continuation track. Unlike the primary track's
    scan (structure alone), a continuation track has no independent
    structural signal, so its entries are trusted only when their computed
    DEC hashes to the expected HIT byte -- otherwise unrelated data on an
    unconnected track could be mistaken for directory entries.
    """
    secs = img.track_sectors(track, side)
    ids = sorted(secs)

    def is_entry_sector(d):
        return any(_valid_entry(d[o:o + 32]) or d[o] == 0x94
                   for o in range(0, 256, 32))
    detected = [s for s in ids if is_entry_sector(secs[s])]
    if not detected:
        return []
    first_ent = detected[0]
    idx = ids.index(first_ent)
    if idx < 2:
        return []  # no room for GAT+HIT ahead of the entries
    hit_id = ids[idx - 1]
    si_count = len([s for s in ids if s >= first_ent])
    if si_count >= 32:
        return []  # already at the DEC field's maximum
    hit = secs[hit_id]

    needs_more = any(hit[si + 32 * row] != 0
                     for si in range(si_count, 32) for row in range(8))
    if not needs_more:
        return []

    entries = []
    cur_track, cur_side = track, side
    while si_count < 32:
        cur_track, cur_side = _next_track_side(img, cur_track, cur_side)
        if cur_track >= img.ntracks:
            break
        csecs = img.track_sectors(cur_track, cur_side)
        cids = sorted(csecs)
        if not cids:
            break
        found_here = 0
        for local_si, sec_id in enumerate(cids):
            si = si_count + local_si
            if si >= 32:
                break
            d = csecs[sec_id]
            for row in range(8):
                ent = d[row * 32:(row + 1) * 32]
                if not _valid_entry(ent):
                    continue
                dec = si + 32 * row
                if dec >= len(hit) or hit[dec] == 0:
                    continue
                if hit[dec] != newdos_hashcode(ent[5:13], ent[13:16]):
                    continue
                entries.append(_make_dir_entry(ent))
                found_here += 1
        if verbose:
            print(f"[dir] continuation: track {cur_track} side {cur_side} "
                  f"-> {found_here} confirmed entries", file=sys.stderr)
        si_count += len(cids)
    return entries


def decode_directory(img, track, side=0, verbose=False):
    # NEWDOS/80 & G-DOS directory entries are 32-byte FPDE/FXDE records that
    # NEVER span a sector boundary: each 256-byte directory sector holds
    # exactly 8 slots at fixed offsets 0,32,...,224. The first sectors of the
    # directory track are NOT entries -- sector 0 is the GAT, sector 1 the HIT,
    # and (depending on the build) several following sectors carry boot/system
    # data. The number of such leading non-entry sectors VARIES by disk
    # (e.g. esnd-15/25 keep entries in sectors 10-17, not from sector 0).
    #
    # The old approach concatenated the whole track into one blob and strode
    # 32 bytes from offset 0. That (a) let GAT/HIT/system bytes pass as phantom
    # entries and (b) could misalign the stride, producing dozens of bogus
    # files ("damaged directory"). Parsing each sector independently in 8 fixed
    # slots removes both failure modes: a sector that is GAT/HIT/system simply
    # yields no _valid_entry hits and is skipped, no matter where it sits.
    secs = img.track_sectors(track, side)
    entries = []
    for s in sorted(secs):
        sector = secs[s]
        for slot in range(0, len(sector) - ENTRY_SIZE + 1, ENTRY_SIZE):
            ent = sector[slot:slot + ENTRY_SIZE]
            if len(ent) < ENTRY_SIZE or not _valid_entry(ent):
                continue
            entries.append(_make_dir_entry(ent))

    # A directory whose live-file count exceeds what the primary track holds
    # continues onto the next track/side (see _decode_directory_continuation).
    entries.extend(_decode_directory_continuation(img, track, side, verbose))
    return entries


def _parse_extents(ent):
    # Extent area in TRSDOS-family directory entries holds pairs describing
    # granule runs. The exact packing varies by DOS. We read pairs from the
    # tail of the entry as (cylinder/granule, count) until a 0xFF terminator.
    extents = []
    for p in range(22, ENTRY_SIZE - 1, 2):
        a, b = ent[p], ent[p + 1]
        if a == 0xFF:
            break
        extents.append((a, b))
    return extents


# ---------------------------------------------------------------------------
# Reporting / extraction
# ---------------------------------------------------------------------------

STANDARD_GEOMETRIES = (35, 40, 80)


def track_count_note(ntracks):
    """TRS-80 media is formatted to 35, 40, or 80 tracks. An image with one
    extra track (36/41/81) is the classic signature of an imaging over-read:
    the dumper stepped one track past the formatted area. We cannot prove the
    extra track is noise vs. real data from the count alone, so we only flag
    it for the reader rather than silently 'correcting' it."""
    if ntracks - 1 in STANDARD_GEOMETRIES:
        return (f" (note: standard TRS-80 media is 35/40/80 tracks; {ntracks} "
                f"likely means a one-track imaging over-read past track "
                f"{ntracks - 2} — the last track may be over-step noise rather "
                f"than real data)")
    return ""


def detect_geometry(img, dirtrack, dirside):
    """Detect (sides, spt, gpl, offset) for the disk's geometry.

    The extraction model (validated byte/CR-exact across SS-SD G-DOS, and
    DS-DD NEWDOS at GPL 2 and 6) is:

        flat_sector = (lump * gpl + startgran) * 5      # 5 sectors / granule
        abs_sector  = flat_sector + offset
        physical:   SS -> track = abs // spt, side 0
                    DS -> cyl = abs // (2*spt); side = (abs % (2*spt)) // spt

    - sides and spt (sectors per track) are observed directly from the image.
    - gpl (granules per lump) and offset are solved from a directory-marker
      entry whose data IS the directory and therefore sits at a known sector.
      G-DOS uses INHALT/SYS; NEWDOS uses DIR/SYS. Observed: SS-SD -> gpl 2,
      offset 0; DS-DD -> gpl 2 or 6, offset 36 (one reserved cylinder).
    """
    from collections import Counter
    spt_counts = Counter()
    for (t, h, s) in img.sectors:
        spt_counts[(t, h)] += 1
    spt = Counter(spt_counts.values()).most_common(1)[0][0]
    sides = img.sides

    # directory-marker entry: DIR/SYS (NEWDOS) or INHALT/SYS (G-DOS)
    secs = img.track_sectors(dirtrack, dirside)
    blob = b"".join(secs[s] for s in sorted(secs))

    def find(n, x):
        for off in range(0, len(blob) - 32, 32):
            e = blob[off:off + 32]
            if (_valid_entry(e) and e[5:13] == n.ljust(8).encode()
                    and e[13:16] == x.ljust(3).encode()):
                return e
        return None

    marker = find("DIR", "SYS") or find("INHALT", "SYS")
    # absolute sector of the directory track in this disk's ordering
    if sides == 1:
        abs_dir = dirtrack * spt
    else:
        abs_dir = dirtrack * (2 * spt) + dirside * spt

    # offset convention: 0 for SS, one reserved cylinder (2*spt) for DS.
    offset = 0 if sides == 1 else 2 * spt

    gpl = 2
    if marker is not None:
        ldir = marker[22]
        sg = (marker[23] & 0xE0) >> 5
        if ldir:
            # abs_dir = (ldir*gpl + sg)*5 + offset  ->  solve gpl
            val = (abs_dir - offset) / 5.0
            cand = round((val - sg) / ldir)
            if cand in (2, 3, 6):
                gpl = cand
    return sides, spt, gpl, offset


def resolve_extent_start(lump, second_byte, gpl=6, offset=36):
    """flat-space start sector for an extent pair, plus the disk's offset.
        abs = (lump*gpl + startgran)*5 + offset ; startgran = byte>>5 ; gran=5."""
    startgran = (second_byte & 0xE0) >> 5
    return (lump * gpl + startgran) * 5 + offset


def extract_file(img, entry, dirtrack=15, dirside=0, gpl=6, spt=18,
                 sides=2, offset=36):
    """Extract a file's bytes by resolving and concatenating its extent runs.

    Each extent pair is (lump, second_byte); the low 5 bits of second_byte are
    (granule_count - 1), each granule being 5 sectors. An FPDE holds up to 4
    inline extent pairs (bytes 22-29). If byte 30 == 0xFE, byte 31 is a link to
    an FXDE (extended directory entry) holding further extent pairs; the FXDE
    index is (link_byte >> 5). FXDEs are chained the same way.

    Geometry (sides, spt, gpl, offset) is supplied by detect_geometry().
    Validated byte/CR-exact across SS-SD G-DOS and DS-DD NEWDOS (GPL 2 and 6).
    """
    per_cyl = spt * sides

    def get_abs(a):
        if sides == 1:
            return img.get(a // spt, 0, a % spt)
        cyl = a // per_cyl
        rem = a % per_cyl
        return img.get(cyl, rem // spt, rem % spt)

    def dir_entry_raw(idx):
        sec = 8 + idx // 8  # FDE sectors begin at sector 8 of the dir track
        d = img.get(dirtrack, dirside, sec)
        if not d:
            return None
        return d[(idx % 8) * 32:(idx % 8) * 32 + 32]

    raw = entry.raw
    nsec = raw[20] | (raw[21] << 8)
    eof = raw[3]
    warnings = []

    # Collect all extent pairs, following any FXDE continuation chain.
    # An FPDE/FXDE holds extent pairs in bytes 22..29 plus 30..31. A first
    # byte of 0xFF ends the chain; 0xFE means the following byte is the DEC
    # (directory entry code) of an FXDE holding more pairs (Klaus Kaempf's
    # newdos.rb unpack_extends).
    pairs = []
    cur = raw
    seen_fxde = set()
    while cur is not None:
        nxt = None
        for p in range(22, 32, 2):
            lo = cur[p]
            hi = cur[p + 1]
            if lo == 0xFF:
                break
            if lo == 0xFE:
                link = hi >> 5
                if link not in seen_fxde:
                    seen_fxde.add(link)
                    nxt = dir_entry_raw(link)
                break
            pairs.append((lo, hi))
        cur = nxt

    data = bytearray()
    for (lump, b1) in pairs:
        start = resolve_extent_start(lump, b1, gpl, offset)
        gcount = (b1 & 0x1F) + 1
        for s in range(gcount * 5):
            d = get_abs(start + s)
            data += d if d else b"\x00" * 256

    # File size per Klaus Kaempf / NEWDOS spec: bytes 20-21 are the EOF
    # relative sector count (eof_mid, eof_high); if the EOF byte (byte 3) is
    # non-zero, the sector count is one too high, so subtract one. The final
    # length is eof_sector*256 + eof_byte.
    eof_byte = raw[3]
    eof_sector = (raw[21] << 8) | raw[20]
    if eof_byte != 0:
        eof_sector -= 1
    truelen = eof_sector * 256 + eof_byte
    if truelen > len(data):
        warnings.append(f"declared length {truelen} exceeds granule span "
                        f"{len(data)}; file may use an unresolved extent")
        truelen = len(data)
    return bytes(data[:truelen]), warnings


def read_file_from_start(img, start_abs, nsec, eof_offset):
    """Low-level engine: read nsec sectors from a known ABSOLUTE start sector
    (two-sided contiguous ordering) and trim by EOF. Used by --extract-at and
    the self-test."""
    spt = 18
    sides = img.sides
    per_cyl = spt * sides

    def get_abs(a):
        cyl = a // per_cyl
        rem = a % per_cyl
        return img.get(cyl, rem // spt, rem % spt)

    out = bytearray()
    for i in range(nsec):
        d = get_abs(start_abs + i)
        out += d if d else b"\x00" * 256
    truelen = (nsec - 1) * 256 + (eof_offset if eof_offset else 256)
    return bytes(out[:truelen])


def self_test(img):
    """Built-in regression: extract WBEDIT/SAV from esnd-23 by its known
    start sector and confirm the engine still works (length check).
    Only meaningful on the esnd-23 reference disk."""
    data = read_file_from_start(img, start_abs=331, nsec=59, eof_offset=251)
    return len(data) == 15099


def list_directory(img, entries, dirtrack, dirside=0):
    note = track_count_note(img.ntracks)
    print(f"trsextract {__version__}   Format: {img.fmt}   "
          f"Tracks: {img.ntracks}{note}")
    print(f"Sides: {img.sides}   Sector size: {img.sector_size}")
    side_s = f" side {dirside}" if img.sides > 1 else ""
    print(f"Directory track: {dirtrack}{side_s}")
    print(f"{'Filename':<14} {'Attr':>4} {'LRL':>4} {'EOFoff':>6}  Extents")
    print("-" * 60)
    for e in entries:
        ext_s = " ".join(f"{a}:{b}" for a, b in e.extents) or "-"
        print(f"{e.filename:<14} {e.attr:>4} {e.lrl:>4} {e.eof_offset:>6}  {ext_s}")
    print(f"\n{len(entries)} entries.")



# ===========================================================================
# WRITE SUPPORT (NEWDOS/80 DSDD) - v1.2
# ---------------------------------------------------------------------------
# Validated end-to-end against real NEWDOS/80 in the sdltrs emulator: a
# tokenized BASIC file written by this code LOADs, LISTs and RUNs correctly.
# Built from Klaus Kaempf's newdos.rb (authoritative) and the TRSDOS/NEWDOS
# directory specification:
#   - Directory Entry Code (DEC): dec = (rrr<<5)+sssss, where sssss selects
#     the entry sector (entries start 2 sectors after the GAT) and rrr selects
#     the 32-byte slot within that sector.
#   - The HIT byte for a file lives at offset == DEC (NOT a linear slot index).
#   - hashcode(): XOR-rotate over the 11-byte name+ext (Kaempf newdos.rb).
#   - Entry layout: 0=type 1-2=date 3=eof_byte 4=lrl 5-12=name 13-15=ext
#     16-19=update/access hash 20-21=eof relative-sector 22+=extent pairs.
#   - Extent pair: (lump, (startgran<<5)|(ngran-1)), 0xFF terminates.
# v1 scope: append a file into free space. Operates on a COPY. No overwrite,
# delete, or defragment. DSDD NEWDOS/80 geometry (spt=18/side, gpl=6).
# ===========================================================================

def _crc16_ccitt(data, crc=0xFFFF):
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if (crc & 0x8000) else (crc << 1) & 0xFFFF
    return crc

def newdos_hashcode(name8, ext3):
    """NEWDOS/80 directory HIT hash (Kaempf newdos.rb). name8+ext3 = 11 bytes."""
    hc = 0
    for a in (name8 + ext3):
        a ^= hc
        a = a * 2
        if a > 255:
            a -= 256; a += 1
        hc = a
    return hc

# ---- BASIC tokenizer (TRS-80 Level II / Disk BASIC) -----------------------
_BASIC_LOAD_BASE = 0x6A46
_BASIC_TOKENS = {
    "END":0x80,"FOR":0x81,"RESET":0x82,"SET":0x83,"CLS":0x84,"CMD":0x85,
    "RANDOM":0x86,"NEXT":0x87,"DATA":0x88,"INPUT":0x89,"DIM":0x8A,"READ":0x8B,
    "LET":0x8C,"GOTO":0x8D,"RUN":0x8E,"IF":0x8F,"RESTORE":0x90,"GOSUB":0x91,
    "RETURN":0x92,"REM":0x93,"STOP":0x94,"ELSE":0x95,"TRON":0x96,"TROFF":0x97,
    "DEFSTR":0x98,"DEFINT":0x99,"DEFSNG":0x9A,"DEFDBL":0x9B,"LINE":0x9C,
    "EDIT":0x9D,"ERROR":0x9E,"RESUME":0x9F,"OUT":0xA0,"ON":0xA1,"OPEN":0xA2,
    "FIELD":0xA3,"GET":0xA4,"PUT":0xA5,"CLOSE":0xA6,"LOAD":0xA7,"MERGE":0xA8,
    "NAME":0xA9,"KILL":0xAA,"LSET":0xAB,"RSET":0xAC,"SAVE":0xAD,"SYSTEM":0xAE,
    "LPRINT":0xAF,"DEF":0xB0,"POKE":0xB1,"PRINT":0xB2,"CONT":0xB3,"LIST":0xB4,
    "LLIST":0xB5,"DELETE":0xB6,"AUTO":0xB7,"CLEAR":0xB8,"CLOAD":0xB9,
    "CSAVE":0xBA,"NEW":0xBB,"TAB(":0xBC,"TO":0xBD,"FN":0xBE,"USING":0xBF,
    "VARPTR":0xC0,"USR":0xC1,"ERL":0xC2,"ERR":0xC3,"STRING$":0xC4,
    "INSTR":0xC5,"POINT":0xC6,"TIME$":0xC7,"MEM":0xC8,"INKEY$":0xC9,
    "THEN":0xCA,"NOT":0xCB,"STEP":0xCC,"+":0xCD,"-":0xCE,"*":0xCF,"/":0xD0,
    "[":0xD1,"AND":0xD2,"OR":0xD3,">":0xD4,"=":0xD5,"<":0xD6,"SGN":0xD7,
    "INT":0xD8,"ABS":0xD9,"FRE":0xDA,"INP":0xDB,"POS":0xDC,"SQR":0xDD,
    "RND":0xDE,"LOG":0xDF,"EXP":0xE0,"COS":0xE1,"SIN":0xE2,"TAN":0xE3,
    "ATN":0xE4,"PEEK":0xE5,"CVI":0xE6,"CVS":0xE7,"CVD":0xE8,"EOF":0xE9,
    "LOC":0xEA,"LOF":0xEB,"MKI$":0xEC,"MKS$":0xED,"MKD$":0xEE,"CINT":0xEF,
    "CSNG":0xF0,"CDBL":0xF1,"FIX":0xF2,"LEN":0xF3,"STR$":0xF4,"VAL":0xF5,
    "ASC":0xF6,"CHR$":0xF7,"LEFT$":0xF8,"RIGHT$":0xF9,"MID$":0xFA,
}
_BASIC_KW = sorted(_BASIC_TOKENS.keys(), key=len, reverse=True)

def _tokenize_line(text):
    out = bytearray(); i = 0; n = len(text)
    while i < n:
        c = text[i]
        if c == '"':
            out.append(0x22); i += 1
            while i < n and text[i] != '"':
                out.append(ord(text[i])); i += 1
            if i < n:
                out.append(0x22); i += 1
            continue
        up = text[i:].upper(); matched = None
        for kw in _BASIC_KW:
            if up.startswith(kw):
                matched = kw; break
        if matched:
            out.append(_BASIC_TOKENS[matched]); i += len(matched)
            if matched == "REM":
                while i < n:
                    out.append(ord(text[i])); i += 1
            continue
        out.append(ord(c)); i += 1
    return bytes(out)

def tokenize_basic(source_lines):
    """source_lines: list of (lineno:int, text:str). Returns tokenized image
    in NEWDOS BASIC SAVE format (FF marker ... 00 00 terminator)."""
    body = bytearray(); body.append(0xFF)
    cur = _BASIC_LOAD_BASE
    for lineno, text in source_lines:
        toks = _tokenize_line(text)
        rec_len = 2 + 2 + len(toks) + 1
        nextptr = cur + rec_len
        body += nextptr.to_bytes(2, 'little')
        body += lineno.to_bytes(2, 'little')
        body += toks
        body.append(0x00)
        cur = nextptr
    body += b'\x00\x00'
    return bytes(body)

def parse_basic_source(text):
    """Parse plain BASIC text (one statement per line, leading line number)
    into [(lineno, rest)]."""
    out = []
    for raw in text.replace('\r\n','\n').replace('\r','\n').split('\n'):
        s = raw.rstrip()
        if not s.strip():
            continue
        i = 0
        while i < len(s) and s[i].isdigit():
            i += 1
        if i == 0:
            raise ValueError(f"line without a line number: {s!r}")
        lineno = int(s[:i])
        rest = s[i:].lstrip()
        out.append((lineno, rest))
    return out


class DMKWriteImage:
    """Write-aware DMK accessor: keeps the raw bytes and each sector's data
    offset so sectors can be overwritten with regenerated CRCs. Keyed by
    PHYSICAL side (image position), not the recorded IDAM side byte."""
    def __init__(self, path):
        self.path = path
        self.raw = bytearray(open(path, 'rb').read())
        self.ntracks = self.raw[1]
        self.track_len = struct.unpack_from('<H', self.raw, 2)[0]
        self.sides = 1 if (self.raw[4] & 0x10) else 2
        self.HEADER = 16
        self.index = {}
        for t in range(self.ntracks):
            for s in range(self.sides):
                self._index_track(t, s)

    def _track_base(self, track, side):
        return self.HEADER + (track * self.sides + side) * self.track_len

    def _index_track(self, track, side):
        base = self._track_base(track, side)
        td = self.raw[base:base + self.track_len]
        for i in range(0, 0x80, 2):
            raw = struct.unpack_from('<H', td, i)[0]
            if raw == 0:
                continue
            off = raw & 0x3FFF
            dd = bool(raw & 0x8000)
            if off >= len(td) or td[off] != 0xFE:
                continue
            sec = td[off + 3]
            size = 128 << (td[off + 4] & 0x03)
            data_off = dam_off = None
            if dd:
                for p in range(off + 7, min(off + 60, len(td) - 4)):
                    if (td[p] == 0xA1 and td[p+1] == 0xA1 and td[p+2] == 0xA1
                            and td[p+3] in (0xF8, 0xF9, 0xFA, 0xFB)):
                        dam_off = p + 3; data_off = p + 4; break
            else:
                for p in range(off + 7, min(off + 60, len(td) - 2)):
                    if td[p] in (0xF8, 0xF9, 0xFA, 0xFB):
                        dam_off = p; data_off = p + 1; break
            if data_off is None:
                continue
            self.index[(track, side, sec)] = (base + data_off, base + dam_off, size, dd)

    def read_sector(self, track, side, sector):
        rec = self.index.get((track, side, sector))
        if not rec:
            return None
        data_off, dam_off, size, dd = rec
        return bytes(self.raw[data_off:data_off + size])

    def write_sector(self, track, side, sector, newdata):
        rec = self.index.get((track, side, sector))
        if not rec:
            raise KeyError(f"sector ({track},{side},{sector}) not formatted")
        data_off, dam_off, size, dd = rec
        if len(newdata) != size:
            raise ValueError(f"expected {size} bytes, got {len(newdata)}")
        self.raw[data_off:data_off + size] = newdata
        if dd:
            crc = _crc16_ccitt(bytes([0xA1,0xA1,0xA1]) + bytes(self.raw[dam_off:dam_off+1+size]))
        else:
            crc = _crc16_ccitt(bytes(self.raw[dam_off:dam_off+1+size]))
        self.raw[data_off + size] = (crc >> 8) & 0xFF
        self.raw[data_off + size + 1] = crc & 0xFF

    def save(self, path=None):
        open(path or self.path, 'wb').write(self.raw)


def _locate_dir_structures(img, verbose=False):
    """Locate directory geometry and structures for write-side operations.

    Returns dict(dt, ds, sides, spt, gpl, offset, gat_id, hit_id, ent_ids,
    secs). GAT and HIT are the two sectors before the first entry sector;
    entry sectors are those containing at least one structurally valid FPDE
    (or BOOT/SYS, attr 0x94, excluded by _valid_entry as an FXDE pattern).
    Shared by --undelete and the writer so both resolve SS-SD and DSDD
    layouts identically."""
    dt, ds = find_directory_track(img, verbose=verbose)
    sides, spt, gpl, offset = detect_geometry(img, dt, ds)
    secs = img.track_sectors(dt, ds)
    ids = sorted(secs)

    def is_entry_sector(d):
        return any(_valid_entry(d[o:o + 32]) or d[o] == 0x94
                   for o in range(0, 256, 32))
    detected = [s for s in ids if is_entry_sector(secs[s])]
    first_ent = detected[0]
    # Entry sectors run contiguously from the first one to the end of the
    # track (DEC's sssss counts them from there). Detection alone would miss
    # sectors holding only never-used slots, hiding their free entries.
    ent_ids = [s for s in ids if s >= first_ent]
    hit_id = ids[ids.index(first_ent) - 1]
    gat_id = ids[ids.index(first_ent) - 2]
    return dict(dt=dt, ds=ds, sides=sides, spt=spt, gpl=gpl, offset=offset,
                gat_id=gat_id, hit_id=hit_id, ent_ids=ent_ids, secs=secs)


def _confirm_hit_mapping(secs, ent_ids, hit):
    """Count live entries whose HIT hash sits at the computed DEC
    (offset = entry_sector_index + 32*row). Both write-side operations
    require >= 2 confirmations before modifying the directory: a mis-mapped
    HIT write would de-list OTHER files."""
    confirmed = 0
    live_slots = set()
    for si, sid in enumerate(ent_ids):
        d = secs[sid]
        for row in range(8):
            e = d[row * 32:(row + 1) * 32]
            if not (_valid_entry(e) or e[0] == 0x94):
                continue
            dec = si + 32 * row
            if dec < len(hit) and hit[dec] != 0 and \
                    hit[dec] == newdos_hashcode(e[5:13], e[13:16]):
                confirmed += 1
                live_slots.add((sid, row))
    return confirmed, live_slots


def undelete_file(image_path, name, ext, out_path, force=False, verbose=False):
    """Resurrect a KILLed NEWDOS/80 file in a COPY of the image.

    A kill clears the entry's active bit (0x10), removes its HIT hash, and
    frees its granules in the GAT — but leaves the entry bytes and (unless
    reused) the data sectors intact. Undelete reverses all three, geometry-
    aware via the same detection the read path uses.

    Safety: refuses (unless force=True) when the dead file's granules overlap
    any HIT-live file's granules — overlap means the data was partially
    overwritten and resurrection would yield a corrupt file.
    HIT offset mapping ((sector_index)+32*row) and hash verified against the
    7 live entries of esnd-40 (SS 10-spt) — DSDD layout uses the same rule.
    """
    img = load_image(image_path, verbose)
    loc = _locate_dir_structures(img, verbose)
    dt, ds = loc['dt'], loc['ds']
    gpl = loc['gpl']
    secs = loc['secs']
    ent_ids = loc['ent_ids']
    hit_id, gat_id = loc['hit_id'], loc['gat_id']
    hit = bytearray(secs[hit_id])
    gat = bytearray(secs[gat_id])

    def extents_of(e):
        out, p = [], 22
        while p < 31 and e[p] != 0xFF:
            out.append((e[p], e[p + 1])); p += 2
        return out

    def granules(exts):
        g = set()
        for lump, packed in exts:
            base = lump * gpl + ((packed & 0xE0) >> 5)
            for k in range((packed & 0x1F) + 1):
                g.add(base + k)
        return g

    name8 = name.upper().ljust(8).encode()
    ext3 = ext.upper().ljust(3).encode()
    target = None            # (sector_id, row, entry_bytes, dec)
    live_gran = set()
    confirmed = 0            # entries whose hash sits at the computed DEC
    for si, sid in enumerate(ent_ids):
        d = secs[sid]
        for row in range(8):
            e = d[row * 32:(row + 1) * 32]
            if not (_valid_entry(e) or e[0] == 0x94):
                continue
            dec = si + 32 * row
            in_hit = dec < len(hit) and hit[dec] != 0 and \
                hit[dec] == newdos_hashcode(e[5:13], e[13:16])
            if in_hit:
                confirmed += 1
                live_gran |= granules(extents_of(e))
            elif e[5:13] == name8 and e[13:16] == ext3:
                target = (sid, row, bytearray(e), dec)
    if confirmed < 2:
        raise RuntimeError(f"HIT mapping could not be confirmed "
                           f"({confirmed} live entries matched their "
                           f"computed HIT slot); refusing to modify the "
                           f"directory")
    if target is None:
        raise RuntimeError(f"{name}/{ext}: no dead directory entry found "
                           f"(already live, or never on this disk)")
    sid, row, e, dec = target
    exts = extents_of(e)
    if not exts:
        raise RuntimeError(f"{name}/{ext}: dead entry has no extents left - "
                           f"nothing to resurrect")
    mine = granules(exts)
    clash = sorted(mine & live_gran)
    if clash and not force:
        raise RuntimeError(f"{name}/{ext}: granules {clash} were reallocated "
                           f"to live files; data partially overwritten. "
                           f"Use force to resurrect anyway (file WILL be "
                           f"corrupt).")

    import shutil
    shutil.copy(image_path, out_path)
    w = DMKWriteImage(out_path)
    e[0] |= 0x10                       # active bit
    d = bytearray(w.read_sector(dt, ds, sid))
    d[row * 32:(row + 1) * 32] = e
    w.write_sector(dt, ds, sid, bytes(d))
    hit[dec] = newdos_hashcode(bytes(e[5:13]), bytes(e[13:16]))
    w.write_sector(dt, ds, hit_id, bytes(hit))
    for g in mine:                     # re-mark granules used in GAT
        gat[g // gpl] |= (1 << (g % gpl))
    w.write_sector(dt, ds, gat_id, bytes(gat))
    w.save(out_path)
    return dict(filename=f"{name.upper()}/{ext.upper()}", dec=dec,
                granules=sorted(mine), overlap=clash, out=out_path)


class Newdos80Writer:
    """Append a file into free space of a NEWDOS/80 DMK image.

    Since 1.7 the writer is geometry-aware: directory track/side, GAT, HIT,
    and entry sectors are located structurally (shared locator with
    --undelete), and geometry (sides, spt, gpl, offset) comes from
    detect_geometry. Before any directory write, the DEC->HIT mapping must
    confirm against >= 2 live entries, else the writer aborts."""
    def __init__(self, path, verbose=False):
        self.w = DMKWriteImage(path)
        img = load_image(path, verbose)
        loc = _locate_dir_structures(img, verbose)
        self.sides = loc['sides']
        self.spt = loc['spt']; self.gpl = loc['gpl']
        self.sec_per_gran = 5; self.offset = loc['offset']
        self.dt, self.ds = loc['dt'], loc['ds']
        self.gat_sec, self.hit_sec = loc['gat_id'], loc['hit_id']
        self.ent_ids = loc['ent_ids']
        hit = img.get(self.dt, self.ds, self.hit_sec)
        confirmed, self._live_slots = _confirm_hit_mapping(
            loc['secs'], self.ent_ids, hit)
        if confirmed < 2:
            raise RuntimeError(
                f"HIT mapping could not be confirmed ({confirmed} live "
                f"entries matched); refusing to write to this directory "
                f"layout")
        # granule address space: bounded by the actual sector count
        self.max_gran = (len(img.sectors) - self.offset) // self.sec_per_gran

    def _abs_to_phys(self, abs_sec):
        if self.sides == 1:
            return abs_sec // self.spt, 0, abs_sec % self.spt
        cyl = abs_sec // (2*self.spt)
        rem = abs_sec % (2*self.spt)
        return cyl, rem // self.spt, rem % self.spt

    def write_basic_file(self, fname, ext, source_lines):
        return self._write(fname, ext, tokenize_basic(source_lines))

    def write_data_file(self, fname, ext, data):
        return self._write(fname, ext, data)

    def _free_granule_run(self, gat, need, reserved_lumps=2):
        """First contiguous run of `need` free granules. Granules are numbered
        continuously across the disk: gran = lump*gpl + bit. A granule is free
        when its GAT bit is clear and its lump byte is not 0xFF (fully reserved
        system area). Returns the starting granule index, or None."""
        gpl = self.gpl
        def is_free(gran):
            lump = gran // gpl; bit = gran % gpl
            if lump < reserved_lumps or gran >= self.max_gran:
                return False
            if gat[lump] == 0xFF:
                return False
            return (gat[lump] & (1 << bit)) == 0
        run = 0; start = None
        for gran in range(reserved_lumps*gpl, self.max_gran):
            if is_free(gran):
                if run == 0:
                    start = gran
                run += 1
                if run == need:
                    return start
            else:
                run = 0; start = None
        return None

    def _extent_pairs(self, start_gran, ngran):
        """Encode a contiguous granule run as NEWDOS extent pairs. A single
        extent is (lump, (startgran_in_lump<<5)|(count-1)). The count field is
        5 bits (max 32 granules) and may span lumps (granules are continuous).
        Runs longer than 32 granules split into multiple extents. Returns a
        list of (lump, packed_byte). NEWDOS itself writes one extent for runs
        that fit, e.g. SARGON/CMD: lump 0, startgran 1, ngran 8."""
        pairs = []
        g = start_gran
        remaining = ngran
        while remaining > 0:
            lump = g // self.gpl
            startgran_in_lump = g % self.gpl
            count = min(remaining, 32)
            pairs.append((lump, (startgran_in_lump << 5) | ((count - 1) & 0x1F)))
            g += count
            remaining -= count
            if len(pairs) > 4:
                # Beyond 4 extents NEWDOS uses FXDE continuation entries, which
                # this version does not yet emit. Contiguous allocation keeps us
                # to a single extent in practice, so this is a guard, not a path.
                raise RuntimeError("file too fragmented for v1 (needs FXDE)")
        return pairs

    def _write(self, fname, ext, data):
        w = self.w
        name8 = fname.upper().ljust(8)[:8].encode('ascii')
        ext3  = ext.upper().ljust(3)[:3].encode('ascii')
        nsec = (len(data) + 255) // 256
        ngran = (nsec + self.sec_per_gran - 1) // self.sec_per_gran

        gat = bytearray(w.read_sector(self.dt, self.ds, self.gat_sec))
        start_gran = self._free_granule_run(gat, ngran)
        if start_gran is None:
            raise RuntimeError(f"no contiguous run of {ngran} free granules "
                               f"on disk")
        pairs = self._extent_pairs(start_gran, ngran)
        if len(pairs) > 4:
            raise RuntimeError("file needs more than 4 extents (FXDE) - "
                               "not supported in this version")

        # write data sectors across the contiguous granule run
        for i in range(nsec):
            gran = start_gran + (i // self.sec_per_gran)
            sec_in_gran = i % self.sec_per_gran
            abs_sec = gran*self.sec_per_gran + sec_in_gran + self.offset
            cyl, side, sec = self._abs_to_phys(abs_sec)
            chunk = data[i*256:(i+1)*256]
            chunk = chunk + b'\x00'*(256 - len(chunk))
            w.write_sector(cyl, side, sec, chunk)

        # mark every allocated granule bit in the GAT (may span lumps)
        for g in range(start_gran, start_gran + ngran):
            lump = g // self.gpl; bit = g % self.gpl
            gat[lump] |= (1 << bit)
        w.write_sector(self.dt, self.ds, self.gat_sec, bytes(gat))

        eof_byte = len(data) - (nsec-1)*256
        if eof_byte == 256:
            eof_byte = 0
        rel = nsec

        # Find a free directory slot. Slots occupied by HIT-live entries are
        # never candidates. Among the rest, VIRGIN slots (no structurally
        # valid entry) are preferred over KILLed entries, so writing does not
        # destroy dead entries that --undelete could still resurrect; dead
        # slots are reused only when no virgin slot remains (as NEWDOS does).
        virgin = None; dead = None
        for sssss, esec in enumerate(self.ent_ids):
            d = w.read_sector(self.dt, self.ds, esec)
            if d is None:
                continue
            for rrr in range(0, 256 // 32):
                off = rrr * 32
                if (esec, rrr) in self._live_slots:
                    continue
                e = d[off:off + 32]
                if e[0] == 0x94:                     # BOOT/SYS
                    continue
                if e[0] & 0x50:                      # active or system bit:
                    continue                         # occupied, HIT or not
                if _valid_entry(e) or (e[0] & 0x80): # dead FPDE / FXDE-like
                    if dead is None and _valid_entry(e):
                        dead = (sssss, rrr, esec, off)
                    continue
                if virgin is None:
                    virgin = (sssss, rrr, esec, off)
            if virgin:
                break
        chosen = virgin or dead
        if not chosen:
            raise RuntimeError("directory full")
        sssss, rrr, esec, off = chosen
        dec = (rrr << 5) + sssss

        ent = bytearray(32)
        ent[0] = 0x10
        ent[3] = eof_byte & 0xFF
        ent[5:13] = name8
        ent[13:16] = ext3
        ent[16] = 0x96; ent[17] = 0x42; ent[18] = 0x96; ent[19] = 0x42
        ent[20] = rel & 0xFF
        ent[21] = (rel >> 8) & 0xFF
        # write extent pairs starting at byte 22
        p = 22
        for (lump, packed) in pairs:
            ent[p] = lump; ent[p+1] = packed; p += 2
        for k in range(p, 32):
            ent[k] = 0xFF
        d = bytearray(w.read_sector(self.dt, self.ds, esec))
        d[off:off+32] = ent
        w.write_sector(self.dt, self.ds, esec, bytes(d))

        hit = bytearray(w.read_sector(self.dt, self.ds, self.hit_sec))
        hit[dec] = newdos_hashcode(name8, ext3)
        w.write_sector(self.dt, self.ds, self.hit_sec, bytes(hit))
        return dict(filename=f"{fname.upper()}/{ext.upper()}",
                    lump=start_gran // self.gpl, sectors=nsec, dec=dec,
                    hit=hit[dec], extents=len(pairs))

    def save(self, path=None):
        self.w.save(path)


def main():
    ap = argparse.ArgumentParser(description="Extract TRS-80 NEWDOS/80 & "
                                             "G-DOS files from DMK/DSK images.")
    ap.add_argument("image")
    ap.add_argument("-o", "--output", help="output directory (extract mode)")
    ap.add_argument("--track", type=int, help="force directory track")
    ap.add_argument("--detokenize", action="store_true",
                    help="de-tokenize /BAS files to ASCII")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--version", action="version",
                    version=f"trsextract {__version__}")
    ap.add_argument("--extract-at", metavar="START,NSEC,EOF",
                    help="extract a file from a KNOWN start: absolute start "
                         "sector, sector count, and EOF-offset-in-last-sector "
                         "(0=full). Writes to --output or stdout. The start "
                         "must be supplied because automatic start resolution "
                         "(GAT decoding) is not yet implemented.")
    ap.add_argument("--write-basic", metavar="SRC.bas",
                    help="tokenize an ASCII BASIC source file and write it "
                         "into a COPY of the image (NEWDOS/80 DSDD). Use --as "
                         "to set the on-disk name; output goes to --output or "
                         "<image>.out.dsk. Validated against real NEWDOS.")
    ap.add_argument("--write-file", metavar="SRC",
                    help="write ANY host file verbatim into a COPY of the "
                         "image (NEWDOS/80 DSDD): /CMD, /TXT, data, source, "
                         "etc. Use --as to set the on-disk NAME/EXT. Handles "
                         "multi-lump files; needs a contiguous free-granule "
                         "run (no fragmented/FXDE allocation yet).")
    ap.add_argument("--as", dest="as_name", metavar="NAME/EXT",
                    help="on-disk filename for --write-basic / --write-file "
                         "(for --write-basic the default extension is /BAS; "
                         "for --write-file the source name and extension are "
                         "used unless overridden)")
    ap.add_argument("--undelete", metavar="NAME/EXT",
                    help="resurrect a KILLed file in a COPY of the image: "
                         "restores the entry's active bit, HIT hash, and GAT "
                         "allocation. Geometry-aware (SS-SD and DS-DD). "
                         "Refuses if the data granules were reallocated to "
                         "live files, unless --force is given.")
    ap.add_argument("--force", action="store_true",
                    help="with --undelete: resurrect even when granules "
                         "overlap live files (result will be corrupt)")
    ap.add_argument("--self-test", action="store_true",
                    help="run the built-in extraction regression "
                         "(meaningful only on the esnd-23 reference disk)")
    args = ap.parse_args()

    if args.undelete:
        nm = args.undelete.replace("\\", "/")
        name, _, ext = nm.partition("/")
        out_path = args.output or (os.path.splitext(args.image)[0] + ".out.dsk")
        try:
            info = undelete_file(args.image, name, ext, out_path,
                                 force=args.force, verbose=args.verbose)
        except Exception as e:
            print(f"ERROR undeleting: {e}", file=sys.stderr)
            sys.exit(2)
        warn = (f"  WARNING: granules {info['overlap']} overlapped live "
                f"files - data corrupt!" if info['overlap'] else "")
        print(f"Undeleted {info['filename']} (DEC {info['dec']}, granules "
              f"{info['granules']}) -> {info['out']}{warn}")
        sys.exit(0)

    if args.write_basic:
        # Write a tokenized BASIC file into a COPY of the image. Never touches
        # the original. Done before load_image (an empty target disk has no
        # user files for the directory scan to lock onto).
        import shutil
        src_path = args.write_basic
        try:
            text = open(src_path, "r", encoding="latin-1").read()
            source_lines = parse_basic_source(text)
        except (OSError, ValueError) as e:
            print(f"ERROR reading BASIC source: {e}", file=sys.stderr)
            sys.exit(2)
        if args.as_name:
            nm = args.as_name.replace("\\", "/")
            name, _, ext = nm.partition("/")
            ext = ext or "BAS"
        else:
            base = os.path.basename(src_path)
            name = os.path.splitext(base)[0]
            ext = "BAS"
        out_path = args.output or (os.path.splitext(args.image)[0] + ".out.dsk")
        shutil.copy(args.image, out_path)
        try:
            nd = Newdos80Writer(out_path)
            info = nd.write_basic_file(name, ext, source_lines)
            nd.save(out_path)
        except Exception as e:
            print(f"ERROR writing file: {e}", file=sys.stderr)
            sys.exit(2)
        print(f"Wrote {info['filename']} ({info['sectors']} sector(s), "
              f"lump {info['lump']}, DEC {info['dec']}) -> {out_path}")
        sys.exit(0)

    if args.write_file:
        # Write ANY host file verbatim into a COPY of the image.
        import shutil
        src_path = args.write_file
        try:
            data = open(src_path, "rb").read()
        except OSError as e:
            print(f"ERROR reading source file: {e}", file=sys.stderr)
            sys.exit(2)
        if args.as_name:
            nm = args.as_name.replace("\\", "/")
            name, sep, ext = nm.partition("/")
        else:
            base = os.path.basename(src_path)
            stem, dot, e = base.partition(".")
            name = stem
            ext = e if dot else ""
        out_path = args.output or (os.path.splitext(args.image)[0] + ".out.dsk")
        shutil.copy(args.image, out_path)
        try:
            nd = Newdos80Writer(out_path)
            info = nd.write_data_file(name, ext, data)
            nd.save(out_path)
        except Exception as e:
            print(f"ERROR writing file: {e}", file=sys.stderr)
            sys.exit(2)
        print(f"Wrote {info['filename']} ({len(data)} bytes, "
              f"{info['sectors']} sector(s), lump {info['lump']}, "
              f"DEC {info['dec']}) -> {out_path}")
        sys.exit(0)

    img = load_image(args.image, args.verbose)
    if not img.sectors:
        print("ERROR: no sectors decoded; unrecognised or damaged image.",
              file=sys.stderr)
        sys.exit(2)

    if args.self_test:
        ok = self_test(img)
        print(f"self-test (WBEDIT/SAV extraction): "
              f"{'PASS' if ok else 'FAIL'}")
        sys.exit(0 if ok else 1)

    if args.extract_at:
        try:
            parts = [int(x) for x in args.extract_at.split(",")]
            start, nsec, eof = parts
        except ValueError:
            print("ERROR: --extract-at needs START,NSEC,EOF (three integers).",
                  file=sys.stderr)
            sys.exit(2)
        data = read_file_from_start(img, start, nsec, eof)
        if args.output:
            import os
            os.makedirs(args.output, exist_ok=True)
            path = os.path.join(args.output, f"extract_{start}.bin")
            with open(path, "wb") as f:
                f.write(data)
            print(f"wrote {len(data)} bytes to {path}")
        else:
            sys.stdout.buffer.write(data)
        sys.exit(0)

    dirtrack, dirside = find_directory_track(img, args.track, args.verbose)
    if dirtrack is None:
        # Distinguish a likely hard-disk volume from a damaged floppy. HD
        # volume images exceed floppy capacity and place their directory at a
        # PDRIVE-defined cylinder that floppy-track scanning cannot find.
        import os
        sz = os.path.getsize(args.image)
        floppy_max = 80 * 2 * 18 * 256  # ~720 KB, max DD 80-track 2-sided
        if sz > floppy_max:
            print(
                f"ERROR: no directory found by floppy-track scanning, and this "
                f"image ({sz // 1024} KB) is larger than any floppy "
                f"({floppy_max // 1024} KB max).\n"
                f"This is almost certainly a HARD-DISK VOLUME. Its directory "
                f"sits at a cylinder set by the PDRIVE geometry (DDSL/lump), "
                f"not on a scannable floppy track. To read it, the volume's "
                f"PDRIVE parameters (sectors/track, heads, directory lump) are "
                f"needed. Use --track N to point at the directory cylinder if "
                f"you know it.", file=sys.stderr)
            sys.exit(4)
        print("ERROR: could not locate a directory track. The image may be "
              "damaged, a non-NEWDOS/G-DOS format, or need --track N. "
              "Run with -v to inspect per-track scores.", file=sys.stderr)
        sys.exit(3)

    entries = decode_directory(img, dirtrack, dirside, args.verbose)
    list_directory(img, entries, dirtrack, dirside)

    if args.output:
        import os
        os.makedirs(args.output, exist_ok=True)
        sides, spt, gpl, offset = detect_geometry(img, dirtrack, dirside)
        print(f"\nExtracting {len(entries)} files to {args.output}/ "
              f"(sides={sides} spt={spt} GPL={gpl} offset={offset}) ...",
              file=sys.stderr)
        n_ok = 0
        for e in entries:
            data, warnings = extract_file(img, e, dirtrack, dirside,
                                          gpl, spt, sides, offset)
            # filesystem-safe name: NAME.EXT
            nm = e.name.decode("ascii", "replace").rstrip()
            ex = e.ext.decode("ascii", "replace").rstrip()
            fname = f"{nm}.{ex}" if ex else nm
            fname = fname.replace("/", "_")
            path = os.path.join(args.output, fname)
            with open(path, "wb") as f:
                f.write(data)
            n_ok += 1
            w = f"  ({warnings[0]})" if warnings else ""
            print(f"  {fname:<16} {len(data):6d} bytes{w}", file=sys.stderr)
        print(f"Done: {n_ok} files written.", file=sys.stderr)


if __name__ == "__main__":
    main()