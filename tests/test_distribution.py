"""Smoke tests for built distributions and installed console commands."""

import hashlib
import configparser
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile


MODULES = {
    "aventures2rst.py", "findpenguins.py", "aventures_archive.py",
    "aventures_writers.py", "common_archive.py", "common_config.py", "common_elevation.py",
    "common_profiles.py", "common_utils.py", "common_writers.py",
    "findpenguins_config.py", "findpenguins_parsers.py", "findpenguins_utils.py",
    "output_safety.py", "polarsteps.py", "polarsteps_config.py", "polarsteps_parsers.py",
    "polarsteps_utils.py", "reminder.py", "reminders2rst.py", "scrapers.py",
}
COMMANDS = ("findpenguins", "polarsteps", "aventures2rst", "reminder", "reminders2rst")


class DistributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wheel = Path(os.environ["SCRAPERS_TEST_WHEEL"]).resolve()
        cls.sdist = Path(os.environ["SCRAPERS_TEST_SDIST"]).resolve()
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.env_dir = cls.root / "venv"
        subprocess.run(
            [sys.executable, "-m", "venv", str(cls.env_dir)],
            check=True,
        )
        cls.bin_dir = cls.env_dir / ("Scripts" if os.name == "nt" else "bin")
        python = cls.bin_dir / ("python.exe" if os.name == "nt" else "python")
        subprocess.run(
            [str(python), "-m", "pip", "install", str(cls.wheel)],
            check=True, cwd=cls.root,
        )
        subprocess.run([str(python), "-m", "pip", "check"], check=True, cwd=cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_command(self, command, *args, check=True):
        executable = self.bin_dir / (command + (".exe" if os.name == "nt" else ""))
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        result = subprocess.run(
            [str(executable), *map(str, args)], cwd=self.root, env=env,
            text=True, capture_output=True,
        )
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_artifacts_contain_modules_without_private_files(self):
        with zipfile.ZipFile(self.wheel) as archive:
            wheel_files = set(archive.namelist())
            entry_points = next(name for name in wheel_files if name.endswith(".dist-info/entry_points.txt"))
            metadata = configparser.ConfigParser()
            metadata.read_string(archive.read(entry_points).decode("utf-8"))
            self.assertEqual(dict(metadata["console_scripts"]), {"scrapers": "scrapers:main"})
        with tarfile.open(self.sdist, "r:gz") as archive:
            source_files = {name.split("/", 1)[-1] for name in archive.getnames()}
        for files in (wheel_files, source_files):
            self.assertTrue(MODULES <= files, MODULES - files)
            self.assertFalse({
                "findpenguins_archive.py", "findpenguins_elevation.py", "findpenguins_writers.py",
            } & files)
            self.assertFalse(any(Path(name).name.startswith("fp_") for name in files))
            self.assertNotIn("profiles.json", files)
            self.assertNotIn("franklin.json", files)

    def test_all_commands_show_help_outside_checkout(self):
        result = self.run_command("scrapers", "--help")
        no_command = self.run_command("scrapers")
        self.assertEqual(no_command.stdout, result.stdout)
        self.assertEqual(no_command.stderr, "")
        for command in COMMANDS:
            self.assertIn(command, result.stdout)
        for command in COMMANDS:
            with self.subTest(command=command):
                result = self.run_command("scrapers", command, "--help")
                self.assertIn("usage:", result.stdout.lower())
                self.assertIn("scrapers " + command, result.stdout)

    def test_module_invocation_and_invalid_commands(self):
        python = self.bin_dir / ("python.exe" if os.name == "nt" else "python")
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        result = subprocess.run(
            [str(python), "-m", "scrapers", "reminders2rst", "--help"],
            cwd=self.root, env=env, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--output", result.stdout)
        for args in (("invalid",), ("--unknown",), ("reminder", "--unknown")):
            with self.subTest(args=args):
                result = self.run_command("scrapers", *args, check=False)
                self.assertEqual(result.returncode, 2)
                self.assertIn("error:", result.stderr)

    def test_subcommand_argument_forwarding(self):
        python = self.bin_dir / ("python.exe" if os.name == "nt" else "python")
        code = """
import sys
from unittest.mock import patch
import scrapers

cases = [
    (["findpenguins", "profiles.json", "--output", "archive", "-t", "trip", "--force", "--skip"],
     "findpenguins.scrapper", ("profiles.json", "archive", "trip", True, True)),
    (["findpenguins", "profiles.json"],
     "findpenguins.scrapper", ("profiles.json", "output", None, False, False)),
    (["polarsteps", "profiles.json", "--output", "archive", "-t", "trip", "--force", "--skip"],
     "polarsteps.scrape_profiles", ("profiles.json", "archive", "trip"), {"force": True, "skip": True}),
    (["aventures2rst", "--output", "archive", "--content", "articles", "-t", "trip"],
     "aventures2rst.convert", ("archive", "articles", "trip", "findpenguins")),
    (["aventures2rst", "--output", "archive", "--content", "articles", "--category", "polarsteps"],
     "aventures2rst.convert", ("archive", "articles", None, "polarsteps")),
    (["reminder", "--list", "Trips", "--output", "archive", "--all", "--force"],
     "reminder.export_reminders", ("archive", "Trips", True, True)),
    (["reminders2rst", "--output", "archive", "--content", "articles"],
     "reminders2rst.convert", ("archive", "articles")),
]
for case in cases:
    arguments, target, expected = case[:3]
    keywords = case[3] if len(case) > 3 else {}
    with patch.object(sys, "argv", ["scrapers", *arguments]), patch(target) as called:
        scrapers.main()
        called.assert_called_once_with(*expected, **keywords)
"""
        result = subprocess.run(
            [str(python), "-I", "-c", code], cwd=self.root, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_reminder_commands(self):
        output = self.root / "reminders"
        result = self.run_command("scrapers", "reminder", "--list", "Trips", "--output", output)
        self.assertIn("rem export", result.stdout)
        (output / "reminders.json").write_text(
            json.dumps([{"id": "test-id", "name": "Pack", "body": "Bring a map"}]),
            encoding="utf-8",
        )
        content = self.root / "reminder-articles"
        self.run_command("scrapers", "reminders2rst", "--output", output, "--content", content)
        slug = "reminder-" + hashlib.sha256(b"test-id").hexdigest()
        article = (content / (slug + ".rst")).read_text(encoding="utf-8")
        self.assertIn(":Title: Pack", article)
        self.assertIn("Bring a map", article)

    def test_force_still_protects_working_directory(self):
        result = self.run_command(
            "scrapers", "reminder", "--list", "Trips", "--output", self.root, "--force", check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Refusing to clear", result.stderr)

    def test_findpenguins_reports_missing_profiles(self):
        result = self.run_command("scrapers", "findpenguins", "missing.json", "--skip", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing.json", result.stderr)

    def test_aventures_converter(self):
        archive = self.root / "archive"
        trip_dir = archive / "traveller" / "journey"
        trip_dir.mkdir(parents=True)
        (trip_dir.parent / "profile.json").write_text(json.dumps({
            "version": 1, "user": {"uid": "traveller", "name": "Traveller"},
            "sizes": {"small": 128, "large": 1600},
        }), encoding="utf-8")
        (trip_dir / "trip.json").write_text(json.dumps({
            "version": 1, "trip": {
                "slug": "journey", "title": "Journey",
                "footprints": [{"title": "Stop", "text": "A stop", "country": "France"}],
            },
        }), encoding="utf-8")
        content = self.root / "trip-articles"
        self.run_command("scrapers", "aventures2rst", "--output", archive, "--content", content)
        trip_dir = content / "traveller" / "journey"
        article = (trip_dir / "trip.rst").read_text(encoding="utf-8")
        self.assertIn(":Title: Journey", article)
        self.assertIn(":Category: findpenguins", article)
        self.assertIn(":Tags: findpenguins, trip", article)
        self.assertIn(":Author: Traveller", article)
        footprint = (trip_dir / "footprint_1" / "footprint.rst").read_text(encoding="utf-8")
        self.assertIn(":Tags: findpenguins, footprint, France", footprint)
        self.assertIn(":Author: Traveller", footprint)

        polarsteps_content = self.root / "polarsteps-articles"
        self.run_command(
            "scrapers", "aventures2rst", "--output", archive, "--content", polarsteps_content,
            "--category", "polarsteps",
        )
        polarsteps_trip_dir = polarsteps_content / "traveller" / "journey"
        polarsteps_article = (polarsteps_trip_dir / "trip.rst").read_text(encoding="utf-8")
        self.assertIn(":Category: polarsteps", polarsteps_article)
        self.assertIn(":Tags: polarsteps, trip", polarsteps_article)
        self.assertIn(":Author: Traveller", polarsteps_article)
        polarsteps_footprint = (
            polarsteps_trip_dir / "footprint_1" / "footprint.rst"
        ).read_text(encoding="utf-8")
        self.assertIn(":Tags: polarsteps, footprint, France", polarsteps_footprint)
        self.assertIn(":Author: Traveller", polarsteps_footprint)

        result = self.run_command(
            "scrapers", "aventures2rst", "--output", archive, "--content", content, "--trip", "missing",
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No archived trip found", result.stderr)

    def test_polarsteps_measurements_are_whole_numbers(self):
        python = self.bin_dir / ("python.exe" if os.name == "nt" else "python")
        code = """
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

import common_writers
import polarsteps
from common_utils import gpx_tag

source = {
    "total_km": 12.6,
    "steps": [{
        "id": 12, "type": 1, "start_time": "2024-05-01T10:00:00+00:00",
        "weather_temperature": 18.6, "location": {"lat": 45.7, "lon": 4.8},
    }],
    "zelda_steps": [{"location": {"lat": 45.7, "lon": 4.8}}],
}
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    trip = polarsteps.normalize_trip(source, "owner", "42-trip", root, False)
    assert trip["distance"] == 13
    assert trip["footprints"][0]["temperature"] == 19
    serialized = polarsteps._stringify_trip_numbers(trip)
    assert serialized["distance"] == "13"
    assert serialized["footprints"][0]["temperature"] == "19"

    gpx = root / "trip.gpx"
    polarsteps.seed_gpx(gpx, source)
    with patch("common_writers.fetch_elevations",
               side_effect=lambda points: points[0].update(ele=123.6)):
        common_writers.build_trip_gpx(
            str(gpx), {}, trip, trip["footprints"], integer_elevation=True
        )
    document = ET.parse(gpx).getroot()
    trackpoint = document.find(f".//{gpx_tag('trkpt')}")
    waypoint = document.find(gpx_tag("wpt"))
    assert trackpoint.findtext(gpx_tag("ele")) == "124"
    assert waypoint.findtext(gpx_tag("ele")) == "124"
    extensions = waypoint.find(gpx_tag("extensions"))
    assert extensions.find(gpx_tag("temperature")).text == "19"
    assert extensions.find(gpx_tag("point")).get("ele") == "124"
"""
        result = subprocess.run(
            [str(python), "-c", code], cwd=self.root, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class CompanionPictureTests(unittest.TestCase):
    def test_owner_picture_uses_profile_directory_case(self):
        from PIL import Image

        from aventures2rst import convert

        for owner_uid in ("Dburais", "dburais"):
            with self.subTest(owner_uid=owner_uid), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                profile_dir = root / "archive" / "dburais"
                trip_dir = profile_dir / "journey"
                trip_dir.mkdir(parents=True)
                (profile_dir / "profile.json").write_text(json.dumps({
                    "version": 1, "user": {"uid": "dburais", "name": "Owner"},
                    "sizes": {"small": 128, "large": 1600},
                }), encoding="utf-8")
                for picture in ("owner.webp", "buddy.webp"):
                    Image.new("RGB", (4, 4), "red").save(profile_dir / picture)
                (trip_dir / "trip.json").write_text(json.dumps({
                    "version": 1, "trip": {
                        "slug": "journey", "title": "Journey", "footprints": [],
                        "companions": [
                            {"uid": owner_uid, "name": "Owner", "picture": "owner.webp"},
                            {"uid": "Buddy", "name": "Buddy", "picture": "buddy.webp"},
                        ],
                    },
                }), encoding="utf-8")

                content = root / "content"
                convert(str(root / "archive"), str(content), category="polarsteps")
                article = (content / "dburais" / "journey" / "trip.rst").read_text(encoding="utf-8")
                self.assertIn(":Companions: Owner|../owner.webp;Buddy|../../Buddy/buddy.webp", article)
                self.assertTrue((content / "dburais" / "owner.webp").is_file())
                self.assertTrue((content / "Buddy" / "buddy.webp").is_file())


class PolarstepsFootprintAltitudeTests(unittest.TestCase):
    def test_enriched_elevation_is_saved_in_manifest_and_article(self):
        import xml.etree.ElementTree as ET
        from unittest.mock import patch

        from aventures2rst import convert
        from common_utils import gpx_tag
        from polarsteps import scrape

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "archive"
            profile_dir = archive / "traveller"
            trip_dir = profile_dir / "42-journey"
            trip_dir.mkdir(parents=True)
            (profile_dir / "api-user.json").write_text(json.dumps({
                "first_name": "Traveller",
                "alltrips": [{"id": 42, "slug": "journey"}],
            }), encoding="utf-8")
            (trip_dir / "api-trip.json").write_text(json.dumps({
                "id": 42,
                "steps": [
                    {"id": 1, "type": 1},
                    {"id": 2, "type": 1, "location": {"lat": 45, "lon": 4}},
                    {"id": 3, "type": 1, "location": {"lat": 46, "lon": 4}},
                    {"id": 4, "type": 1, "location": {"lat": 47, "lon": 4}},
                ],
                "zelda_steps": [
                    {"location": {"lat": 45, "lon": 4}},
                    {"location": {"lat": 46, "lon": 4}},
                    {"location": {"lat": 47, "lon": 4}},
                ],
            }), encoding="utf-8")

            def elevations(points):
                points[0]["ele"] = 123.6
                points[1]["ele"] = 0

            with patch("polarsteps.download_country_flags", return_value={}), \
                 patch("polarsteps.save_trip_route_map", return_value=None), \
                 patch("common_writers.fetch_elevations", side_effect=elevations):
                scrape("traveller", str(archive), skip=True)

            trip = json.loads((trip_dir / "trip.json").read_text(encoding="utf-8"))["trip"]
            self.assertEqual(
                [footprint["altitude"] for footprint in trip["footprints"]],
                ["", "124", "0", ""],
            )
            gpx = ET.parse(profile_dir / "42-journey.gpx").getroot()
            self.assertEqual(
                [waypoint.findtext(gpx_tag("ele")) for waypoint in gpx.findall(gpx_tag("wpt"))],
                ["124", "0", None],
            )
            with patch("aventures_writers.save_full_country_map", return_value=None), \
                 patch("aventures_writers.shrink_image"):
                convert(str(archive), str(root / "content"), category="polarsteps")
            article = (root / "content" / "traveller" / "42-journey" / "footprint_2" / "footprint.rst")
            self.assertIn(":Ele: 124", article.read_text(encoding="utf-8"))


class WaypointAltitudeTests(unittest.TestCase):
    def test_existing_altitude_is_written_without_a_track(self):
        import xml.etree.ElementTree as ET

        from common_utils import gpx_tag
        from common_writers import build_trip_gpx

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trip.gpx"
            build_trip_gpx(
                str(path), {}, {},
                [{"lat": "45", "lon": "4", "altitude": 0}],
                enrich_elevation=False,
            )
            waypoint = ET.parse(path).getroot().find(gpx_tag("wpt"))
            self.assertEqual(waypoint.findtext(gpx_tag("ele")), "0")
            self.assertEqual(
                waypoint.findtext(f"{gpx_tag('extensions')}/{gpx_tag('altitude')}"), "0",
            )

    def test_track_elevation_fills_missing_altitude_without_overwriting_existing(self):
        import xml.etree.ElementTree as ET

        from common_utils import gpx_tag
        from common_writers import build_trip_gpx

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trip.gpx"
            root = ET.Element(gpx_tag("gpx"))
            segment = ET.SubElement(ET.SubElement(root, gpx_tag("trk")), gpx_tag("trkseg"))
            point = ET.SubElement(segment, gpx_tag("trkpt"), lat="45", lon="4")
            ET.SubElement(point, gpx_tag("ele")).text = "123.6"
            ET.SubElement(segment, gpx_tag("trkpt"), lat="46", lon="4")
            ET.ElementTree(root).write(path)
            footprints = [
                {"lat": "45", "lon": "4", "date": "2024-01-01"},
                {"lat": "45", "lon": "4", "altitude": 50},
                {"lat": "46", "lon": "4"},
            ]
            build_trip_gpx(
                str(path), {}, {}, footprints,
                enrich_elevation=False, integer_elevation=True,
            )
            self.assertNotIn("altitude", footprints[0])
            waypoints = ET.parse(path).getroot().findall(gpx_tag("wpt"))
            for waypoint, expected in zip(waypoints, ("124", "50")):
                self.assertEqual(waypoint.findtext(gpx_tag("ele")), expected)
                self.assertEqual(
                    waypoint.findtext(f"{gpx_tag('extensions')}/{gpx_tag('altitude')}"), expected,
                )
            self.assertIsNone(waypoints[2].findtext(gpx_tag("ele")))
            self.assertIsNone(
                waypoints[2].findtext(f"{gpx_tag('extensions')}/{gpx_tag('altitude')}"),
            )
            build_trip_gpx(
                str(path), {}, {}, footprints,
                enrich_elevation=False, integer_elevation=True, update_footprint_altitudes=True,
            )
            self.assertEqual(footprints[0]["altitude"], 124)
            self.assertEqual(footprints[1]["altitude"], 50)
            self.assertNotIn("altitude", footprints[2])


if __name__ == "__main__":
    unittest.main()
