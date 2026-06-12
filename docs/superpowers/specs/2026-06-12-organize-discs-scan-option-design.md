# Organize Discs — Scan Option Design

**Date:** 2026-06-12
**Status:** Approved, ready for implementation plan

## Summary

Add a standalone scan option — "Organize discs" — to the Scan page, sibling to
"Recalculate hashes". For the selected platforms it runs only the existing
`.m3u` + subfolder disc-restructure logic and syncs the library database. It
performs no metadata matching and makes no external provider calls.

## Motivation

`auto_organize_loose_discs` (`backend/handler/filesystem/roms_handler.py:702`)
already runs on every scan and restructures loose multi-disc `.cue` sets into an
`.m3u` + subfolder layout. Today the only way to trigger it is to run a full
scan, which also performs metadata matching. Users want to apply the
restructure to chosen platforms without the cost and side effects of metadata
matching — analogous to how "Recalculate hashes" updates the DB without
fetching metadata.

## Design Decisions

- **DB sync:** After restructuring files on disk, the option updates the
  library — it adds the new `.m3u` ROM entry and marks the now-gone loose `.cue`
  ROMs as missing. The library immediately reflects the new structure. No
  metadata is fetched.
- **Hashing:** The new `.m3u` ROM's files are hashed only if hashing is not
  globally disabled (`SKIP_HASH_CALCULATION`) — identical to any newly-added ROM
  during a normal scan. Only the new entry is hashed, never the whole platform.

## Architecture

The new scan type reuses existing machinery almost entirely. `ScanType.HASHES`
already establishes the pattern of a standalone scan operation that skips
metadata; the organize restructure already runs unconditionally on every scan.
The new type adds an enum member and three small gating changes plus the
frontend option.

### Backend (`backend/`)

1. **`handler/scan_handler.py` — `ScanType` enum (line 59)**
   Add member:
   ```python
   ORGANIZE = "organize"
   ```

2. **`endpoints/sockets/scan.py` — `scan_platforms`**
   When `scan_type == ScanType.ORGANIZE`, force `metadata_sources = []`
   (ignore any sources sent by the client). Every metadata gate in `scan_rom`
   requires `SOURCE in metadata_sources`, so an empty list yields zero provider
   calls — including for the newly-added `.m3u` ROM, which has `newly_added=True`
   and would otherwise trigger metadata gates that fire on new ROMs.

3. **`endpoints/sockets/scan.py` — `_should_scan_rom`**
   Add `ScanType.ORGANIZE` to the new-ROMs-only branch:
   ```python
   scan_type in {ScanType.NEW_PLATFORMS, ScanType.QUICK, ScanType.ORGANIZE} and not rom
   ```
   Only the freshly-created `.m3u` file (absent from the DB) is added. The loose
   `.cue` ROMs, now moved into the subfolder and gone from the FS listing, are
   marked missing by the existing `mark_missing_roms` call. Existing unaffected
   ROMs are left untouched.

4. **`endpoints/sockets/scan.py` — HASHES short-circuit in `_identify_rom`**
   Extend the existing short-circuit to ORGANIZE:
   ```python
   if scan_type in {ScanType.HASHES, ScanType.ORGANIZE}:
       return
   ```
   This skips cover/screenshot/media fetching after the ROM has been persisted.

5. **`endpoints/sockets/scan.py` — `_should_get_rom_files`**
   No change. Its existing `newly_added` branch already covers the new `.m3u`
   ROM, so its files are built and hashed respecting `SKIP_HASH_CALCULATION`.

6. **`endpoints/sockets/scan.py` — `auto_organize_loose_discs` call (line 573)**
   No change. Already unconditional and idempotent (skips when the `.m3u` /
   subfolder already exists), so it works correctly under ORGANIZE.

### Frontend (`frontend/`)

7. **`views/Scan.vue` — `scanOptions` array (line 105)**
   Add an option entry:
   ```js
   { title: t("scan.organize-discs"), subtitle: t("scan.organize-discs-desc"), value: "organize" }
   ```

8. **i18n — English locale (source of truth)**
   Add `scan.organize-discs` and `scan.organize-discs-desc` strings. Non-English
   translations are out of scope.

## Data Flow

1. `Scan.vue` emits the `scan` socket event with `type: "organize"` and the
   selected platforms.
2. `scan_platforms` sees `ScanType.ORGANIZE` and clears `metadata_sources`.
3. Per platform: `auto_organize_loose_discs` restructures loose `.cue` sets into
   `.m3u` + subfolder layout.
4. The platform's filesystem ROM list is re-read.
5. `_should_scan_rom` returns True only for the new `.m3u` file → it is added to
   the DB, its files built and hashed (per `SKIP_HASH_CALCULATION`).
6. `_identify_rom` short-circuits before any metadata/cover/media work.
7. The loose `.cue` ROMs absent from the FS are marked missing.
8. Scan stats are emitted as usual.

## Error Handling

Reuses the existing scan pipeline error handling: per-ROM exceptions are caught
and logged in the batch gather; filesystem/platform structure errors emit
`scan:done_ko`. No new error paths introduced. The restructure is idempotent, so
re-running ORGANIZE on an already-organized platform is a no-op.

## Testing

- **`_should_scan_rom` under ORGANIZE:** returns True for a new ROM
  (`rom is None`), False for an existing ROM.
- **Metadata suppression:** ORGANIZE forces `metadata_sources = []`; assert no
  provider calls occur for a newly-added ROM.
- **Integration-style:** given a loose multi-disc `.cue` set, after an ORGANIZE
  scan the DB contains the `.m3u` ROM, the loose `.cue` ROMs are marked missing,
  and no metadata IDs are set on the new ROM.

## Out of Scope

- Console-mode UI (no scan trigger exists there).
- Changing the organize behavior of other scan types.
- Non-English locale translations.
