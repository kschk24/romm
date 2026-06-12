# Organize Discs Scan Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the user clear visual feedback when an "Organize discs" scan reorganizes (or doesn't reorganize) multi-disc games, by listing reorganized games and showing distinct snackbars.

**Architecture:** `auto_organize_loose_discs` returns the fs_names of games it reorganized instead of a bare count. The scan loop re-emits `scan:scanning_rom` for those games so they always list, and counts them in a new `organized_roms` stat. The frontend gains a snackbar queue so a distinct "organized" toast can follow the usual "scan completed" toast.

**Tech Stack:** FastAPI + SQLAlchemy + Socket.IO (backend), Vue 3 + Pinia + Vuetify + vue-i18n (frontend), pytest (backend tests). The frontend has no unit-test framework — frontend tasks verify via `npm run typecheck` + `npm run lint` + manual check.

**Reference spec:** `docs/superpowers/specs/2026-06-12-scan-organize-feedback-design.md`

---

## File Structure

**Backend (modify):**
- `backend/handler/filesystem/roms_handler.py` — `auto_organize_loose_discs` returns `list[str]`
- `backend/endpoints/responses/__init__.py` — add `organized_roms` to `ScanStats` TypedDict (drives generated TS)
- `backend/endpoints/sockets/scan.py` — add `organized_roms` to `ScanStats` dataclass; add `_emit_reorganized_roms` helper; wire into `_identify_platform`

**Backend (tests):**
- `backend/tests/handler/filesystem/test_roms_handler.py` — update 9 `auto_organize` assertions
- `backend/tests/endpoints/sockets/test_scan.py` — extend `test_scan_stats`; add `TestEmitReorganizedRoms`

**Frontend (modify):**
- `frontend/src/__generated__/models/ScanStats.ts` — add `organized_roms: number`
- `frontend/src/stores/scanning.ts` — add `scanType` state + setter
- `frontend/src/views/Scan.vue` — call `setScanType` on scan start
- `frontend/src/components/common/Notifications/Notification.vue` — snackbar queue
- `frontend/src/components/common/Navigation/ScanBtn.vue` — second snackbar in `scan:done`
- `frontend/src/locales/en_US/scan.json` — two new i18n keys

---

## Task 1: `auto_organize_loose_discs` returns reorganized fs_names

**Files:**
- Modify: `backend/handler/filesystem/roms_handler.py:702-820`
- Test: `backend/tests/handler/filesystem/test_roms_handler.py` (9 assertions across the `auto_organize_loose_discs` block, lines ~1236–1444)

- [ ] **Step 1: Update the tests to expect a list of fs_names**

In `backend/tests/handler/filesystem/test_roms_handler.py`, change these assertions:

- In `test_auto_organize_platform_path_not_found` (line ~1236): `assert result == 0` → `assert result == []`
- In `test_auto_organize_no_cue_files` (line ~1250): `assert result == 0` → `assert result == []`
- In `test_auto_organize_single_disc` (line ~1265): `assert result >= 1` → `assert result == ["Silent Hill"]`
- In `test_auto_organize_multi_disc` (line ~1290): `assert result >= 1` → `assert result == ["Final Fantasy VII"]`
- In `test_auto_organize_strips_rev_and_region` (line ~1322, the "Exactly one game organized" test): `assert result == 1` → `assert result == ["Metal Gear Solid (USA) (Rev 1)"]`
- In `test_auto_organize_idempotent_m3u_exists` (line ~1349): `assert result == 0` → `assert result == []`
- In `test_auto_organize_creates_m3u_for_pre_organized_subdir` (line ~1407): `assert result == 1` → `assert result == ["Metal Gear Solid (USA)"]`
- In `test_auto_organize_skips_subdir_with_existing_m3u` (line ~1429): `assert result == 0` → `assert result == []`
- In `test_auto_organize_subdir_no_cue_files_skipped` (line ~1444): `assert result == 0` → `assert result == []`

(`test_auto_organize_idempotent_dir_exists` at line ~1349 region also has `assert result == 0` → `assert result == []`. There are two `idempotent` tests — update the `result == 0` in both.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/handler/filesystem/test_roms_handler.py -k auto_organize -vv`
Expected: FAIL — assertions compare `int` (current return) against `list`, e.g. `assert 0 == []`.

- [ ] **Step 3: Change the implementation to return a list of fs_names**

In `backend/handler/filesystem/roms_handler.py`:

Update the early-return on missing path (line ~718) from `return 0` to `return []`.

Update the docstring line (line ~711) from:
```python
        Returns the number of games reorganized.
```
to:
```python
        Returns the fs_names (directory names) of the games reorganized this run.
```

Change the accumulator (line ~777) from:
```python
        organized = 0
```
to:
```python
        organized: list[str] = []
```

In the pass-1 loop, replace (line ~796):
```python
            organized += 1
```
with:
```python
            organized.append(base_name)
```

In the pass-2 loop, replace (line ~818):
```python
                organized += 1
```
with:
```python
                organized.append(dir_name)
```

The final `return organized` (line ~820) is unchanged (now returns the list).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/handler/filesystem/test_roms_handler.py -k auto_organize -vv`
Expected: PASS (all `auto_organize` tests green).

- [ ] **Step 5: Commit**

```bash
git add backend/handler/filesystem/roms_handler.py backend/tests/handler/filesystem/test_roms_handler.py
git commit -m "refactor(scan): auto_organize_loose_discs returns reorganized fs_names

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Add `organized_roms` to both ScanStats definitions

**Files:**
- Modify: `backend/endpoints/responses/__init__.py:8-18` (TypedDict — drives generated TS)
- Modify: `backend/endpoints/sockets/scan.py:60-108` (dataclass + `to_dict`)
- Test: `backend/tests/endpoints/sockets/test_scan.py:22-49` (`test_scan_stats`)

- [ ] **Step 1: Extend `test_scan_stats` to cover the new field**

In `backend/tests/endpoints/sockets/test_scan.py`, in `test_scan_stats` (line ~22), add an assertion in the initial block (after `assert stats.new_firmware == 0`):
```python
    assert stats.organized_roms == 0
    assert "organized_roms" in stats.to_dict()
```
Add an increment in the mutation block (after `stats.new_firmware += 1`):
```python
    stats.organized_roms += 1
```
Add a final assertion (after `assert stats.new_firmware == 1`):
```python
    assert stats.organized_roms == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/endpoints/sockets/test_scan.py::test_scan_stats -vv`
Expected: FAIL with `AttributeError: 'ScanStats' object has no attribute 'organized_roms'`.

- [ ] **Step 3: Add the field to the dataclass and `to_dict`**

In `backend/endpoints/sockets/scan.py`, in the `ScanStats` dataclass (line ~60-71), add the field after `new_firmware: int = 0`:
```python
    organized_roms: int = 0
```

In `to_dict` (line ~96-108), add the key before the closing brace (after `"new_firmware": self.new_firmware,`):
```python
            "organized_roms": self.organized_roms,
```

- [ ] **Step 4: Add the field to the response TypedDict**

In `backend/endpoints/responses/__init__.py`, in the `ScanStats` TypedDict (line ~8-18), add after `new_firmware: int`:
```python
    organized_roms: int
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd backend && uv run pytest tests/endpoints/sockets/test_scan.py::test_scan_stats -vv`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/endpoints/sockets/scan.py backend/endpoints/responses/__init__.py backend/tests/endpoints/sockets/test_scan.py
git commit -m "feat(scan): add organized_roms stat to ScanStats

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Emit reorganized roms + count them in `_identify_platform`

**Files:**
- Modify: `backend/endpoints/sockets/scan.py` (add `_emit_reorganized_roms` helper after `_emit_scanning_rom` ~line 252; wire into `_identify_platform` at ~line 606 and before its `return scan_stats` ~line 699)
- Test: `backend/tests/endpoints/sockets/test_scan.py` (add `TestEmitReorganizedRoms` class)

- [ ] **Step 1: Write the failing test for the helper**

In `backend/tests/endpoints/sockets/test_scan.py`, append a new test class at the end of the file:
```python
class TestEmitReorganizedRoms:
    """``_emit_reorganized_roms`` re-emits scan:scanning_rom for games that
    ``auto_organize_loose_discs`` reorganized this run, and counts them.
    """

    async def test_emits_and_increments_for_organized_roms(self, mocker):
        rom = Mock()
        mocker.patch.object(
            scan_module.db_rom_handler,
            "get_roms_by_fs_name",
            return_value={"Game": rom},
        )
        emit_mock = mocker.patch.object(
            scan_module, "_emit_scanning_rom", new=AsyncMock()
        )
        socket_manager = AsyncMock()
        scan_stats = ScanStats()

        await scan_module._emit_reorganized_roms(
            socket_manager=socket_manager,
            platform=Mock(id=1),
            organized_fs_names=["Game"],
            scan_stats=scan_stats,
        )

        assert scan_stats.organized_roms == 1
        emit_mock.assert_awaited_once_with(socket_manager, rom)

    async def test_noop_for_empty_list(self, mocker):
        get_mock = mocker.patch.object(
            scan_module.db_rom_handler, "get_roms_by_fs_name"
        )
        socket_manager = AsyncMock()
        scan_stats = ScanStats()

        await scan_module._emit_reorganized_roms(
            socket_manager=socket_manager,
            platform=Mock(id=1),
            organized_fs_names=[],
            scan_stats=scan_stats,
        )

        assert scan_stats.organized_roms == 0
        get_mock.assert_not_called()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/endpoints/sockets/test_scan.py::TestEmitReorganizedRoms -vv`
Expected: FAIL with `AttributeError: module 'endpoints.sockets.scan' has no attribute '_emit_reorganized_roms'`.

- [ ] **Step 3: Add the helper**

In `backend/endpoints/sockets/scan.py`, add this function immediately after `_emit_scanning_rom` (which ends ~line 252, before `_should_get_rom_files`):
```python
async def _emit_reorganized_roms(
    socket_manager: socketio.AsyncRedisManager,
    platform: Platform,
    organized_fs_names: list[str],
    scan_stats: ScanStats,
) -> None:
    """Surface games reorganized by ``auto_organize_loose_discs`` this run.

    The scan results UI is driven solely by ``scan:scanning_rom`` events. New
    ``.m3u`` roms are emitted by the normal scan loop, but games whose rom row
    already existed (e.g. a pre-existing folder that only gained a new ``.m3u``)
    are skipped and never emitted. Re-emit every reorganized rom here so they
    all appear; the frontend dedupes by ``rom.id`` so re-emitting is harmless.
    """
    if not organized_fs_names:
        return

    await scan_stats.increment(
        socket_manager=socket_manager,
        organized_roms=len(organized_fs_names),
    )

    roms_by_fs_name = db_rom_handler.get_roms_by_fs_name(
        platform_id=platform.id,
        fs_names=set(organized_fs_names),
    )
    for rom in roms_by_fs_name.values():
        await _emit_scanning_rom(socket_manager, rom)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && uv run pytest tests/endpoints/sockets/test_scan.py::TestEmitReorganizedRoms -vv`
Expected: PASS (both tests).

- [ ] **Step 5: Wire the helper into `_identify_platform`**

In `backend/endpoints/sockets/scan.py`, in `_identify_platform`, update the organize block (line ~606-608) from:
```python
    organized = await fs_rom_handler.auto_organize_loose_discs(platform)
    if organized:
        log.info(f"Auto-organized {hl(str(organized))} game(s) into M3U structure")
```
to:
```python
    organized = await fs_rom_handler.auto_organize_loose_discs(platform)
    if organized:
        log.info(
            f"Auto-organized {hl(str(len(organized)))} game(s) into M3U structure"
        )
```

Then, at the end of `_identify_platform`, replace the final `return scan_stats` (line ~699) with:
```python
    await _emit_reorganized_roms(
        socket_manager=socket_manager,
        platform=platform,
        organized_fs_names=organized,
        scan_stats=scan_stats,
    )

    return scan_stats
```
(Leave the earlier `return scan_stats` inside the `RomsNotFoundException` handler unchanged — if no roms were found there is nothing in the DB to re-emit.)

- [ ] **Step 6: Run the scan socket tests to verify nothing regressed**

Run: `cd backend && uv run pytest tests/endpoints/sockets/test_scan.py -vv`
Expected: PASS (all tests in the file).

- [ ] **Step 7: Commit**

```bash
git add backend/endpoints/sockets/scan.py backend/tests/endpoints/sockets/test_scan.py
git commit -m "feat(scan): re-emit reorganized roms so organize scans list games

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Add `organized_roms` to the generated frontend ScanStats type

**Files:**
- Modify: `frontend/src/__generated__/models/ScanStats.ts`

> The canonical way is `npm run generate` (requires the backend running). If the backend isn't available, hand-edit the file as below; the field must match the backend TypedDict from Task 2.

- [ ] **Step 1: Add the field**

In `frontend/src/__generated__/models/ScanStats.ts`, add inside the type (after `new_firmware: number;`):
```typescript
    organized_roms: number;
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: PASS (no type errors).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/__generated__/models/ScanStats.ts
git commit -m "chore(frontend): add organized_roms to generated ScanStats type

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Track active scanType in the scanning store

**Files:**
- Modify: `frontend/src/stores/scanning.ts`
- Modify: `frontend/src/views/Scan.vue:144-159` (`scan()` function)

- [ ] **Step 1: Add `scanType` state + setter to the store**

In `frontend/src/stores/scanning.ts`, add `scanType` to state (after `scanStats: {} as ScanStats,`):
```typescript
    scanType: "quick",
```
Add a setter action (after `setScanStats`):
```typescript
    setScanType(scanType: string) {
      this.scanType = scanType;
    },
```
In `reset()`, add (after `this.scanning = false;`):
```typescript
      this.scanType = "quick";
```

- [ ] **Step 2: Store the scanType when a scan starts**

In `frontend/src/views/Scan.vue`, in `scan()` (line ~144), add after `scanningStore.setScanning(true);`:
```typescript
  scanningStore.setScanType(scanType.value);
```

- [ ] **Step 3: Typecheck + lint**

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/stores/scanning.ts frontend/src/views/Scan.vue
git commit -m "feat(frontend): track active scanType in scanning store

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Add a snackbar queue to Notification.vue

**Files:**
- Modify: `frontend/src/components/common/Notifications/Notification.vue:1-25` (script block)

The current component shows one snackbar at a time; a second `snackbarShow` emit overwrites the first. Replace the script block so snackbars queue and display sequentially.

- [ ] **Step 1: Replace the `<script setup>` block**

In `frontend/src/components/common/Notifications/Notification.vue`, replace the entire `<script setup lang="ts"> ... </script>` block (lines 1-25) with:
```vue
<script setup lang="ts">
import type { Emitter } from "mitt";
import { inject, ref } from "vue";
import { useDisplay } from "vuetify";
import storeNotifications from "@/stores/notifications";
import type { Events, SnackbarStatus } from "@/types/emitter";

const show = ref(false);
const { xs } = useDisplay();
const snackbarStatus = ref<SnackbarStatus>({ msg: "" });
const queue = ref<SnackbarStatus[]>([]);
const notificationStore = storeNotifications();

// Event listeners bus
const emitter = inject<Emitter<Events>>("emitter");
emitter?.on("snackbarShow", (snackbar: SnackbarStatus) => {
  queue.value.push(snackbar);
  if (!show.value) showNext();
});

function showNext() {
  const next = queue.value.shift();
  if (!next) return;
  snackbarStatus.value = next;
  snackbarStatus.value.id = notificationStore.notifications.length + 1;
  show.value = true;
}

function closeDialog() {
  notificationStore.remove(snackbarStatus.value.id);
  show.value = false;
  // Advance to the next queued snackbar after the close transition.
  if (queue.value.length > 0) {
    setTimeout(showNext, 300);
  }
}
</script>
```

The `<template>` block is unchanged — it already binds `show`, `snackbarStatus`, and calls `closeDialog` on `@timeout` and the close button.

- [ ] **Step 2: Typecheck + lint**

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/common/Notifications/Notification.vue
git commit -m "feat(frontend): queue snackbars so they show sequentially

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Emit the organize snackbar on scan completion + i18n

**Files:**
- Modify: `frontend/src/locales/en_US/scan.json`
- Modify: `frontend/src/components/common/Navigation/ScanBtn.vue:125-136` (`scan:done` handler)

- [ ] **Step 1: Add the i18n keys**

In `frontend/src/locales/en_US/scan.json`, add these two keys (keep alphabetical-ish order, e.g. after `"not-identified"` and before `"organize-discs"`):
```json
  "organize-none": "Organize complete — no discs needed organizing",
  "organized-summary": "Organized {n} game(s) into M3U structure",
```

- [ ] **Step 2: Emit the second snackbar in the `scan:done` handler**

In `frontend/src/components/common/Navigation/ScanBtn.vue`, replace the `scan:done` handler (lines ~125-136) with:
```typescript
socket.on("scan:done", () => {
  scanningStore.setScanning(false);
  socket.disconnect();

  emitter?.emit("refreshDrawer", null);
  emitter?.emit("snackbarShow", {
    msg: "Scan completed successfully!",
    icon: "mdi-check-bold",
    color: "green",
    timeout: 4000,
  });

  const organizedCount = scanningStore.scanStats.organized_roms ?? 0;
  if (organizedCount > 0) {
    emitter?.emit("snackbarShow", {
      msg: t("scan.organized-summary", { n: organizedCount }),
      icon: "mdi-disc",
      color: "green",
      timeout: 4000,
    });
  } else if (scanningStore.scanType === "organize") {
    emitter?.emit("snackbarShow", {
      msg: t("scan.organize-none"),
      icon: "mdi-disc",
      color: "green",
      timeout: 4000,
    });
  }
});
```
(`scanningStore` and `t` are already in scope in this component. `scanStats` and `scanType` are read directly off the store instance here rather than via the destructured refs.)

- [ ] **Step 3: Typecheck + lint**

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/locales/en_US/scan.json frontend/src/components/common/Navigation/ScanBtn.vue
git commit -m "feat(frontend): show organize feedback snackbar after scan

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: Full verification

- [ ] **Step 1: Backend test suite (scan-related)**

Run: `cd backend && uv run pytest tests/handler/filesystem/test_roms_handler.py tests/endpoints/sockets/test_scan.py -vv`
Expected: PASS.

- [ ] **Step 2: Backend lint/format**

Run: `trunk check --filter=ruff,mypy backend/endpoints/sockets/scan.py backend/handler/filesystem/roms_handler.py backend/endpoints/responses/__init__.py`
Expected: PASS (or no new findings). If `trunk` is unavailable, run `cd backend && uv run ruff check endpoints/sockets/scan.py handler/filesystem/roms_handler.py`.

- [ ] **Step 3: Frontend typecheck + lint**

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: PASS.

- [ ] **Step 4: Manual smoke check (DEV_MODE)**

With the dev stack running (`docker compose up -d`, backend on :5000, Vite on :3000):
1. Put two loose `.cue` discs of one game in a platform folder (e.g. `Game (Disc 1).cue`, `Game (Disc 2).cue`).
2. Run an **Organize discs** scan for that platform. Verify the game lists in the results panel AND two snackbars appear in sequence: "Scan completed successfully!" then "Organized 1 game(s) into M3U structure".
3. Run **Organize discs** again (now already organized). Verify the second snackbar reads "Organize complete — no discs needed organizing".
4. Run a **Quick scan** on an already-organized platform. Verify only the usual "Scan completed" snackbar appears (no organize toast).

Expected: behavior matches the snackbar matrix in the spec.

---

## Self-Review Notes

- **Spec coverage:** list reorganized games (Task 1+3), `organized_roms` stat (Task 2+4), plain rom entries / no badge (no task needed — reuses existing panels), distinct empty-state snackbar (Task 7), organize snackbar on standard scans (Task 7), snackbar queue (Task 6), scanType tracking (Task 5). All spec sections covered.
- **Type consistency:** `auto_organize_loose_discs -> list[str]` consumed via `len(...)` (log) and `set(...)` (helper). `organized_roms: int` added to both `ScanStats` definitions + generated TS. `_emit_reorganized_roms` signature matches its call site. `get_roms_by_fs_name` returns `dict[str, Rom]`, iterated via `.values()`.
- **No placeholders:** every code step shows full code.
