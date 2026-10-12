"""Run offline regression tests, including Windows spawn integration tests."""
import os
from pathlib import Path
import unittest

if __name__ == '__main__':
    suite = unittest.defaultTestLoader.discover(str(Path(__file__).parent), pattern='test_*.py')
    # Discovery loads the host .env through tunnel configuration. Override only
    # after discovery so tests never send transactions or load the LAYA model.
    os.environ['LAYA_MODE'] = 'heuristic'
    os.environ['POLYGON_MODE'] = 'simulation'
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    raise SystemExit(not result.wasSuccessful())
