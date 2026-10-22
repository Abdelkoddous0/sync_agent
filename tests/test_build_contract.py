"""Build-contract checks; Windows CI must execute pytest-style safety tests."""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]

class BuildContractTests(unittest.TestCase):
    def test_build_runs_full_suite_before_packaging(self):
        text=(ROOT/'build.bat').read_text()
        self.assertIn('-m pytest tests -q',text)
        self.assertLess(text.index('-m pytest tests -q'),text.index('-m PyInstaller'))
        self.assertIn('requirements-dev.txt',text)

    def test_ci_installs_and_runs_full_suite(self):
        text=(ROOT/'.github/workflows/windows.yml').read_text()
        self.assertIn('pip install -r requirements-dev.txt',text)
        self.assertIn('-m pytest tests -q',text)
        self.assertNotIn('hte',text.lower())
