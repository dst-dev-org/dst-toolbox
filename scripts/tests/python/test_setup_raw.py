"""Exercise source preparation in temporary synthetic Steam installations."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile


SOURCE_SCRIPT = Path(os.environ["DST_SETUP_SCRIPT"]) if os.environ.get("DST_SETUP_SCRIPT") else None
POWERSHELL = os.environ.get("DST_TEST_POWERSHELL") or shutil.which("pwsh") or shutil.which("powershell")
FILES = ("class.lua", "entityscript.lua", "components/example.lua", "prefabs/example.lua")
OTHER_DRIVE_TEMP = os.environ.get("DST_TEST_OTHER_DRIVE_TEMP")


@unittest.skipUnless(POWERSHELL and SOURCE_SCRIPT and SOURCE_SCRIPT.is_file(), "set DST_SETUP_SCRIPT to an installed Skill setup_raw.ps1")
class SourcePreparationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dst-setup-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.project = self.root / "wiki workspace"
        self.script = self.project / "scripts/setup_raw.ps1"
        self.script.parent.mkdir(parents=True)
        shutil.copy2(SOURCE_SCRIPT, self.script)
        self.game = self.root / "Steam Library/steamapps/common/Don't Starve Together"
        self.game.mkdir(parents=True)
        self.current = self.project / "raw/current"
        self.archives = self.project / "raw/archive"
        self.zip = self.game / "data/databundles/scripts.zip"
        self.zip.parent.mkdir(parents=True)
        self.prepare_install("101")

    def prepare_install(self, build, files=FILES):
        manifest = self.game.parents[1] / "appmanifest_322330.acf"
        manifest.write_text(f'"AppState" {{ "buildid" "{build}" }}', encoding="utf-8")
        with zipfile.ZipFile(self.zip, "w") as archive:
            for name in files:
                archive.writestr("scripts/" + name, f"-- synthetic build {build}\n")

    def prepare_current(self, build="101", files=FILES):
        self.current.mkdir(parents=True)
        (self.current / "BUILD.txt").write_text(build + "\n", encoding="ascii")
        for name in files:
            path = self.current / "scripts" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("-- previous snapshot\n", encoding="utf-8")

    def run_setup(self, *options, knowledge_root=None, game_path=None, steam_path=None):
        command = [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(self.script),
                   "-KnowledgeRoot", str(self.project if knowledge_root is None else knowledge_root)]
        if steam_path is not None:
            command.extend(["-SteamPath", str(steam_path)])
        if game_path is not None or steam_path is None:
            command.extend(["-GamePath", str(self.game if game_path is None else game_path)])
        result = subprocess.run(
            [*command, *options], cwd=self.root,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30,
        )
        return result.returncode, result.stdout.decode("utf-8", errors="replace")

    def assert_no_staging(self):
        self.assertEqual(list((self.project / "raw").glob(".setup-*")), [])

    def test_first_install_prepares_source(self):
        code, output = self.run_setup()
        self.assertEqual(code, 0, output)
        self.assertEqual((self.current / "BUILD.txt").read_text().strip(), "101")
        self.assertTrue(all((self.current / "scripts" / file).is_file() for file in FILES))
        self.assertFalse(self.archives.exists())
        self.assert_no_staging()

    def test_same_build_skips_without_changing_snapshot(self):
        self.prepare_current()
        before = (self.current / "scripts/class.lua").read_bytes()
        code, output = self.run_setup()
        self.assertEqual(code, 0, output)
        self.assertIn("[Skip]", output)
        self.assertEqual((self.current / "scripts/class.lua").read_bytes(), before)
        self.assertFalse(self.archives.exists())
        self.assert_no_staging()

    def test_update_keeps_old_snapshot_and_existing_archive(self):
        self.prepare_current()
        existing_archive = self.archives / "build-101"
        existing_archive.mkdir(parents=True)
        marker = existing_archive / "keep.txt"
        marker.write_text("older archive", encoding="utf-8")
        self.prepare_install("102")
        code, output = self.run_setup()
        self.assertEqual(code, 0, output)
        self.assertEqual((self.current / "BUILD.txt").read_text().strip(), "102")
        self.assertEqual(marker.read_text(), "older archive")
        new_archives = [p for p in self.archives.iterdir() if p != existing_archive]
        self.assertEqual(len(new_archives), 1)
        self.assertEqual((new_archives[0] / "scripts/class.lua").read_text(), "-- previous snapshot\n")
        self.assert_no_staging()

    def test_force_preserves_same_build_snapshot(self):
        self.prepare_current()
        code, output = self.run_setup("-Force")
        self.assertEqual(code, 0, output)
        self.assertNotIn("[Skip]", output)
        self.assertEqual((self.archives / "build-101/scripts/class.lua").read_text(), "-- previous snapshot\n")
        self.assert_no_staging()

    def test_incomplete_same_build_gets_repaired(self):
        self.prepare_current(files=("class.lua",))
        code, output = self.run_setup()
        self.assertEqual(code, 0, output)
        self.assertNotIn("[Skip]", output)
        self.assertTrue(all((self.current / "scripts" / file).is_file() for file in FILES))
        self.assertTrue((self.archives / "build-101/scripts/class.lua").is_file())
        self.assert_no_staging()

    def test_failed_preparations_preserve_current(self):
        for failure in ("missing", "corrupt", "incomplete"):
            with self.subTest(failure=failure):
                self.prepare_install("102")
                if not self.current.exists():
                    self.prepare_current()
                if failure == "missing":
                    self.zip.unlink()
                elif failure == "corrupt":
                    self.zip.write_bytes(b"not a zip file")
                else:
                    self.prepare_install("102", files=("class.lua",))
                code, output = self.run_setup()
                self.assertNotEqual(code, 0, output)
                self.assertEqual((self.current / "BUILD.txt").read_text().strip(), "101")
                self.assertEqual((self.current / "scripts/class.lua").read_text(), "-- previous snapshot\n")
                self.assertFalse(self.archives.exists())
                self.assert_no_staging()

    def test_snapshot_without_build_is_preserved(self):
        self.prepare_current()
        (self.current / "BUILD.txt").unlink()
        code, output = self.run_setup()
        self.assertEqual(code, 0, output)
        self.assertEqual((self.archives / "build-unidentified/scripts/class.lua").read_text(), "-- previous snapshot\n")
        self.assert_no_staging()

    def assert_current_preserved(self):
        self.assertEqual((self.current / "BUILD.txt").read_text().strip(), "101")
        self.assertEqual((self.current / "scripts/class.lua").read_text(), "-- previous snapshot\n")
        self.assertFalse(self.archives.exists())
        self.assert_no_staging()

    def test_relative_paths_fail_before_snapshot_changes(self):
        self.prepare_current()
        paths = ["relative/path"]
        if os.name == "nt":
            paths.extend([f"{self.root.drive}relative", r"\root-relative"])
        for path in paths:
            for argument, expected in (("knowledge_root", "KnowledgeRoot"),
                                       ("game_path", "GamePath"), ("steam_path", "SteamPath")):
                with self.subTest(argument=argument, path=path):
                    code, output = self.run_setup(**{argument: path})
                    self.assertNotEqual(code, 0, output)
                    self.assertIn(f"{expected} must be absolute.", output)
                    self.assert_current_preserved()
        self.assertFalse((self.root / "relative").exists())

    def test_missing_or_file_install_paths_give_focused_errors(self):
        self.prepare_current()
        file_path = self.root / "not a directory"
        file_path.write_text("keep", encoding="ascii")
        for path in (self.root / "missing directory", file_path):
            for argument, expected in (("game_path", "Game"), ("steam_path", "Steam")):
                with self.subTest(argument=argument, path=path):
                    code, output = self.run_setup(**{argument: path})
                    self.assertNotEqual(code, 0, output)
                    self.assertIn(f"{expected} path not found:", output)
                    self.assert_current_preserved()
        self.assertEqual(file_path.read_text(), "keep")

    def test_explicit_steam_path_finds_game(self):
        code, output = self.run_setup(steam_path=self.game.parents[2])
        self.assertEqual(code, 0, output)
        self.assertEqual((self.current / "BUILD.txt").read_text().strip(), "101")

    def test_explicit_game_path_takes_precedence_over_unused_steam_path(self):
        code, output = self.run_setup(game_path=self.game, steam_path="relative/unused")
        self.assertEqual(code, 0, output)
        self.assertEqual((self.current / "BUILD.txt").read_text().strip(), "101")

    def test_libraryfolders_discovers_separate_game_library(self):
        steam_root = self.root / "Steam client"
        steamapps = steam_root / "steamapps"
        steamapps.mkdir(parents=True)
        library = str(self.game.parents[2]).replace("\\", "\\\\")
        (steamapps / "libraryfolders.vdf").write_text(
            f'"libraryfolders" {{ "0" {{ "path" "{library}" }} }}', encoding="utf-8")
        code, output = self.run_setup(steam_path=steam_root)
        self.assertEqual(code, 0, output)
        self.assertEqual((self.current / "BUILD.txt").read_text().strip(), "101")

    def test_unknown_build_does_not_skip_unknown_snapshot(self):
        self.prepare_current(build="unknown")
        (self.game.parents[1] / "appmanifest_322330.acf").unlink()
        code, output = self.run_setup()
        self.assertEqual(code, 0, output)
        self.assertNotIn("[Skip]", output)
        self.assertEqual((self.current / "BUILD.txt").read_text().strip(), "unknown")
        self.assertEqual((self.archives / "build-unknown/scripts/class.lua").read_text(),
                         "-- previous snapshot\n")
        self.assert_no_staging()

    @unittest.skipUnless(os.name == "nt" and OTHER_DRIVE_TEMP,
                         "set DST_TEST_OTHER_DRIVE_TEMP to a writable directory on another drive")
    def test_script_and_game_on_different_drives(self):
        other_parent = Path(OTHER_DRIVE_TEMP)
        self.assertTrue(other_parent.is_absolute() and other_parent.is_dir())
        self.assertNotEqual(other_parent.drive.lower(), self.root.drive.lower())
        with tempfile.TemporaryDirectory(prefix="dst-setup-cross-drive-", dir=other_parent) as directory:
            other_root = Path(directory)
            self.game = other_root / "Steam Library/steamapps/common/Don't Starve Together"
            self.game.mkdir(parents=True)
            self.zip = self.game / "data/databundles/scripts.zip"
            self.zip.parent.mkdir(parents=True)
            self.prepare_install("101")
            self.prepare_current()
            self.prepare_install("102")
            game_before = {p.relative_to(other_root): p.read_bytes()
                           for p in other_root.rglob("*") if p.is_file()}
            steam_root = self.root / "Steam client"
            steamapps = steam_root / "steamapps"
            steamapps.mkdir(parents=True)
            library = str(self.game.parents[2]).replace("\\", "\\\\")
            (steamapps / "libraryfolders.vdf").write_text(
                f'"libraryfolders" {{ "0" {{ "path" "{library}" }} }}', encoding="utf-8")

            for location in (self.project, other_root / "knowledge with spaces"):
                with self.subTest(knowledge_drive=location.drive):
                    location.mkdir(parents=True, exist_ok=True)
                    code, output = self.run_setup(knowledge_root=location)
                    self.assertEqual(code, 0, output)
                    current = location / "raw/current"
                    self.assertEqual((current / "BUILD.txt").read_text().strip(), "102")
                    self.assertTrue(all((current / "scripts" / name).is_file() for name in FILES))
                    before = {p.relative_to(current): p.read_bytes()
                              for p in current.rglob("*") if p.is_file()}
                    code, output = self.run_setup(knowledge_root=location, steam_path=steam_root)
                    self.assertEqual(code, 0, output)
                    self.assertIn("[Skip]", output)
                    self.assertEqual(before, {p.relative_to(current): p.read_bytes()
                                              for p in current.rglob("*") if p.is_file()})
                    self.assertEqual(list((location / "raw").glob(".setup-*")), [])

            archived = self.archives / "build-101/scripts/class.lua"
            self.assertEqual(archived.read_text(), "-- previous snapshot\n")
            # Use script-side Steam metadata to extract from the other drive.
            code, output = self.run_setup("-Force", steam_path=steam_root)
            self.assertEqual(code, 0, output)
            self.assertNotIn("[Skip]", output)
            self.assertTrue((self.archives / "build-102/scripts/class.lua").is_file())
            self.assert_no_staging()
            self.assertEqual(game_before, {p: (other_root / p).read_bytes() for p in game_before})


if __name__ == "__main__":
    unittest.main()
