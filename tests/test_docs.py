"""The documentation: every link and image must lead somewhere."""
import os
import re
import unittest

from tests import support

DOCS = ("README.md", "CONTRIBUTING.md", "SECURITY.md", "docs/GUIDE.md",
        "docs/TECHNICAL.md", "docs/QA-CHECKLIST.md")


def _anchors(text: str) -> set:
    """GitHub-style heading anchors of a markdown text."""
    return {re.sub(r"[^\w\- ]", "", h.strip().lower()).replace(" ", "-")
            for h in re.findall(r"^#+ (.+)$", text, re.M)}


class Links(unittest.TestCase):
    def test_every_relative_link_and_image_resolves(self):
        broken = []
        for doc in DOCS:
            path = os.path.join(support.ROOT, doc)
            with open(path, encoding="utf-8") as f:
                text = f.read()
            base = os.path.dirname(path)
            for target in re.findall(r"\]\(([^)\s]+)\)", text):
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                file_part, _, frag = target.partition("#")
                if not file_part:
                    if frag not in _anchors(text):
                        broken.append(f"{doc}: #{frag}")
                    continue
                full = os.path.normpath(os.path.join(base, file_part))
                if not os.path.exists(full):
                    broken.append(f"{doc}: {target} (no such file)")
                elif frag and full.endswith(".md"):
                    with open(full, encoding="utf-8") as f:
                        if frag not in _anchors(f.read()):
                            broken.append(f"{doc}: {target} (no such heading)")
        self.assertEqual(broken, [])

    def test_every_screenshot_is_used(self):
        """No stale images: each file in docs/images appears in some doc."""
        texts = ""
        for doc in DOCS:
            with open(os.path.join(support.ROOT, doc), encoding="utf-8") as f:
                texts += f.read()
        images = os.listdir(os.path.join(support.ROOT, "docs", "images"))
        unused = [i for i in images if f"images/{i}" not in texts]
        self.assertEqual(unused, [])

    def test_screenshot_script_still_produces_every_image(self):
        """scripts/docs_screenshots.py must keep working as the UI changes;
        it runs into a temporary folder, never over docs/images."""
        import subprocess
        import sys
        import tempfile
        out = tempfile.mkdtemp(dir=support.fresh_dir("shots"))
        env = dict(os.environ, AMT_SCREENSHOT_DIR=out)
        r = subprocess.run([sys.executable, "-X", "faulthandler",
                            os.path.join(support.ROOT, "scripts", "docs_screenshots.py")],
                           capture_output=True, text=True, env=env, timeout=180)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        produced = set(os.listdir(out))
        published = set(os.listdir(os.path.join(support.ROOT, "docs", "images")))
        self.assertEqual(produced, published)

    def test_hotkey_tables_match_the_real_defaults(self):
        """The documented defaults must be the ones the app uses."""
        from src.defaults import DEFAULT_HOTKEYS
        from src.ui.widgets import pretty_hotkey
        key = {k: "+".join(pretty_hotkey(v)) for k, v in DEFAULT_HOTKEYS.items()}
        rows = {
            "README.md": {"Toggle recording": key["hotkey_record"],
                          "Play / stop macro": key["hotkey_play"],
                          "Toggle autoclicker": key["hotkey_autoclicker"],
                          "Test play the Composer's edit": key["hotkey_test"]},
            "docs/GUIDE.md": {"Start / stop recording": key["hotkey_record"],
                              "Play / stop the loaded macro": key["hotkey_play"],
                              "Start / stop the auto clicker": key["hotkey_autoclicker"],
                              "Play / stop the Composer's edit (Test play)": key["hotkey_test"]},
        }
        for doc, expected in rows.items():
            with open(os.path.join(support.ROOT, doc), encoding="utf-8") as f:
                text = f.read()
            for action, k in expected.items():
                self.assertIn(f"| {action} | {k} |", text, f"{doc}: {action}")

    def test_user_guide_and_technical_docs_are_separate(self):
        with open(os.path.join(support.ROOT, "docs", "GUIDE.md"), encoding="utf-8") as f:
            guide = f.read()
        # Implementation words belong in TECHNICAL.md, not the user guide.
        for word in ("pynput", "PyQt", "_Bridge", "virtual key code", "QScrollArea",
                     "dataclass", "excepthook"):
            self.assertNotIn(word, guide, word)


if __name__ == "__main__":
    unittest.main()
