import shutil
import subprocess
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "Node.js is not installed")
class JavaScriptSyntaxTests(unittest.TestCase):
    def test_browser_scripts_parse(self):
        for relative_path in ("static/app.js", "static/game.js"):
            with self.subTest(script=relative_path):
                result = subprocess.run(
                    [NODE, "--check", str(PROJECT_ROOT / relative_path)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
