from unittest.mock import AsyncMock, Mock

import pytest
import socketio

from endpoints.sockets import scan as scan_module
from endpoints.sockets.scan import (
    ScanStats,
    _identify_rom,
    _metadata_sources_for_scan_type,
    _should_scan_rom,
    _skip_metadata_phase,
)
from handler.filesystem.roms_handler import FSRomsHandler
from handler.metadata.base_handler import UniversalPlatformSlug as UPS
from handler.scan_handler import ScanType
from models.platform import Platform
from models.rom import Rom
from utils.context import initialize_context


def test_scan_stats():
    stats = ScanStats()
    assert stats.scanned_platforms == 0
    assert stats.new_platforms == 0
    assert stats.identified_platforms == 0
    assert stats.scanned_roms == 0
    assert stats.new_roms == 0
    assert stats.identified_roms == 0
    assert stats.scanned_firmware == 0
    assert stats.new_firmware == 0
    assert stats.organized_roms == 0
    assert "organized_roms" in stats.to_dict()

    stats.scanned_platforms += 1
    stats.new_platforms += 1
    stats.identified_platforms += 1
    stats.scanned_roms += 1
    stats.new_roms += 1
    stats.identified_roms += 1
    stats.scanned_firmware += 1
    stats.new_firmware += 1
    stats.organized_roms += 1

    assert stats.scanned_platforms == 1
    assert stats.new_platforms == 1
    assert stats.identified_platforms == 1
    assert stats.scanned_roms == 1
    assert stats.new_roms == 1
    assert stats.identified_roms == 1
    assert stats.scanned_firmware == 1
    assert stats.new_firmware == 1
    assert stats.organized_roms == 1


async def test_merging_scan_stats():
    stats = ScanStats(
        scanned_platforms=1,
        new_platforms=2,
        identified_platforms=3,
        scanned_roms=4,
        new_roms=5,
        identified_roms=6,
        scanned_firmware=7,
        new_firmware=8,
    )

    await stats.update(
        socket_manager=Mock(spec=socketio.AsyncRedisManager),
        scanned_platforms=stats.scanned_platforms + 10,
        new_platforms=stats.new_platforms + 11,
        identified_platforms=stats.identified_platforms + 12,
        scanned_roms=stats.scanned_roms + 13,
        new_roms=stats.new_roms + 14,
        identified_roms=stats.identified_roms + 15,
        scanned_firmware=stats.scanned_firmware + 16,
        new_firmware=stats.new_firmware + 17,
    )

    assert stats.scanned_platforms == 11
    assert stats.new_platforms == 13
    assert stats.identified_platforms == 15
    assert stats.scanned_roms == 17
    assert stats.new_roms == 19
    assert stats.identified_roms == 21
    assert stats.scanned_firmware == 23
    assert stats.new_firmware == 25


def test_organize_scan_type_value():
    """ORGANIZE scan type exists with the string value 'organize'."""
    assert ScanType.ORGANIZE == "organize"
    assert ScanType("organize") is ScanType.ORGANIZE


class TestShouldScanRom:
    def test_new_platforms_scan_with_no_rom(self):
        """NEW_PLATFORMS should scan when rom is None"""
        result = _should_scan_rom(ScanType.NEW_PLATFORMS, None, [], ["igdb"])
        assert result is True

    def test_new_platforms_scan_with_existing_rom(self, rom: Rom):
        """NEW_PLATFORMS should not scan when rom exists"""
        result = _should_scan_rom(ScanType.NEW_PLATFORMS, rom, [], ["igdb"])
        assert result is False

    # Test QUICK scan type
    def test_quick_scan_with_no_rom(self):
        """QUICK should scan when rom is None"""
        result = _should_scan_rom(ScanType.QUICK, None, [], ["igdb"])
        assert result is True

    def test_quick_scan_with_existing_rom(self, rom: Rom):
        """QUICK should not scan when rom exists"""
        result = _should_scan_rom(ScanType.QUICK, rom, [], ["igdb"])
        assert result is False

    def test_organize_scan_with_no_rom(self):
        """ORGANIZE should scan (add) when rom is None — the new .m3u entry."""
        result = _should_scan_rom(ScanType.ORGANIZE, None, [], ["igdb"])
        assert result is True

    def test_organize_scan_with_existing_rom(self, rom: Rom):
        """ORGANIZE should not re-scan an existing rom."""
        result = _should_scan_rom(ScanType.ORGANIZE, rom, [], ["igdb"])
        assert result is False

    # Test COMPLETE scan type
    def test_complete_scan_always_scans(self, rom: Rom):
        """COMPLETE should scan everything when unscoped, but respect roms_ids when scoped"""
        assert _should_scan_rom(ScanType.COMPLETE, None, [], ["igdb"]) is True
        assert _should_scan_rom(ScanType.COMPLETE, rom, [], ["igdb"]) is True
        # Scoped scan should not scan/add new filesystem ROMs when rom is None
        assert _should_scan_rom(ScanType.COMPLETE, None, [rom.id], ["igdb"]) is False
        # Scoped scan: rom not in list → skip even for COMPLETE
        assert (
            _should_scan_rom(ScanType.COMPLETE, rom, [rom.id + 99], ["igdb"]) is False
        )
        assert _should_scan_rom(ScanType.COMPLETE, rom, [rom.id], ["igdb"]) is True

    # Test HASHES scan type
    def test_hashes_scan_always_scans(self, rom: Rom):
        """HASHES should scan everything when unscoped, but respect roms_ids when scoped"""
        assert _should_scan_rom(ScanType.HASHES, None, [], ["igdb"]) is True
        assert _should_scan_rom(ScanType.HASHES, rom, [], ["igdb"]) is True
        # Scoped scan should not scan/add new filesystem ROMs when rom is None
        assert _should_scan_rom(ScanType.HASHES, None, [rom.id], ["igdb"]) is False
        # Scoped scan: rom not in list → skip even for HASHES
        assert _should_scan_rom(ScanType.HASHES, rom, [rom.id + 99], ["igdb"]) is False
        assert _should_scan_rom(ScanType.HASHES, rom, [rom.id], ["igdb"]) is True

    # Test UNMATCHED scan type
    def test_unmatched_scan_with_no_rom(self):
        """UNMATCHED should not scan when rom is None"""
        result = _should_scan_rom(ScanType.UNMATCHED, None, [], ["igdb"])
        assert result is False

    def test_unmatched_scan_with_unmatched_rom(self, rom: Rom):
        """UNMATCHED should scan when rom is unmatched"""
        rom.igdb_id = None
        rom.moby_id = None
        rom.ss_id = None
        rom.ra_id = None
        rom.launchbox_id = None
        result = _should_scan_rom(ScanType.UNMATCHED, rom, [], ["igdb"])
        assert result is True

    def test_unmatched_scan_with_identified_rom(self, rom: Rom):
        """UNMATCHED should also scan when rom is identified"""
        rom.igdb_id = 1
        result = _should_scan_rom(ScanType.UNMATCHED, rom, [], ["moby"])
        assert result is True

    # Test UPDATE scan type
    def test_update_scan_with_no_rom(self):
        """UPDATE should not scan when rom is None"""
        result = _should_scan_rom(ScanType.UPDATE, None, [], ["igdb"])
        assert result is False

    def test_update_scan_with_identified_rom(self, rom: Rom):
        """UPDATE should scan when rom is identified"""
        rom.igdb_id = 1
        result = _should_scan_rom(ScanType.UPDATE, rom, [], ["igdb"])
        assert result is True

    def test_update_scan_with_unmatched_rom(self, rom: Rom):
        """UPDATE should not scan when rom is not identified"""
        rom.igdb_id = None
        rom.moby_id = None
        rom.ss_id = None
        rom.ra_id = None
        rom.launchbox_id = None
        result = _should_scan_rom(ScanType.UPDATE, rom, [], ["igdb"])
        assert result is False

    # Test rom_ids parameter
    def test_scan_when_rom_id_in_list(self, rom: Rom):
        """Should scan when rom.id is in roms_ids list regardless of scan type"""
        rom.id = 1
        roms_ids = [1, 2, 3]

        # Test with different scan types
        for scan_type in [
            ScanType.QUICK,
            ScanType.UNMATCHED,
            ScanType.UPDATE,
        ]:
            result = _should_scan_rom(scan_type, rom, roms_ids, ["igdb"])
            assert result is True

    def test_no_scan_when_rom_id_not_in_list(self, rom: Rom):
        """When roms_ids is non-empty, scan is scoped: roms outside the list are skipped for every scan type"""
        rom.id = 4
        rom.igdb_id = None
        rom.moby_id = None
        rom.ss_id = None
        rom.ra_id = None
        rom.launchbox_id = None
        roms_ids = [1, 2, 3]

        for scan_type in [
            ScanType.NEW_PLATFORMS,
            ScanType.QUICK,
            ScanType.UPDATE,
            ScanType.UNMATCHED,
            ScanType.COMPLETE,
            ScanType.HASHES,
        ]:
            assert _should_scan_rom(scan_type, rom, roms_ids, ["igdb"]) is False

    # Edge cases
    def test_empty_roms_ids_list(self, rom: Rom):
        """Test behavior with empty roms_ids list"""
        rom.id = 1
        rom.igdb_id = 1

        assert _should_scan_rom(ScanType.UPDATE, rom, [], ["igdb"]) is True
        assert _should_scan_rom(ScanType.NEW_PLATFORMS, rom, [], ["igdb"]) is False

    def test_rom_id_type_conversion(self, rom: Rom):
        """Test that rom.id (int) is properly compared with roms_ids (list of strings)"""
        rom.id = 123
        roms_ids = [123, 456]

        # This should scan because 123 should match "123"
        result = _should_scan_rom(ScanType.QUICK, rom, roms_ids, ["igdb"])
        assert result is True

    @pytest.mark.parametrize(
        "scan_type,rom_exists,is_identified,rom_in_list,expected",
        [
            # Comprehensive test matrix
            (ScanType.NEW_PLATFORMS, False, None, False, False),
            (ScanType.NEW_PLATFORMS, True, True, False, False),
            (ScanType.NEW_PLATFORMS, True, True, True, True),
            (ScanType.QUICK, False, None, False, False),
            (ScanType.QUICK, True, True, False, False),
            (ScanType.COMPLETE, False, None, False, True),
            (ScanType.COMPLETE, True, False, False, True),
            (ScanType.HASHES, False, None, False, True),
            (ScanType.HASHES, True, False, False, True),
            (ScanType.UNMATCHED, True, False, False, True),
            (ScanType.UNMATCHED, True, True, False, False),
            (ScanType.UPDATE, True, True, False, True),
        ],
    )
    def test_comprehensive_scenarios(
        self,
        scan_type,
        rom_exists,
        is_identified,
        rom_in_list,
        expected,
    ):
        """Test comprehensive scenarios with different combinations"""
        rom: Rom = Mock(spec=Rom)
        roms_ids = []

        if rom_exists:
            rom.id = 1
            if is_identified:
                rom.igdb_id = 1
            else:
                rom.igdb_id = None
                rom.moby_id = None
                rom.ss_id = None
                rom.ra_id = None
                rom.launchbox_id = None

            if rom_in_list:
                roms_ids = [1]

        result = _should_scan_rom(scan_type, rom, roms_ids, ["igdb"])
        assert result is expected


class TestGetPico8CoverUrl:
    """Tests for the PICO-8 cover art URL helper on FSRomsHandler."""

    @pytest.fixture
    def handler(self):
        return FSRomsHandler()

    def test_returns_file_url_for_pico8_cartridge(self, handler: FSRomsHandler):
        url = handler.get_pico8_cover_url(
            platform_slug=UPS.PICO,
            fs_name="mygame.p8.png",
            fs_path="pico/roms",
        )
        expected = "file://pico/roms/mygame.p8.png"
        assert url == expected

    def test_returns_none_for_non_pico8_platform(self, handler: FSRomsHandler):
        url = handler.get_pico8_cover_url(
            platform_slug="snes",
            fs_name="mygame.p8.png",
            fs_path="snes/roms",
        )
        assert url is None

    def test_returns_none_for_plain_p8_text_file(self, handler: FSRomsHandler):
        """Plain .p8 files are text-only and have no embedded PNG image."""
        url = handler.get_pico8_cover_url(
            platform_slug=UPS.PICO,
            fs_name="mygame.p8",
            fs_path="pico/roms",
        )
        assert url is None

    def test_returns_none_for_unrelated_extension(self, handler: FSRomsHandler):
        url = handler.get_pico8_cover_url(
            platform_slug=UPS.PICO,
            fs_name="mygame.zip",
            fs_path="pico/roms",
        )
        assert url is None

    def test_url_starts_with_file_scheme(self, handler: FSRomsHandler):
        url = handler.get_pico8_cover_url(
            platform_slug=UPS.PICO,
            fs_name="cart.p8.png",
            fs_path="pico/roms",
        )
        assert url is not None
        assert url.startswith("file://")

    def test_url_contains_fs_path_and_name(self, handler: FSRomsHandler):
        fs_path = "pico/roms"
        fs_name = "celeste.p8.png"
        url = handler.get_pico8_cover_url(
            platform_slug=UPS.PICO,
            fs_name=fs_name,
            fs_path=fs_path,
        )
        assert url is not None
        assert fs_path in url
        assert fs_name in url


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


class TestOrganizeScanEmitsFeedback:
    """An ORGANIZE scan reorganizes discs and adds new (unidentified) .m3u roms
    to the DB, then short-circuits before the metadata phase. The scan results
    UI is driven solely by ``scan:scanning_rom`` socket events, so those new
    roms must still be emitted — otherwise the user sees "No new/changed ROMs
    found" even though work was done.
    """

    async def test_organize_emits_scanning_rom_for_new_unidentified_rom(
        self, platform: Platform, mocker
    ):
        mocker.patch.object(scan_module.redis_client, "get", return_value=None)
        mocker.patch.object(
            scan_module.fs_rom_handler,
            "get_rom_files",
            new=AsyncMock(
                return_value=Mock(
                    rom_files=[],
                    crc_hash="",
                    md5_hash="",
                    sha1_hash="",
                    ra_hash="",
                )
            ),
        )
        # scan_rom returns the (newly added, unidentified) rom unchanged.
        mocker.patch.object(
            scan_module,
            "scan_rom",
            new=AsyncMock(side_effect=lambda **kwargs: kwargs["rom"]),
        )

        socket_manager = AsyncMock()
        scan_stats = ScanStats()

        fs_rom = {
            "fs_name": "Final Fantasy VII (USA).m3u",
            "flat": False,
            "nested": True,
            "files": [],
            "crc_hash": "",
            "md5_hash": "",
            "sha1_hash": "",
            "ra_hash": "",
        }

        async with initialize_context():
            await _identify_rom(
                platform=platform,
                fs_rom=fs_rom,
                rom=None,
                scan_type=ScanType.ORGANIZE,
                roms_ids=[],
                metadata_sources=[],
                launchbox_remote_enabled=False,
                socket_manager=socket_manager,
                scan_stats=scan_stats,
            )

        emitted_events = [call.args[0] for call in socket_manager.emit.call_args_list]
        assert "scan:scanning_rom" in emitted_events


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
