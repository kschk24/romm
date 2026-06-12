import asyncio
import binascii
import fnmatch
import hashlib
import os
import re
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

from anyio import Path as AnyioPath

from config import LIBRARY_BASE_PATH
from logger.formatter import highlight as hl
from logger.logger import log
from config.config_manager import (
    DEFAULT_EXCLUDED_EXTENSIONS,
    DEFAULT_EXCLUDED_FILES,
)
from config.config_manager import config_manager as cm
from exceptions.fs_exceptions import (
    RomAlreadyExistsException,
    RomsNotFoundException,
)
from handler.metadata.base_handler import UniversalPlatformSlug as UPS
from models.platform import Platform
from models.rom import Rom, RomFile, RomFileCategory
from utils.archives import (
    detect_mime_type,
    extract_chd_hash,
    is_chd_file,
    process_7z_file,
    read_7z_archive_files,
    read_basic_file,
    read_bz2_file,
    read_gz_file,
    read_rar_archive_files,
    read_tar_archive_files,
    read_tar_file,
    read_zip_archive_files,
    read_zip_file,
)
from utils.filesystem import iter_files
from utils.hashing import crc32_to_hex

from .base_handler import (
    LANGUAGES_BY_SHORTCODE,
    LANGUAGES_NAME_KEYS,
    REGIONS_BY_SHORTCODE,
    REGIONS_NAME_KEYS,
    TAG_REGEX,
    FSHandler,
)

# PICO-8 cartridges are often stored as PNG files
PICO8_CARTRIDGE_EXTENSION = ".p8.png"

# Matches disc-number tags: "(Disc 1)", "[Disk 2]", "(Disc1)", etc.
_DISC_TAG_RE: re.Pattern = re.compile(
    r"\s*[\(\[]\s*dis[ck]\s*\d+\s*[\)\]]", re.IGNORECASE
)


NON_HASHABLE_PLATFORMS = frozenset(
    (
        UPS.AMAZON_ALEXA,
        UPS.AMAZON_FIRE_TV,
        UPS.ANDROID,
        UPS.GEAR_VR,
        UPS.IOS,
        UPS.IPAD,
        UPS.LINUX,
        UPS.MAC,
        UPS.META_QUEST_2,
        UPS.META_QUEST_3,
        UPS.OCULUS_GO,
        UPS.OCULUS_QUEST,
        UPS.OCULUS_RIFT,
        UPS.PS3,
        UPS.PS4,
        UPS.PS5,
        UPS.PSVR,
        UPS.PSVR2,
        UPS.SERIES_X_S,
        UPS.SWITCH,
        UPS.SWITCH_2,
        UPS.WIIU,
        UPS.WIN,
        UPS.XBOX360,
        UPS.XBOXONE,
        UPS.SERIES_X_S,
    )
)


class FSRom(TypedDict):
    fs_name: str
    flat: bool
    nested: bool
    files: list[RomFile]
    crc_hash: str
    md5_hash: str
    sha1_hash: str
    ra_hash: str


class FileHash(TypedDict):
    crc_hash: str
    md5_hash: str
    sha1_hash: str
    chd_sha1_hash: str


def category_matches(category: str, path_parts: list[str]):
    return category in path_parts or f"{category}s" in path_parts


DEFAULT_CRC_C = 0
DEFAULT_MD5_H_DIGEST = hashlib.md5(usedforsecurity=False).digest()
DEFAULT_SHA1_H_DIGEST = hashlib.sha1(usedforsecurity=False).digest()

ARCHIVE_READERS = {
    ".zip": read_zip_archive_files,
    ".tar": read_tar_archive_files,
    ".tar.gz": read_tar_archive_files,
    ".tgz": read_tar_archive_files,
    ".tar.bz2": read_tar_archive_files,
    ".tbz2": read_tar_archive_files,
    ".tar.xz": read_tar_archive_files,
    ".txz": read_tar_archive_files,
    ".7z": read_7z_archive_files,
    ".rar": read_rar_archive_files,
}


def _make_file_hash(
    crc_c: int, md5_h: Any, sha1_h: Any, chd_sha1_hash: str = ""
) -> FileHash:
    """Build a FileHash, blanking each field whose hasher state is still the default."""
    return FileHash(
        crc_hash=crc32_to_hex(crc_c) if crc_c != DEFAULT_CRC_C else "",
        md5_hash=md5_h.hexdigest() if md5_h.digest() != DEFAULT_MD5_H_DIGEST else "",
        sha1_hash=(
            sha1_h.hexdigest() if sha1_h.digest() != DEFAULT_SHA1_H_DIGEST else ""
        ),
        chd_sha1_hash=chd_sha1_hash,
    )


VERSION_TAG_REGEX = re.compile(r"^(?:version|ver|v)[\s_-]?(.*)", re.I)
REGION_TAG_REGEX = re.compile(r"^reg[\s|-](.*)$", re.I)
REVISION_TAG_REGEX = re.compile(r"^rev[\s|-](.*)$", re.I)


@dataclass(frozen=True)
class ParsedTags:
    version: str
    revision: str
    regions: list[str]
    languages: list[str]
    other_tags: list[str]


@dataclass(frozen=True)
class ParsedRomFiles:
    rom_files: list[RomFile]
    crc_hash: str
    md5_hash: str
    sha1_hash: str
    ra_hash: str


class FSRomsHandler(FSHandler):
    def __init__(self) -> None:
        super().__init__(base_path=LIBRARY_BASE_PATH)

    def get_roms_fs_structure(self, fs_slug: str) -> str:
        cnfg = cm.get_config()
        return (
            f"{fs_slug}/{cnfg.ROMS_FOLDER_NAME}"
            if cnfg.has_structure_path_b
            else f"{cnfg.ROMS_FOLDER_NAME}/{fs_slug}"
        )

    def parse_tags(self, fs_name: str) -> ParsedTags:
        tags = [
            chunk.strip()
            for tag in (m[0] or m[1] for m in TAG_REGEX.findall(fs_name))
            for chunk in tag.split(",")
        ]

        regions, languages, other_tags = [], [], []
        version = revision = ""

        for raw_tag in tags:
            lower_tag = raw_tag.lower()

            # Region by code
            if raw_tag in REGIONS_BY_SHORTCODE.keys():
                regions.append(REGIONS_BY_SHORTCODE[raw_tag])
                continue
            if lower_tag in REGIONS_NAME_KEYS:
                regions.append(raw_tag)
                continue

            # Language by code
            if raw_tag in LANGUAGES_BY_SHORTCODE.keys():
                languages.append(LANGUAGES_BY_SHORTCODE[raw_tag])
                continue
            if lower_tag in LANGUAGES_NAME_KEYS:
                languages.append(raw_tag)
                continue

            # Version
            version_match = VERSION_TAG_REGEX.match(raw_tag)
            if version_match:
                version = version_match[1]
                continue

            # Region prefix
            region_match = REGION_TAG_REGEX.match(raw_tag)
            if region_match:
                key = region_match[1].lower()
                regions.append(REGIONS_BY_SHORTCODE.get(key, region_match[1]))
                continue

            # Revision prefix
            revision_match = REVISION_TAG_REGEX.match(raw_tag)
            if revision_match:
                revision = revision_match[1]
                continue

            # Anything else
            other_tags.append(raw_tag)

        return ParsedTags(
            version=version,
            regions=regions,
            languages=languages,
            revision=revision,
            other_tags=other_tags,
        )

    def exclude_multi_roms(self, roms: list[str]) -> list[str]:
        excluded_names = cm.get_config().EXCLUDED_MULTI_FILES
        normalized_patterns = [
            excluded_name.lower().strip() for excluded_name in excluded_names
        ]

        kept_roms: list[str] = []
        for rom in roms:
            normalized_rom_name = rom.strip().lower()
            if normalized_rom_name in normalized_patterns:
                continue

            if any(
                fnmatch.fnmatch(normalized_rom_name, pattern)
                for pattern in normalized_patterns
            ):
                continue

            kept_roms.append(rom)

        return kept_roms

    @staticmethod
    def _cue_stems(filtered_single: list[str]) -> set[str]:
        """Return stems of all .cue files in filtered_single.

        Used to suppress same-stem .bin/.img siblings from appearing as
        standalone ROM entries.
        """
        return {Path(f).stem for f in filtered_single if f.lower().endswith(".cue")}

    def _build_rom_file(
        self,
        rom: Rom,
        rom_path: Path,
        file_name: str,
        file_hash: FileHash,
        file_size_bytes: int | None = None,
        last_modified: float | None = None,
        archive_members: list[dict[str, Any]] | None = None,
    ) -> RomFile:
        abs_file_path = Path(self.base_path, rom_path, file_name)

        path_parts_lower = list(map(str.lower, rom_path.parts))
        matching_category = next(
            (
                category
                for category in RomFileCategory
                if category_matches(category.value, path_parts_lower)
            ),
            None,
        )

        return RomFile(
            rom=rom,
            rom_id=rom.id,
            file_name=file_name,
            file_path=str(rom_path),
            file_size_bytes=(
                file_size_bytes
                if file_size_bytes is not None
                else os.stat(abs_file_path).st_size
            ),
            last_modified=(
                last_modified
                if last_modified is not None
                else os.path.getmtime(abs_file_path)
            ),
            category=matching_category,
            crc_hash=file_hash["crc_hash"],
            md5_hash=file_hash["md5_hash"],
            sha1_hash=file_hash["sha1_hash"],
            chd_sha1_hash=file_hash["chd_sha1_hash"],
            archive_members=archive_members,
        )

    async def get_rom_files(
        self, rom: Rom, calculate_hashes: bool = True
    ) -> ParsedRomFiles:
        from adapters.services.rahasher import RAHasherService
        from handler.metadata import meta_ra_handler

        rel_roms_path = self.get_roms_fs_structure(
            rom.platform.fs_slug
        )  # Relative path to roms
        abs_fs_path = self.validate_path(rel_roms_path)  # Absolute path to roms
        rom_files: list[RomFile] = []

        # Skip hashing games for platforms that don't have a hash database or when hashes are disabled
        hashable_platform = (
            rom.platform_slug not in NON_HASHABLE_PLATFORMS and calculate_hashes
        )

        cnfg = cm.get_config()
        excluded_file_names = cnfg.EXCLUDED_MULTI_PARTS_FILES
        excluded_file_exts = cnfg.EXCLUDED_MULTI_PARTS_EXT

        rom_crc_c = 0
        rom_md5_h = hashlib.md5(usedforsecurity=False) if calculate_hashes else None
        rom_sha1_h = hashlib.sha1(usedforsecurity=False) if calculate_hashes else None
        rom_ra_h = ""

        rom_dir = Path(abs_fs_path, rom.fs_name)
        rom_ext = f".{rom.fs_extension.lower()}" if rom.fs_extension else ""

        # For M3U-backed ROMs the actual disc images live in a sibling directory
        # named after the .m3u stem (e.g. "Game (USA).m3u" → "Game (USA)/").
        if rom_ext == ".m3u":
            m3u_sibling = Path(abs_fs_path, Path(rom.fs_name).stem)
            if await AnyioPath(m3u_sibling).is_dir():
                rom_dir = m3u_sibling

        # Check if rom is a multi-part rom
        if await AnyioPath(rom_dir).is_dir():
            # Calculate the RA hash if the platform has a slug that matches a known RA slug
            if calculate_hashes:
                ra_platform = meta_ra_handler.get_platform(rom.platform_slug)
                if ra_platform and ra_platform["ra_id"]:
                    # RAHasher can't process CHD files via the /* wildcard and instead expects
                    # track files (bin/cue/etc.). For CHD-only folders, find the largest
                    # CHD and pass it directly, matching single-file CHD behaviour.

                    def _largest_chd_file() -> Path | None:
                        chds = [f for f in rom_dir.iterdir() if is_chd_file(f)]
                        sorted_chds = sorted(
                            chds, key=lambda f: f.stat().st_size, reverse=True
                        )
                        return sorted_chds[0] if sorted_chds else None

                    chd_file = await asyncio.to_thread(_largest_chd_file)
                    ra_path = (
                        str(chd_file)
                        if chd_file and chd_file.is_file()
                        else f"{rom_dir}/*"
                    )
                    rom_ra_h = await RAHasherService().calculate_hash(
                        ra_platform,
                        ra_path,
                    )

            for f_path, file_name in iter_files(str(rom_dir), recursive=True):
                # Check if file is excluded by extension.
                f_rom_dir = Path(f_path, file_name)
                file_name_lower = file_name.lower()
                if any(
                    file_name_lower.endswith("." + ext) for ext in excluded_file_exts
                ):
                    continue

                # Check if the file name matches a pattern in the excluded list.
                if any(
                    file_name == exc_name or fnmatch.fnmatch(file_name, exc_name)
                    for exc_name in excluded_file_names
                ):
                    continue

                # Check if this is a top-level file (not in a subdirectory)
                is_top_level = f_path.samefile(rom_dir)

                if hashable_platform:
                    try:
                        if is_top_level:
                            # Include this file in the main ROM hash calculation
                            crc_c, rom_crc_c, md5_h, rom_md5_h, sha1_h, rom_sha1_h = (
                                await asyncio.to_thread(
                                    self._calculate_rom_hashes,
                                    Path(f_path, file_name),
                                    rom_crc_c,
                                    rom_md5_h,
                                    rom_sha1_h,
                                )
                            )
                        else:
                            # Calculate individual file hash only
                            crc_c, _, md5_h, _, sha1_h, _ = await asyncio.to_thread(
                                self._calculate_rom_hashes,
                                Path(f_path, file_name),
                                0,
                                hashlib.md5(usedforsecurity=False),
                                hashlib.sha1(usedforsecurity=False),
                            )
                    except zlib.error:
                        crc_c = 0
                        md5_h = hashlib.md5(usedforsecurity=False)
                        sha1_h = hashlib.sha1(usedforsecurity=False)

                    file_hash = _make_file_hash(
                        crc_c,
                        md5_h,
                        sha1_h,
                        chd_sha1_hash=(
                            extract_chd_hash(f_rom_dir)
                            if is_chd_file(f_rom_dir)
                            else ""
                        ),
                    )
                else:
                    file_hash = FileHash(
                        crc_hash="",
                        md5_hash="",
                        sha1_hash="",
                        chd_sha1_hash="",
                    )

                rom_files.append(
                    self._build_rom_file(
                        rom=rom,
                        rom_path=f_path.relative_to(self.base_path),
                        file_name=file_name,
                        file_hash=file_hash,
                    )
                )
        elif hashable_platform and rom_ext in ARCHIVE_READERS:
            # Multi-file archive: compute a composite hash across all
            # internal entries (in ASCII path order) for hash-database
            # matching, while still emitting a single RomFile for the
            # archive file itself. Per-member hashes are stored on that
            # RomFile in `archive_members` so consumers can identify each
            # internal file without us inventing RomFile rows whose
            # full_path would point inside the archive and break downloads.
            assert rom_md5_h is not None and rom_sha1_h is not None

            def _hash_archive_entries(
                crc: int, md5_h: Any, sha1_h: Any
            ) -> tuple[list[dict[str, Any]], int]:
                members: list[dict[str, Any]] = []
                for name, size, chunks in ARCHIVE_READERS[rom_ext](
                    rom_dir,
                    DEFAULT_EXCLUDED_FILES,
                    DEFAULT_EXCLUDED_EXTENSIONS,
                ):
                    member_crc = 0
                    member_md5 = hashlib.md5(usedforsecurity=False)
                    member_sha1 = hashlib.sha1(usedforsecurity=False)
                    for chunk in chunks:
                        crc = binascii.crc32(chunk, crc)
                        md5_h.update(chunk)
                        sha1_h.update(chunk)
                        member_crc = binascii.crc32(chunk, member_crc)
                        member_md5.update(chunk)
                        member_sha1.update(chunk)
                    members.append(
                        {
                            "name": name,
                            "size": size,
                            "crc_hash": crc32_to_hex(member_crc),
                            "md5_hash": member_md5.hexdigest(),
                            "sha1_hash": member_sha1.hexdigest(),
                        }
                    )
                return members, crc

            members, rom_crc_c = await asyncio.to_thread(
                _hash_archive_entries, rom_crc_c, rom_md5_h, rom_sha1_h
            )

            if members:
                if calculate_hashes:
                    ra_platform = meta_ra_handler.get_platform(rom.platform_slug)
                    if ra_platform and ra_platform["ra_id"]:
                        rom_ra_h = await RAHasherService().calculate_hash(
                            ra_platform,
                            f"{abs_fs_path}/{rom.fs_name}",
                        )

                rom_files.append(
                    self._build_rom_file(
                        rom=rom,
                        rom_path=Path(rel_roms_path),
                        file_name=rom.fs_name,
                        file_hash=_make_file_hash(rom_crc_c, rom_md5_h, rom_sha1_h),
                        archive_members=members,
                    )
                )
            else:
                # Empty, malformed, or all-excluded archive: hash the archive
                # file's raw bytes. We avoid `_calculate_rom_hashes` here because
                # it would decompress based on extension and end up hashing the
                # largest internal member, not the archive itself — and would
                # crash on an empty zip. `archive_members` stays None.
                def _hash_raw_archive(crc: int) -> int:
                    for chunk in read_basic_file(rom_dir):
                        crc = binascii.crc32(chunk, crc)
                        if rom_md5_h:
                            rom_md5_h.update(chunk)
                        if rom_sha1_h:
                            rom_sha1_h.update(chunk)
                    return crc

                rom_crc_c = await asyncio.to_thread(_hash_raw_archive, rom_crc_c)
                rom_files.append(
                    self._build_rom_file(
                        rom=rom,
                        rom_path=Path(rel_roms_path),
                        file_name=rom.fs_name,
                        file_hash=_make_file_hash(rom_crc_c, rom_md5_h, rom_sha1_h),
                    )
                )
        elif hashable_platform:
            try:
                crc_c, rom_crc_c, md5_h, rom_md5_h, sha1_h, rom_sha1_h = (
                    await asyncio.to_thread(
                        self._calculate_rom_hashes,
                        Path(abs_fs_path, rom.fs_name),
                        rom_crc_c,
                        rom_md5_h,
                        rom_sha1_h,
                    )
                )
            except zlib.error:
                crc_c = 0
                md5_h = hashlib.md5(usedforsecurity=False)
                sha1_h = hashlib.sha1(usedforsecurity=False)

            # Calculate the RA hash if the platform has a slug that matches a known RA slug
            if calculate_hashes:
                ra_platform = meta_ra_handler.get_platform(rom.platform_slug)
                if ra_platform and ra_platform["ra_id"]:
                    rom_ra_h = await RAHasherService().calculate_hash(
                        ra_platform,
                        f"{abs_fs_path}/{rom.fs_name}",
                    )

            file_hash = _make_file_hash(
                crc_c,
                md5_h,
                sha1_h,
                chd_sha1_hash=(
                    extract_chd_hash(rom_dir) if is_chd_file(rom_dir) else ""
                ),
            )
            rom_files.append(
                self._build_rom_file(
                    rom=rom,
                    rom_path=Path(rel_roms_path),
                    file_name=rom.fs_name,
                    file_hash=file_hash,
                )
            )
        else:
            file_hash = FileHash(
                crc_hash="",
                md5_hash="",
                sha1_hash="",
                chd_sha1_hash="",
            )
            rom_files.append(
                self._build_rom_file(
                    rom=rom,
                    rom_path=Path(rel_roms_path),
                    file_name=rom.fs_name,
                    file_hash=file_hash,
                )
            )

        # For flat .cue ROMs: include same-stem .bin/.img siblings as download
        # parts. These files are suppressed in get_roms() to avoid appearing as
        # standalone ROM entries.
        if rom_ext == ".cue":
            cue_stem = Path(rom.fs_name).stem
            for _, sib_name in iter_files(abs_fs_path, recursive=False):
                sib_ext = Path(sib_name).suffix.lower()
                if sib_ext in (".bin", ".img") and Path(sib_name).stem == cue_stem:
                    rom_files.append(
                        self._build_rom_file(
                            rom=rom,
                            rom_path=Path(rel_roms_path),
                            file_name=sib_name,
                            file_hash=FileHash(
                                crc_hash="",
                                md5_hash="",
                                sha1_hash="",
                                chd_sha1_hash="",
                            ),
                        )
                    )

        return ParsedRomFiles(
            rom_files=rom_files,
            crc_hash=crc32_to_hex(rom_crc_c) if rom_crc_c != DEFAULT_CRC_C else "",
            md5_hash=(
                rom_md5_h.hexdigest()
                if rom_md5_h and rom_md5_h.digest() != DEFAULT_MD5_H_DIGEST
                else ""
            ),
            sha1_hash=(
                rom_sha1_h.hexdigest()
                if rom_sha1_h and rom_sha1_h.digest() != DEFAULT_SHA1_H_DIGEST
                else ""
            ),
            ra_hash=rom_ra_h,
        )

    def _calculate_rom_hashes(
        self,
        file_path: Path,
        rom_crc_c: int,
        rom_md5_h: Any,
        rom_sha1_h: Any,
    ) -> tuple[int, int, Any, Any, Any, Any]:
        extension = Path(file_path).suffix.lower()
        try:
            file_type = detect_mime_type(file_path)

            crc_c = 0
            md5_h = hashlib.md5(usedforsecurity=False)
            sha1_h = hashlib.sha1(usedforsecurity=False)

            def update_hashes(chunk: bytes | bytearray):
                md5_h.update(chunk)
                rom_md5_h.update(chunk)

                sha1_h.update(chunk)
                rom_sha1_h.update(chunk)

                nonlocal crc_c
                crc_c = binascii.crc32(chunk, crc_c)
                nonlocal rom_crc_c
                rom_crc_c = binascii.crc32(chunk, rom_crc_c)

            if extension == ".zip" or file_type == "application/zip":
                for chunk in read_zip_file(file_path):
                    update_hashes(chunk)

            elif extension == ".tar" or file_type == "application/x-tar":
                for chunk in read_tar_file(file_path):
                    update_hashes(chunk)

            elif extension == ".gz" or file_type == "application/x-gzip":
                for chunk in read_gz_file(file_path):
                    update_hashes(chunk)

            elif extension == ".7z" or file_type == "application/x-7z-compressed":
                process_7z_file(
                    file_path=file_path,
                    fn_hash_update=update_hashes,
                )

            elif extension == ".bz2" or file_type == "application/x-bzip2":
                for chunk in read_bz2_file(file_path):
                    update_hashes(chunk)

            else:
                for chunk in read_basic_file(file_path):
                    update_hashes(chunk)

            return crc_c, rom_crc_c, md5_h, rom_md5_h, sha1_h, rom_sha1_h
        except (FileNotFoundError, PermissionError):
            return (
                0,
                rom_crc_c,
                hashlib.md5(usedforsecurity=False),
                rom_md5_h,
                hashlib.sha1(usedforsecurity=False),
                rom_sha1_h,
            )

    async def auto_organize_loose_discs(self, platform: Platform) -> list[str]:
        """Detect loose multi-disc .cue files and restructure them into the
        M3U + sibling-directory layout the scanner expects.

        For each group of 2+ .cue files that share the same base name (after
        stripping disc-number tags), creates:
          <roms>/<Game Name>.m3u        — lists the disc .cue paths
          <roms>/<Game Name>/           — contains all disc files + noload.txt

        Returns the fs_names (directory names) of the games reorganized this run.
        """
        rel_roms_path = self.get_roms_fs_structure(platform.fs_slug)
        try:
            abs_roms_path = self.validate_path(rel_roms_path)
            all_files = await self.list_files(path=rel_roms_path)
        except FileNotFoundError:
            return []

        cue_files = [f for f in all_files if f.lower().endswith(".cue")]

        # Group .cue files by base name (strip disc tag if present).
        # Two-pass: disc-tagged files first so that an untagged "game.cue"
        # never collides with a tagged "game (Disc 1).cue" that shares the
        # same base — the untagged file is skipped if its stem is already
        # claimed by a disc-tagged group.
        disc_groups: dict[str, list[str]] = {}
        for cue in cue_files:
            stem = Path(cue).stem
            base = _DISC_TAG_RE.sub("", stem).strip()
            if base and base != stem:
                disc_groups.setdefault(base, []).append(cue)
        for cue in cue_files:
            stem = Path(cue).stem
            base = _DISC_TAG_RE.sub("", stem).strip()
            if base != stem:  # disc-tagged → already grouped in first pass
                continue
            if stem not in disc_groups:
                disc_groups.setdefault(stem, []).append(cue)

        def _organize(
            _abs: Path,
            _dir: Path,
            _m3u: Path,
            _base: str,
            _cues: list[str],
            _all: list[str],
        ) -> None:
            _dir.mkdir(parents=True, exist_ok=True)
            m3u_lines: list[str] = []
            for cue_name in sorted(_cues):
                cue_stem = Path(cue_name).stem
                # Move .cue and every same-stem sibling (e.g. .bin, .img)
                for sib in _all:
                    if Path(sib).stem == cue_stem:
                        src = _abs / sib
                        dst = _dir / sib
                        if src.exists() and not dst.exists():
                            src.rename(dst)
                m3u_lines.append(f"{_base}/{cue_name}")
            (_dir / "noload.txt").write_text("\n")
            _m3u.write_text("\n".join(m3u_lines) + "\n")

        def _write_m3u(_m3u: Path, _dir: Path, _dir_name: str) -> int:
            cues = sorted(
                f.name for f in _dir.iterdir()
                if f.is_file() and f.suffix.lower() == ".cue"
            )
            if not cues:
                return 0
            _m3u.write_text("\n".join(f"{_dir_name}/{c}" for c in cues) + "\n")
            noload = _dir / "noload.txt"
            if not noload.exists():
                noload.write_text("\n")
            return len(cues)

        organized: list[str] = []
        for base_name, cue_list in disc_groups.items():
            m3u_path = abs_roms_path / f"{base_name}.m3u"
            dir_path = abs_roms_path / base_name

            # Only an existing sibling directory means the game is already
            # organized. A bare ``.m3u`` with no directory is stale (e.g. the
            # folder was deleted and the discs left loose at the root) and must
            # not block reorganization — ``_organize`` overwrites it.
            if dir_path.exists():
                continue  # already organized

            try:
                await asyncio.to_thread(
                    _organize, abs_roms_path, dir_path, m3u_path, base_name, cue_list, all_files
                )
            except OSError as e:
                log.warning(f"Failed to auto-organize {hl(base_name)}: {e}")
                continue
            log.info(
                f"Auto-organized {hl(base_name)} ({len(cue_list)} discs) "
                f"→ {hl(f'{base_name}.m3u')}"
            )
            organized.append(base_name)

        # Pass 2: subdirectories that already contain .cue files but have no
        # paired .m3u at the platform root.
        all_dirs = await self.list_directories(path=rel_roms_path)
        for dir_name in all_dirs:
            m3u_path = abs_roms_path / f"{dir_name}.m3u"
            if m3u_path.exists():
                continue
            dir_path = abs_roms_path / dir_name
            try:
                cue_count = await asyncio.to_thread(
                    _write_m3u, m3u_path, dir_path, dir_name
                )
            except OSError as e:
                log.warning(f"Failed to create M3U for {hl(dir_name)}: {e}")
                continue
            if cue_count:
                log.info(
                    f"Created missing M3U for {hl(dir_name)} ({cue_count} disc(s)) "
                    f"→ {hl(f'{dir_name}.m3u')}"
                )
                organized.append(dir_name)

        return organized

    async def count_roms(self, platform: Platform) -> int:
        """Return the number of filesystem roms for a platform without
        materializing FSRom objects.
        """
        try:
            rel_roms_path = self.get_roms_fs_structure(platform.fs_slug)
            fs_single_roms = await self.list_files(path=rel_roms_path)
            fs_multi_roms = await self.list_directories(path=rel_roms_path)
        except FileNotFoundError as e:
            raise RomsNotFoundException(platform=platform.fs_slug) from e

        filtered_single = self.exclude_single_files(fs_single_roms)
        filtered_multi = self.exclude_multi_roms(fs_multi_roms)
        multi_dir_set = set(filtered_multi)

        cue_stems = self._cue_stems(filtered_single)

        m3u_paired_dirs: set[str] = set()
        paired_count = 0
        unpaired_single_count = 0
        for file_name in filtered_single:
            stem = Path(file_name).stem
            ext = Path(file_name).suffix.lower()
            if file_name.lower().endswith(".m3u") and stem in multi_dir_set:
                m3u_paired_dirs.add(stem)
                paired_count += 1
            elif ext in (".bin", ".img") and stem in cue_stems:
                pass  # suppressed — part of the paired .cue ROM
            else:
                unpaired_single_count += 1

        multi_count = sum(1 for d in filtered_multi if d not in m3u_paired_dirs)
        return unpaired_single_count + multi_count + paired_count

    async def get_roms(self, platform: Platform) -> list[FSRom]:
        """Gets all filesystem roms for a platform

        Args:
            platform: platform where roms belong
        Returns:
            list with all the filesystem roms for a platform
        """
        try:
            rel_roms_path = self.get_roms_fs_structure(
                platform.fs_slug
            )  # Relative path to roms

            fs_single_roms = await self.list_files(path=rel_roms_path)
            fs_multi_roms = await self.list_directories(path=rel_roms_path)
        except FileNotFoundError as e:
            raise RomsNotFoundException(platform=platform.fs_slug) from e

        filtered_single = self.exclude_single_files(fs_single_roms)
        filtered_multi = self.exclude_multi_roms(fs_multi_roms)
        multi_dir_set = set(filtered_multi)

        cue_stems = self._cue_stems(filtered_single)

        # M3U files that have a matching sibling directory are treated as one
        # logical ROM: the .m3u is the entry point; the directory holds the
        # actual disc images.  Emit a single nested FSRom and suppress the
        # directory entry that would otherwise create a duplicate ROM.
        m3u_paired_dirs: set[str] = set()
        paired_entries: list[dict] = []
        unpaired_single: list[str] = []
        for file_name in filtered_single:
            stem = Path(file_name).stem
            ext = Path(file_name).suffix.lower()
            if file_name.lower().endswith(".m3u") and stem in multi_dir_set:
                m3u_paired_dirs.add(stem)
                paired_entries.append(
                    {"fs_name": file_name, "flat": False, "nested": True}
                )
            elif ext in (".bin", ".img") and stem in cue_stems:
                pass  # suppressed — part of the paired .cue ROM
            else:
                unpaired_single.append(file_name)

        fs_roms: list[dict] = (
            [{"fs_name": rom, "flat": True, "nested": False} for rom in unpaired_single]
            + [
                {"fs_name": rom, "flat": False, "nested": True}
                for rom in filtered_multi
                if rom not in m3u_paired_dirs
            ]
            + paired_entries
        )

        return sorted(
            [
                FSRom(
                    fs_name=rom["fs_name"],
                    flat=rom["flat"],
                    nested=rom["nested"],
                    files=[],
                    crc_hash="",
                    md5_hash="",
                    sha1_hash="",
                    ra_hash="",
                )
                for rom in fs_roms
            ],
            key=lambda rom: rom["fs_name"],
        )

    async def rename_fs_rom(self, old_name: str, new_name: str, fs_path: str) -> None:
        if new_name != old_name:
            file_path = f"{fs_path}/{new_name}"
            if await self.file_exists(file_path=file_path):
                raise RomAlreadyExistsException(new_name)

            await self.move_file_or_folder(
                f"{fs_path}/{old_name}", f"{fs_path}/{new_name}"
            )

    def get_pico8_cover_url(
        self, platform_slug: str, fs_name: str, fs_path: str
    ) -> str | None:
        """Return a ``file://`` URL for a PICO-8 cartridge label, or ``None``.

        PICO-8 ``.p8.png`` files are valid PNG images whose visual content *is*
        the cartridge label/cover art.  When such a ROM is found we can use the
        file itself as the cover instead of fetching one from an external source.
        """
        if platform_slug == UPS.PICO and fs_name.lower().endswith(
            PICO8_CARTRIDGE_EXTENSION
        ):
            self.validate_path(f"{fs_path}/{fs_name}")
            return f"file://{fs_path}/{fs_name}"
        return None
