"""``python -m audiotranslator`` opens the app; with arguments it runs the CLI."""

import sys


def run() -> int:
    if len(sys.argv) > 1:
        from .cli import main as cli_main

        return cli_main()
    from .app import main as gui_main

    return gui_main()


if __name__ == "__main__":
    sys.exit(run())
