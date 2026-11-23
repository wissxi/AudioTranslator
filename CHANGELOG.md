# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [2.0.0] - 2026-11-23

A complete rewrite: new interface, new recognition engine, installer for Windows.

### Added
- Desktop interface built with HTML/CSS in a native window (WebView2 on Windows): file queue, live transcript, original and translation side by side, waveform linked to the text.
- Drag and drop of files and whole folders, with subfolders.
- Automatic detection of the spoken language; 45 languages for recognition and translation.
- Translation through Google Translate, DeepL (API key) or MyMemory, with automatic fallback to another service.
- Export to TXT, SRT, VTT and JSON, plus a combined `translations.txt` report.
- Choice of Whisper model (tiny → large-v3, turbo) with download progress; NVIDIA GPU support with automatic CPU fallback.
- Russian and English interface, light and dark themes, keyboard shortcuts, settings that persist.
- Command-line interface `audiotranslator-cli`.
- Windows installer and portable zip built by GitHub Actions; the build is checked by a self-test that recognizes real speech.
- Test suite (pytest) and continuous integration on Windows, macOS and Linux.

### Changed
- Recognition moved from `openai-whisper` (PyTorch) to `faster-whisper` (CTranslate2): the same models, much faster and lighter, no PyTorch needed.
- Audio is decoded with PyAV, so FFmpeg no longer has to be installed separately.
- Translation moved from the unmaintained `googletrans` to `deep-translator` and direct API clients, with batching that keeps subtitles aligned.

### Fixed
- The interface no longer freezes or crashes while processing (work runs off the UI thread).
- Long texts are no longer cut by translation service limits.

## [1.0.0]

- First version: a CustomTkinter window that transcribed English MP3/MP4 files with Whisper and translated them with googletrans into one text file.

[2.0.0]: https://github.com/wissxi/AudioTranslator/releases/tag/v2.0.0
