"""Static guard against dropped imports (undefined names).

The package split has twice lost module imports during refactors, leaving
NameError crashes on runtime paths that the functional tests never exercise
(e.g. `import math` missing from a module that only uses it inside one draw
method). This test statically scans every module in the `hellcats` package
and fails on any undefined name, catching that whole class of regression
before it reaches a player.
"""
import glob
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "hellcats")


class TestNoUndefinedNames(unittest.TestCase):
    def test_package_has_no_undefined_names(self):
        try:
            from pyflakes.api import check
            from pyflakes.reporter import Reporter
        except ImportError:
            self.skipTest("pyflakes not installed")

        import io

        out, err = io.StringIO(), io.StringIO()
        reporter = Reporter(out, err)

        offenders = []
        for path in sorted(glob.glob(os.path.join(PKG, "*.py"))):
            with open(path, encoding="utf-8") as f:
                source = f.read()
            local_out = io.StringIO()
            check(source, path, Reporter(local_out, local_out))
            for line in local_out.getvalue().splitlines():
                if "undefined name" in line:
                    offenders.append(line)

        self.assertEqual(
            offenders, [],
            "Undefined names found (likely a dropped import):\n"
            + "\n".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
