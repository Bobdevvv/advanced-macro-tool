"""The pieces a published release depends on: icon, version, build spec, workflow."""
from __future__ import annotations

import os
import re
import struct
import unittest

from tests import support

from src import app_paths, brand

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


class TestRelease(unittest.TestCase):
    def test_version_is_three_numbers(self):
        self.assertRegex(brand.VERSION, r"^\d+\.\d+\.\d+$")

    def test_icon_has_every_windows_size(self):
        path = app_paths.icon_file()
        with open(path, "rb") as f:
            data = f.read()
        reserved, kind, count = struct.unpack_from("<HHH", data)
        self.assertEqual((reserved, kind), (0, 1))
        sizes = {data[6 + 16 * i] or 256 for i in range(count)}
        self.assertTrue({16, 24, 32, 48, 256} <= sizes, sizes)

    def test_logo_draws_at_every_size_and_shows_in_the_sidebar(self):
        support.qapp()
        support.stub_global_input()          # never install real input hooks
        from src.ui import logo
        from src.ui.main_window import MainWindow
        for size in (16, 32, 256):
            img = logo.image(size)
            centre = img.pixelColor(size // 2, size // 2)
            self.assertEqual(centre.alpha(), 255, size)          # tile is opaque
            self.assertEqual(img.pixelColor(0, 0).alpha(), 0, size)  # corners round
        w = MainWindow()
        try:
            marks = w.findChildren(logo.LogoMark)
            self.assertEqual(len(marks), 1)
            self.assertFalse(marks[0].grab().isNull())
        finally:
            w._hotkeys.stop()
            w.close()

    def test_pointer_is_symmetric_with_the_key_on_its_axis(self):
        import math
        from src.ui import logo
        # The key is centred on x = 0 of the head's own frame, the axis
        # through the tip and the middle of the base; the head is symmetric.
        self.assertGreater(logo.HEAD_HALF_W, 0)
        self.assertLess(logo.KEY_W, 2 * logo.HEAD_HALF_W)
        # Tilted by its half-angle, the head's left edge stands upright.
        t = math.radians(logo.AXIS_TILT)
        x, y = -logo.HEAD_HALF_W, logo.HEAD_H
        self.assertAlmostEqual(x * math.cos(t) + y * math.sin(t), 0, places=6)

    def test_app_uses_the_icon(self):
        from PyQt6.QtGui import QIcon
        import main
        app = support.qapp()
        before = app.windowIcon()
        try:
            main.setup_app(app)
            self.assertFalse(app.windowIcon().isNull())
            self.assertEqual(app.applicationVersion(), brand.VERSION)
        finally:
            app.setWindowIcon(before if not before.isNull() else QIcon())

    def test_spec_bundles_what_the_app_reads(self):
        spec = _read("build.spec")
        for needed in ("assets/fonts", "assets/amt.ico", "docs/GUIDE.md", "docs/images"):
            self.assertIn(f"'{needed}'", spec)
        self.assertIn("name=brand.APP_SHORT", spec)
        self.assertIn("icon='assets/amt.ico'", spec)

    def test_release_uploads_the_exe_the_spec_builds(self):
        wf = _read(".github", "workflows", "release.yml")
        exe = f"{brand.APP_SHORT}.exe"
        self.assertIn(f"dist/{exe}", wf)
        self.assertIn("unittest discover", wf)          # never ship untested
        self.assertTrue(os.path.isfile(os.path.join(ROOT, ".github", "RELEASE_NOTES.md")))

    def test_readme_links_point_at_this_repository(self):
        readme = _read("README.md")
        for url in re.findall(r"https://github\.com/Bobdevvv/[\w.-]+", readme):
            self.assertTrue(url in (brand.REPO_URL, brand.REPO_URL + ".git")
                            or url.startswith(brand.REPO_URL + "/"), url)
        self.assertIn(brand.REPO_URL + "/releases/latest", readme)


if __name__ == "__main__":
    unittest.main()
