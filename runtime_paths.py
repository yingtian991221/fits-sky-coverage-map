"""Keep mutable state outside a frozen executable's bundled resources."""
import os
import sys
from pathlib import Path

ASSETS = Path(__file__).resolve().parent
BASE = Path(os.environ.get('FITS_SKY_HOME') or (Path(sys.executable).parent if getattr(sys, 'frozen', False) else ASSETS)).resolve()
