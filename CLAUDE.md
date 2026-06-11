# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

RomM — a self-hosted retro game library manager. FastAPI backend + Vue 3 frontend. Scans a filesystem ROM library, enriches metadata from 10+ external providers, manages saves/states/screenshots, supports in-browser emulation.

## Commands

### Backend

```sh
# Setup (once)
uv venv && source .venv/bin/activate
uv sync --all-extras --dev

# Run
cd backend && uv run python3 main.py

# Test (all)
cd backend && uv run pytest -vv

# Test (single file or path)
cd backend && uv run pytest tests/handler/test_scan_handler.py -vv

# Test DB setup (once, requires docker services running)
docker exec -i romm-db-dev mariadb -uroot -p<root password> < backend/romm_test/setup.sql
```

### Frontend

```sh
cd frontend
npm install
npm run dev          # Dev server on :3000
npm run typecheck    # TypeScript validation
npm run lint         # ESLint
npm run build        # Production build
npm run generate     # Regenerate __generated__/models/ from backend OpenAPI (backend must be running)
```

### Linting (both)

```sh
trunk fmt    # Format
trunk check  # Lint — must pass for CI
```

### Docker dev

```sh
cp env.template .env   # then set DEV_MODE=true
docker compose up -d   # spins up MariaDB + Valkey + Postgres (for Authentik)
```

Services: backend on `:5000`, Vite dev server on `:3000`, MariaDB on `:3306`, Valkey/Redis on `:6379`.

## Architecture

### Backend (FastAPI, Python 3.13+)

Three-tier layered architecture:

```
endpoints/     → API route handlers + Pydantic response schemas
handler/       → Business logic (scan, auth, database CRUD, metadata, filesystem)
models/        → SQLAlchemy ORM models
```

Key subdirectories:
- `handler/database/` — per-entity CRUD (one file per model, e.g., `roms_handler.py`)
- `handler/metadata/` — one handler per external provider (IGDB, MobyGames, ScreenScraper, SteamGridDB, RetroAchievements, LaunchBox, Hasheous, TGDB, Flashpoint, HLTB, PlayMatch, Libretro)
- `handler/filesystem/` — ROM file I/O, hashing (CRC32/MD5/SHA1/RA), archive extraction
- `handler/auth/` — multi-method auth: session cookie, Basic, Bearer JWT, Bearer `rmm_*` client tokens, OIDC
- `adapters/services/` — thin HTTP wrappers for external APIs
- `tasks/scheduled/` + `tasks/manual/` — RQ background jobs
- `alembic/versions/` — 80+ migration scripts

**Key patterns:**
- `@begin_session` decorator injects DB session into handlers
- `@protected_route` checks OAuth scopes
- `ConfigManager` singleton reads `config.yml`
- Fixture JSON files (MAME index, PS1/PS2/PSP serials, known BIOS hashes) loaded into Redis at startup
- File serving: `FileResponse` in dev (`DEV_MODE=true`), Nginx `X-Accel-Redirect` in production
- `rq_scheduler` + Redis for cron jobs; `RQ` with 3 priority queues (`high_prio`, `default`, `low_prio`)
- Socket.IO mounted at `/ws` (scan progress) and `/netplay` (multiplayer rooms)

**Database:** MariaDB (default), MySQL, or PostgreSQL. Driver selected via `ROMM_DB_DRIVER`. Sessions use `expire_on_commit=False`. Migrations run automatically on startup.

**Tests:** Use FakeRedis, VCR cassettes for external APIs, separate `romm_test` DB. Tests mirror backend structure under `tests/`.

### Frontend (Vue 3, TypeScript)

```
plugins/       → Vuetify, Pinia, Vue Router, vue-i18n, Mitt
stores/        → 18 Pinia stores (roms is largest ~400 lines)
services/api/  → 17 Axios modules, one per backend resource
components/    → ~168 components, feature-based under common/ and feature dirs
views/         → Page-level route components
console/       → TV/gamepad-optimized UI with its own input system
```

**Key patterns:**
- All components use `<script setup>` Composition API
- Cross-component events via Mitt (80+ event types in `types/emitter.d.ts`)
- Dialogs triggered by Mitt events, rendered in `Main.vue` layout
- `__generated__/models/` — TypeScript types generated from backend OpenAPI; regenerate after schema changes with `npm run generate`
- `galleryFilter` store manages 13+ filter dimensions sent to `GET /api/roms`
- UI settings synced bidirectionally: localStorage ↔ `user.ui_settings` JSON column via `useUISettings` composable
- `heartbeatStore` drives feature flag availability across the UI (which metadata providers are configured, emulation toggles, OIDC state)
- Axios intercepts 403 → clears session → redirect to `/login`; injects CSRF token (`x-csrftoken`) on every mutating request

**Console mode** (`/console/*`): Stack-based input scope manager (`console/input/bus.ts`), spatial navigation composables, procedural Web Audio SFX.

**Paths:** `@/` alias maps to `frontend/src/`.

## Important Conventions

- **New DB columns** → add Alembic migration. Use batch mode for schema changes to support SQLite in tests.
- **New API endpoints** → add Pydantic response schema in `endpoints/responses/`, register router in `main.py`
- **New metadata provider** → add handler in `handler/metadata/`, add adapter in `adapters/services/`, wire into scan flow in `handler/scan_handler.py`
- **ROM hashing** is skipped for some platforms (Switch, PS3/4/5); check `handler/filesystem/roms_handler.py` before adding hash logic
- **`virtual_collections`** is a DB view excluded from Alembic migrations — don't try to migrate it
- The custom `rq-scheduler` fork (in `pyproject.toml`) adds username + SSL support missing from upstream; don't swap it for the upstream package
