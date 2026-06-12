# Organize Discs Scan Option Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a standalone "Organize discs" scan option that runs only the `.m3u`/subfolder disc-restructure for selected platforms and syncs the DB, with no metadata matching.

**Architecture:** Add a new `ScanType.ORGANIZE` enum member. Reuse the existing scan pipeline: the disc-restructure (`auto_organize_loose_discs`) already runs unconditionally per platform. Two small pure helpers gate behavior — one forces metadata sources empty for ORGANIZE (so `scan_rom` makes no provider calls), one centralizes the "skip metadata phase" short-circuit shared with HASHES. `_should_scan_rom` treats ORGANIZE like QUICK (only new ROMs get added; the new `.m3u` ROM), and the existing `mark_missing_roms` marks the moved-away loose `.cue` ROMs missing.

**Tech Stack:** Python 3.13 / FastAPI / pytest (backend); Vue 3 / TypeScript / vue-i18n (frontend).

---

### Task 1: Add `ORGANIZE` to the `ScanType` enum

**Files:**
- Modify: `backend/handler/scan_handler.py:59-65`
- Test: `backend/tests/endpoints/sockets/test_scan.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/endpoints/sockets/test_scan.py` (top-level, after the imports/`test_scan_stats` area):

```python
def test_organize_scan_type_value():
    """ORGANIZE scan type exists with the string value 'organize'."""
    assert ScanType.ORGANIZE == "organize"
    assert ScanType("organize") is ScanType.ORGANIZE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/endpoints/sockets/test_scan.py::test_organize_scan_type_value -vv`
Expected: FAIL with `AttributeError: ORGANIZE` (member does not exist yet).

- [ ] **Step 3: Add the enum member**

In `backend/handler/scan_handler.py`, the `ScanType` enum currently reads:

```python
@enum.unique
class ScanType(enum.StrEnum):
    NEW_PLATFORMS = "new_platforms"
    QUICK = "quick"
    UPDATE = "update"
    UNMATCHED = "unmatched"
    COMPLETE = "complete"
    HASHES = "hashes"
```

Add the new member after `HASHES`:

```python
@enum.unique
class ScanType(enum.StrEnum):
    NEW_PLATFORMS = "new_platforms"
    QUICK = "quick"
    UPDATE = "update"
    UNMATCHED = "unmatched"
    COMPLETE = "complete"
    HASHES = "hashes"
    ORGANIZE = "organize"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/endpoints/sockets/test_scan.py::test_organize_scan_type_value -vv`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/handler/scan_handler.py backend/tests/endpoints/sockets/test_scan.py
git commit -m "feat(scan): add ORGANIZE scan type"
```

---

### Task 2: `_should_scan_rom` treats ORGANIZE like QUICK (new ROMs only)

**Files:**
- Modify: `backend/endpoints/sockets/scan.py` (the `_should_scan_rom` function, the `should_scan` boolean expression)
- Test: `backend/tests/endpoints/sockets/test_scan.py` (class `TestShouldScanRom`)

- [ ] **Step 1: Write the failing tests**

Add to class `TestShouldScanRom` in `backend/tests/endpoints/sockets/test_scan.py`:

```python
    def test_organize_scan_with_no_rom(self):
        """ORGANIZE should scan (add) when rom is None — the new .m3u entry."""
        result = _should_scan_rom(ScanType.ORGANIZE, None, [], ["igdb"])
        assert result is True

    def test_organize_scan_with_existing_rom(self, rom: Rom):
        """ORGANIZE should not re-scan an existing rom."""
        result = _should_scan_rom(ScanType.ORGANIZE, rom, [], ["igdb"])
        assert result is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest "tests/endpoints/sockets/test_scan.py::TestShouldScanRom" -vv -k organize`
Expected: `test_organize_scan_with_no_rom` FAILS (returns False — ORGANIZE not yet in the new-ROM branch). `test_organize_scan_with_existing_rom` passes incidentally.

- [ ] **Step 3: Add ORGANIZE to the new-ROMs-only branch**

In `backend/endpoints/sockets/scan.py`, inside `_should_scan_rom`, the `should_scan` expression currently begins:

```python
    should_scan = bool(
        # Any new roms should be scanned
        (scan_type in {ScanType.NEW_PLATFORMS, ScanType.QUICK} and not rom)
```

Change that first condition to include ORGANIZE:

```python
    should_scan = bool(
        # Any new roms should be scanned
        (
            scan_type in {ScanType.NEW_PLATFORMS, ScanType.QUICK, ScanType.ORGANIZE}
            and not rom
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest "tests/endpoints/sockets/test_scan.py::TestShouldScanRom" -vv`
Expected: all PASS, including both new ORGANIZE tests.

- [ ] **Step 5: Commit**

```bash
git add backend/endpoints/sockets/scan.py backend/tests/endpoints/sockets/test_scan.py
git commit -m "feat(scan): ORGANIZE adds new .m3u rom like QUICK"
```

---

### Task 3: `_metadata_sources_for_scan_type` helper — force empty sources for ORGANIZE

This pure helper is the testable seam for "ORGANIZE makes no provider calls". `scan_rom`'s metadata gates all require `SOURCE in metadata_sources`; an empty list disables every one of them, even for the newly-added `.m3u` ROM (`newly_added=True`).

**Files:**
- Modify: `backend/endpoints/sockets/scan.py` (add helper after `_should_scan_rom`; call it inside `scan_platforms`)
- Test: `backend/tests/endpoints/sockets/test_scan.py`

- [ ] **Step 1: Write the failing tests**

Add the helper to the import on line 6 of `backend/tests/endpoints/sockets/test_scan.py`:

```python
from endpoints.sockets.scan import (
    ScanStats,
    _metadata_sources_for_scan_type,
    _should_scan_rom,
)
```

Add a new test class at the end of the file:

```python
class TestMetadataSourcesForScanType:
    def test_organize_clears_sources(self):
        """ORGANIZE drops all metadata sources so no providers are queried."""
        assert _metadata_sources_for_scan_type(ScanType.ORGANIZE, ["igdb", "ss"]) == []

    def test_other_scan_types_keep_sources(self):
        """Non-ORGANIZE scans keep the provided sources unchanged."""
        for scan_type in (
            ScanType.NEW_PLATFORMS,
            ScanType.QUICK,
            ScanType.UPDATE,
            ScanType.UNMATCHED,
            ScanType.COMPLETE,
            ScanType.HASHES,
        ):
            assert _metadata_sources_for_scan_type(scan_type, ["igdb"]) == ["igdb"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest "tests/endpoints/sockets/test_scan.py::TestMetadataSourcesForScanType" -vv`
Expected: FAIL at import / collection — `ImportError: cannot import name '_metadata_sources_for_scan_type'`.

- [ ] **Step 3: Add the helper**

In `backend/endpoints/sockets/scan.py`, add this function immediately after `_should_scan_rom` (before `_should_get_rom_files`):

```python
def _metadata_sources_for_scan_type(
    scan_type: ScanType,
    metadata_sources: list[str],
) -> list[str]:
    """Return the metadata sources that apply for a given scan type.

    ORGANIZE only restructures discs and syncs the DB, so it must not query
    any external provider. Every metadata gate in ``scan_rom`` requires the
    source to be present in ``metadata_sources``, so returning an empty list
    fully disables metadata fetching.
    """
    if scan_type == ScanType.ORGANIZE:
        return []
    return metadata_sources
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest "tests/endpoints/sockets/test_scan.py::TestMetadataSourcesForScanType" -vv`
Expected: all PASS.

- [ ] **Step 5: Wire the helper into `scan_platforms`**

In `backend/endpoints/sockets/scan.py`, `scan_platforms` begins:

```python
    if not roms_ids:
        roms_ids = []

    socket_manager = _get_socket_manager()
    scan_stats = ScanStats()
```

Insert the metadata-source normalization right after the `roms_ids` guard:

```python
    if not roms_ids:
        roms_ids = []

    # ORGANIZE only restructures discs + syncs the DB; never query providers.
    metadata_sources = _metadata_sources_for_scan_type(scan_type, metadata_sources)

    socket_manager = _get_socket_manager()
    scan_stats = ScanStats()
```

- [ ] **Step 6: Run the full scan test suite to verify nothing regressed**

Run: `cd backend && uv run pytest tests/endpoints/sockets/test_scan.py -vv`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/endpoints/sockets/scan.py backend/tests/endpoints/sockets/test_scan.py
git commit -m "feat(scan): ORGANIZE forces empty metadata sources"
```

---

### Task 4: `_skip_metadata_phase` helper — short-circuit cover/media for ORGANIZE

The existing short-circuit in `_identify_rom` is `if scan_type == ScanType.HASHES: return`. Replace the magic comparison with a shared predicate so HASHES and ORGANIZE both skip the cover/screenshot/media phase, and the rule is unit-testable.

**Files:**
- Modify: `backend/endpoints/sockets/scan.py` (add helper near the other gate helpers; replace the short-circuit condition in `_identify_rom`)
- Test: `backend/tests/endpoints/sockets/test_scan.py`

- [ ] **Step 1: Write the failing tests**

Extend the import in `backend/tests/endpoints/sockets/test_scan.py` to add `_skip_metadata_phase`:

```python
from endpoints.sockets.scan import (
    ScanStats,
    _metadata_sources_for_scan_type,
    _should_scan_rom,
    _skip_metadata_phase,
)
```

Add a new test class at the end of the file:

```python
class TestSkipMetadataPhase:
    def test_organize_and_hashes_skip(self):
        """ORGANIZE and HASHES skip the metadata/cover phase."""
        assert _skip_metadata_phase(ScanType.ORGANIZE) is True
        assert _skip_metadata_phase(ScanType.HASHES) is True

    def test_metadata_scan_types_do_not_skip(self):
        """Metadata-fetching scans run the full phase."""
        for scan_type in (
            ScanType.NEW_PLATFORMS,
            ScanType.QUICK,
            ScanType.UPDATE,
            ScanType.UNMATCHED,
            ScanType.COMPLETE,
        ):
            assert _skip_metadata_phase(scan_type) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest "tests/endpoints/sockets/test_scan.py::TestSkipMetadataPhase" -vv`
Expected: FAIL at import / collection — `ImportError: cannot import name '_skip_metadata_phase'`.

- [ ] **Step 3: Add the helper**

In `backend/endpoints/sockets/scan.py`, add this function next to `_metadata_sources_for_scan_type` (after `_should_scan_rom`):

```python
def _skip_metadata_phase(scan_type: ScanType) -> bool:
    """Whether to skip cover/screenshot/media fetching after a rom is persisted.

    HASHES and ORGANIZE both update the DB entry (and its files) without doing
    any metadata work, so they return early before the resource-download phase.
    """
    return scan_type in {ScanType.HASHES, ScanType.ORGANIZE}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest "tests/endpoints/sockets/test_scan.py::TestSkipMetadataPhase" -vv`
Expected: all PASS.

- [ ] **Step 5: Replace the short-circuit in `_identify_rom`**

In `backend/endpoints/sockets/scan.py`, inside `_identify_rom`, find:

```python
    # Short circuit if the scan type is hashes
    if scan_type == ScanType.HASHES:
        return
```

Replace with:

```python
    # Short circuit for scans that don't fetch metadata (hashes, organize)
    if _skip_metadata_phase(scan_type):
        return
```

- [ ] **Step 6: Run the full scan test suite to verify nothing regressed**

Run: `cd backend && uv run pytest tests/endpoints/sockets/test_scan.py -vv`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/endpoints/sockets/scan.py backend/tests/endpoints/sockets/test_scan.py
git commit -m "feat(scan): ORGANIZE skips metadata/cover phase like HASHES"
```

---

### Task 5: Backend regression sweep

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend scan-related suites**

Run:
```bash
cd backend && uv run pytest tests/endpoints/sockets/test_scan.py tests/tasks/test_scan_library.py tests/handler/filesystem/test_roms_handler.py -vv
```
Expected: all PASS. (Confirms the new enum member and helpers did not break `scan_library` task assertions or the disc-organize tests.)

- [ ] **Step 2: Lint**

Run: `trunk check --filter=ruff backend/handler/scan_handler.py backend/endpoints/sockets/scan.py`
Expected: no findings. (If `trunk` is unavailable, run `cd backend && uv run ruff check handler/scan_handler.py endpoints/sockets/scan.py`.)

---

### Task 6: Frontend — add the "Organize discs" scan option

**Files:**
- Modify: `frontend/src/views/Scan.vue` (the `scanOptions` array, around lines 105-136)
- Modify: `frontend/src/locales/en_US/scan.json`

- [ ] **Step 1: Add the i18n strings**

In `frontend/src/locales/en_US/scan.json`, add two keys in alphabetical position (between the `hashes-*` group and `quick-scan`):

```json
  "organize-discs": "Organize discs",
  "organize-discs-desc": "Restructure loose multi-disc games into .m3u format for selected platforms (no metadata matching)",
```

- [ ] **Step 2: Mention the option in the scan-types info tooltip**

In the same file, the `scan-types-info` string ends with the `<strong>Complete Rescan:</strong> ...` clause. Append a new clause before the closing quote, immediately after the Recalculate Hashes clause and before the Complete Rescan clause. Locate this substring inside `scan-types-info`:

```
<strong>Recalculate Hashes:</strong> Recalculates hashes for all files in the selected platforms.<br><br><strong>Complete Rescan:</strong>
```

Replace it with:

```
<strong>Recalculate Hashes:</strong> Recalculates hashes for all files in the selected platforms.<br><br><strong>Organize Discs:</strong> Restructures loose multi-disc games (multiple .cue files of the same game) into a single .m3u entry with a subfolder, without fetching any metadata.<br><br><strong>Complete Rescan:</strong>
```

- [ ] **Step 3: Add the option to the `scanOptions` array**

In `frontend/src/views/Scan.vue`, the `scanOptions` array currently lists the hashes option then the complete-rescan option:

```js
  {
    title: t("scan.hashes"),
    subtitle: t("scan.hashes-desc"),
    value: "hashes",
  },
  {
    title: t("scan.complete-rescan"),
    subtitle: t("scan.complete-rescan-desc"),
    value: "complete",
  },
];
```

Insert the new option between `hashes` and `complete`:

```js
  {
    title: t("scan.hashes"),
    subtitle: t("scan.hashes-desc"),
    value: "hashes",
  },
  {
    title: t("scan.organize-discs"),
    subtitle: t("scan.organize-discs-desc"),
    value: "organize",
  },
  {
    title: t("scan.complete-rescan"),
    subtitle: t("scan.complete-rescan-desc"),
    value: "complete",
  },
];
```

- [ ] **Step 4: Typecheck and lint**

Run:
```bash
cd frontend && npm run typecheck && npm run lint
```
Expected: both pass with no new errors.

- [ ] **Step 5: Build to confirm the locale JSON is valid**

Run: `cd frontend && npm run build`
Expected: build succeeds (catches malformed JSON in `scan.json`).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/views/Scan.vue frontend/src/locales/en_US/scan.json
git commit -m "feat(scan): add Organize discs option to Scan page"
```

---

### Task 7: Manual end-to-end verification

**Files:** none (manual verification)

- [ ] **Step 1: Prepare test data**

In a dev library, create a platform folder containing a loose multi-disc set, e.g.:
```
psx/Final Fantasy VII (USA) (Disc 1).cue
psx/Final Fantasy VII (USA) (Disc 1).bin
psx/Final Fantasy VII (USA) (Disc 2).cue
psx/Final Fantasy VII (USA) (Disc 2).bin
```
Run a Quick scan first if needed so the loose `.cue` ROMs exist in the DB (to confirm they get marked missing).

- [ ] **Step 2: Run the Organize scan**

In the web UI Scan page: select the `psx` platform, choose scan option "Organize discs", start the scan.

- [ ] **Step 3: Verify the outcome**

Confirm:
- On disk: `psx/Final Fantasy VII (USA).m3u` exists plus a `psx/Final Fantasy VII (USA)/` subfolder containing the disc files.
- In the library: a single `Final Fantasy VII (USA).m3u` ROM is present; the two loose `.cue` ROMs are gone/marked missing.
- The new ROM has no metadata IDs (igdb_id, ss_id, etc. are null) and no cover — confirming no provider calls were made.
- Re-running "Organize discs" on the same platform is a no-op (idempotent; no duplicate `.m3u`).

---

## Notes for the implementer

- The disc-restructure itself (`auto_organize_loose_discs`) and the `mark_missing_roms` reconciliation already run on every scan in `_identify_platform` — no change is needed there; ORGANIZE simply rides on them.
- `_should_get_rom_files` is intentionally left unchanged: its existing `newly_added` branch already builds + hashes the new `.m3u` ROM's files, respecting the global `SKIP_HASH_CALCULATION` config — exactly the desired hashing behavior.
- Only the English (`en_US`) locale is in scope. Other locales fall back to English for the new keys.
