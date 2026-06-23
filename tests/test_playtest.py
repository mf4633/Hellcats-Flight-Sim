"""Automated playtest checks (pytest wrapper)."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("SDL_VIDEODRIVER", "windib")


class TestPlaytestChecklist(unittest.TestCase):
    def test_all_playtest_checks_pass(self):
        from scripts.playtest_checklist import run_checks
        checks = run_checks()
        failures = [c for c in checks if not c.ok]
        if failures:
            msgs = "\n".join(f"  {c.area}: {c.name} — {c.detail}" for c in failures)
            self.fail(f"{len(failures)} playtest check(s) failed:\n{msgs}")


if __name__ == "__main__":
    unittest.main()