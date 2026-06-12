# Scan "Organize discs" — frontend feedback

**Date:** 2026-06-12
**Status:** Approved design, ready for implementation plan
**Type:** Feature (current behavior is correct; it only lacks user-facing feedback)

## Problem

When a user runs the **Organize discs** scan (`ScanType.ORGANIZE`), the scan results UI
often shows an empty list / "0 games" and the generic "Scan completed" toast, giving
no indication that the filesystem reorganization actually happened.

Root cause (verified):

- The scan results list is built **entirely** from `scan:scanning_rom` socket events.
  `ScanBtn.vue` pushes each emitted rom into `scanningPlatforms[].roms`. No emit → not listed.
- `HASHES` lists every rom because `_should_scan_rom` returns `True` for all roms on a
  hashes scan, so every rom is emitted.
- `ORGANIZE` only emits **new** roms (`_should_scan_rom` returns `True` for ORGANIZE only
  when `rom is None`). So only newly-created `.m3u` entries surface.
- The actual disc reorganization happens in
  `FSRomsHandler.auto_organize_loose_discs(platform)` (called unconditionally at
  `endpoints/sockets/scan.py:606` on **every** scan). It returns only an `int` count and
  never reports **which** games were reorganized.
- "0 games" occurs when reorganization already happened on a prior scan: nothing new is
  created → nothing is emitted → empty list, generic toast.

## Decisions (locked with user)

1. **What to list:** only the games reorganized *this run*. When nothing needs
   reorganizing, show a clear empty state instead of a silent 0.
2. **Visual marking:** reorganized games appear as **plain rom entries** (no special
   badge/component) — consistent with the existing scan UI.
3. **Empty state:** a distinct snackbar message when an organize scan reorganizes nothing.
4. **Standard scans too:** when any scan reorganizes games, surface a distinct organize
   snackbar **in addition to** the usual "Scan completed" toast.
5. **Snackbar delivery:** `Notification.vue` currently shows one snackbar at a time (a
   second emit overwrites the first). Add a **queue** so the usual toast and the organize
   toast appear sequentially.

## Snackbar matrix

All organize messaging is emitted as a **second** `snackbarShow` after the usual success
toast; the new queue renders them one after another.

| Scan type | `organized_roms` | Toasts shown |
|-----------|------------------|--------------|
| any       | `> 0`            | "Scan completed successfully!" → "Organized N game(s) into M3U structure" |
| organize  | `== 0`           | "Scan completed successfully!" → "Organize complete — no discs needed organizing" |
| standard  | `== 0`           | "Scan completed successfully!" only |

## Design

### Backend

**1. `handler/filesystem/roms_handler.py` — `auto_organize_loose_discs`**
- Change return type `int` → `list[str]` of the reorganized rom **fs_names**
  (`base_name`, i.e. the resulting multi-disc rom directory name).
- At each `organized += 1` site (pass-1 loose `.cue` grouping and pass-2 pre-existing
  subdirectory), append `base_name` / `dir_name` to a list instead of incrementing a
  counter. Return the list.
- Update docstring ("Returns the fs_names of games reorganized.").

**2. `endpoints/sockets/scan.py` — `ScanStats`**
- Add field `organized_roms: int = 0`.
- Add `"organized_roms"` to `to_dict()`. This automatically plumbs through the existing
  `scan:update_stats` and `scan:done` emits.

**3. `endpoints/sockets/scan.py` — `_identify_platform`**
- `organized = await fs_rom_handler.auto_organize_loose_discs(platform)` is now a list.
- Keep the existing log line, using `len(organized)`.
- `await scan_stats.increment(socket_manager=..., organized_roms=len(organized))`.
- **After** the rom scan loop, fetch the reorganized roms by fs_name
  (`db_rom_handler.get_roms_by_fs_name(platform_id=platform.id, fs_names=set(organized))`)
  and call `_emit_scanning_rom` for each. This guarantees every reorganized game is
  listed — including pass-2 games whose rom already existed in the DB and would otherwise
  be skipped. The frontend already dedupes by `rom.id`, so re-emitting a game that the
  natural new-rom path also emitted is harmless.

> Note: `organized_roms` accumulates on *every* scan type (organize runs on all scans);
> only the snackbar branching distinguishes organize scans. This is intentional.

### Frontend

**4. `__generated__` ScanStats type**
- Regenerate from backend OpenAPI (`npm run generate`) after the schema change, or
  hand-add `organized_roms: number`.

**5. `stores/scanning.ts` + `views/Scan.vue`**
- Add `scanType: string` to the scanning store state with a setter.
- In `Scan.vue`'s `scan()`, store the active `scanType` in the store before emitting, so
  the `scan:done` handler can branch on it.

**6. `components/common/Notifications/Notification.vue` — snackbar queue**
- Replace the single `show`/`snackbarStatus` model with a queue (array of
  `SnackbarStatus`).
- On `snackbarShow`, push to the queue; if nothing is currently showing, display the
  front item.
- On timeout/close, remove the front item and advance to the next (if any). Preserve the
  existing `notificationStore` id assignment and removal behavior.
- Keep the single `v-snackbar` element; it renders the current front item.

**7. `components/common/Navigation/ScanBtn.vue` — `scan:done` handler**
- Keep the existing "Scan completed successfully!" snackbar.
- Read `scanType` from the scanning store and `organized_roms` from `scanStats`.
- If `organized_roms > 0`: emit a second snackbar "Organized N game(s) into M3U
  structure" (icon `mdi-disc`, green).
- Else if `scanType === 'organize'`: emit a second snackbar "Organize complete — no discs
  needed organizing" (icon `mdi-check-bold` or `mdi-disc`).
- Else: no second snackbar.

**8. i18n**
- Add keys to `locales/en_US/scan.json` (and at minimum leave other locales to fall back):
  - `scan.organized-summary` — "Organized {n} game(s) into M3U structure"
  - `scan.organize-none` — "Organize complete — no discs needed organizing"
- Use `t(...)` in `ScanBtn.vue` for the new messages (the existing success message is
  currently a hardcoded English string; out of scope to change).

## Testing

- **Backend:** update the ~10 `auto_organize_loose_discs` assertions in
  `tests/handler/filesystem/test_roms_handler.py` from `result == N` to `len(result) == N`
  (and assert returned fs_names where useful).
- **Backend:** add a scan test asserting that an organize run emits `scan:scanning_rom`
  for reorganized games and that `ScanStats.organized_roms` is set.
- **Frontend:** `npm run typecheck`; manual check that two snackbars queue in sequence and
  the organize message renders for both the `> 0` and organize-`== 0` cases.

## Out of scope

- No badge/visual differentiation of reorganized roms (plain entries, per decision).
- No change to *when* `auto_organize_loose_discs` runs (still every scan).
- No i18n of the pre-existing hardcoded "Scan completed successfully!" string.
