# Contributing

Thanks for helping! Bug reports, ideas and pull requests are all welcome.

## Setup

```bash
git clone https://github.com/wissxi/AudioTranslator.git
cd AudioTranslator
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Run the app with `audiotranslator`, the CLI with `audiotranslator-cli --help`.

## Before opening a pull request

```bash
python -m pytest                  # fast tests, no downloads
python -m pytest --slow           # real recognition with Whisper tiny (downloads ~75 MB once)
ruff check src tests
ruff format src tests
```

## How the code is organised

- `core/` has no GUI code. `Pipeline.run()` takes a list of files and options and reports everything through `emit(event)` callbacks. The CLI prints those events; the desktop app forwards them to the page as JSON.
- `app.py` exposes the `Bridge` class to JavaScript (`window.pywebview.api.*`). Only public methods are reachable from the page.
- `web/` is plain HTML, CSS and JavaScript with no build step. Strings live in `web/i18n.js` (Russian and English); add both when you add one.

## Working on the interface

You do not need Python or a model to work on the UI:

```bash
python -m http.server 8000 -d src/audiotranslator/web
```

Open `http://localhost:8000/?demo`. `mock.js` imitates the backend; add `=processing` or `=done` for ready-made states, `&lang=en` and `&theme=light` to switch language and theme. Please check both themes and a narrow window (around 900 px) before sending UI changes.

## Releases

1. Update `__version__` in `src/audiotranslator/__init__.py` and add a section to `CHANGELOG.md`.
2. Tag the commit: `git tag v2.1.0 && git push --tags`.
3. GitHub Actions builds the installer and portable zip, runs the self-test and publishes the release with the changelog section as notes.
