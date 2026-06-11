# ROM Library File Structure

## Overview

Each system has its own directory under the library root. Within each system directory, every game lives in its own named subfolder. A `.m3u` playlist file at the system root acts as the single entry point for each game — this is what frontends (ES-DE, etc.) and emulators (RetroArch) see and launch.

## Layout

```
<library_root>/
└── <system>/                          # e.g. psx/, saturn/, n64/
    ├── Game Title (Region).m3u        # ← frontend/emulator entry point
    ├── Game Title (Region)/           # game subfolder (hidden from frontend)
    │   ├── Game Title (Region).cue    # or .chd, .iso, .bin, etc.
    │   ├── Game Title (Region).bin    # companion data (if applicable)
    │   └── noload.txt                 # tells ES-DE to ignore this folder
    └── systeminfo.txt                 # system metadata (optional)
```

## Multi-Disc Games

All discs for a single game are consolidated into one subfolder. The `.m3u` lists all disc files in order:

```
psx/
├── Final Fantasy VII (Europe).m3u
└── Final Fantasy VII (Europe)/
    ├── Final Fantasy VII (Europe) (Disc 1).cue
    ├── Final Fantasy VII (Europe) (Disc 1).bin
    ├── Final Fantasy VII (Europe) (Disc 2).cue
    ├── Final Fantasy VII (Europe) (Disc 2).bin
    ├── Final Fantasy VII (Europe) (Disc 3).cue
    ├── Final Fantasy VII (Europe) (Disc 3).bin
    └── noload.txt
```

`.m3u` content (relative paths, UTF-8 no BOM, LF line endings):
```
Final Fantasy VII (Europe)/Final Fantasy VII (Europe) (Disc 1).cue
Final Fantasy VII (Europe)/Final Fantasy VII (Europe) (Disc 2).cue
Final Fantasy VII (Europe)/Final Fantasy VII (Europe) (Disc 3).cue
```

## Single-Disc / Single-File Games

Same structure — even single-file games get a subfolder and `.m3u`:

```
psx/
├── Silent Hill (USA).m3u
└── Silent Hill (USA)/
    ├── Silent Hill (USA).bin
    ├── Silent Hill (USA).cue
    └── noload.txt
```

## Key Rules

| Rule | Detail |
|------|--------|
| **One `.m3u` per game** | Lives at the system root, named after the game |
| **One subfolder per game** | Named identically to the `.m3u` (without extension) |
| **Relative paths in `.m3u`** | `<GameFolder>/<filename>.<ext>` |
| **`.m3u` encoding** | UTF-8, no BOM, LF line endings |
| **`noload.txt`** | Empty file in every game subfolder; signals ES-DE to skip scanning it |
| **Disc ordering** | `.m3u` lines sorted by filename (Disc 1, Disc 2, …) |
| **Naming convention** | `Title (Region) (Rev N)` — No disc/track/side tags in game name |
| **Companion files** | `.bin`, `Vimm's Lair.txt`, etc. live inside the game subfolder alongside the disc image |

## Supported File Types (Disc/Image Files)

The `.m3u` references the **descriptor or primary image** file only — companion raw data files (`.bin`, `.img`, `.mdf`) are co-located but not listed:

- **Optical**: `.chd`, `.cue`, `.iso`, `.cdi`, `.gdi`, `.mds`, `.ccd`, `.nrg`, `.toc`, `.ecm`, `.pbp`, `.ciso`, `.cso`, `.zso`
- **GameCube/Wii**: `.gcm`, `.gcz`, `.tgc`, `.rvz`, `.wia`, `.wbfs`, `.wud`, `.wux`
- **Handheld/Cartridge**: `.3ds`, `.nsp`, `.xci`, `.nds`, `.gba`, `.gb`, `.gbc`, etc.
- **Floppy**: `.st`, `.adf`, `.dsk`, `.d64`, `.ipf`, `.hfe`, etc.

## Upload / Download Expectations

When uploading or downloading a game:
- The **`.m3u`** and the **entire game subfolder** (all files within it) belong together as one logical unit
- A game is fully represented by: `<GameName>.m3u` + `<GameName>/` directory
- `noload.txt` should be preserved/recreated in the subfolder on download
