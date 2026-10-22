import pathlib
import unittest

class BrandingTests(unittest.TestCase):
    def test_legacy_product_name_removed_from_python_filenames(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        self.assertFalse([p.name for p in (root / 'src').glob('*.py') if 'hte' in p.name.lower()])

if __name__ == '__main__': unittest.main()
