"""Entry point used by PyInstaller."""

import sys

from audiotranslator.app import main

if __name__ == "__main__":
    sys.exit(main())
