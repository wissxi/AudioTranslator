# Third-party notices

AudioTranslator is MIT-licensed. It builds on the projects below; their licenses apply to their code.

| Project | Used for | License |
| --- | --- | --- |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | Speech recognition | MIT |
| [OpenAI Whisper](https://github.com/openai/whisper) models | Recognition models (downloaded at runtime) | MIT |
| [CTranslate2](https://github.com/OpenNMT/CTranslate2) | Model inference | MIT |
| [PyAV](https://github.com/PyAV-Org/PyAV) | Audio decoding | BSD-3-Clause |
| [FFmpeg](https://ffmpeg.org) (bundled inside the PyAV wheels) | Audio and video codecs | LGPL-2.1+ / GPL-2.0+ |
| [ONNX Runtime](https://github.com/microsoft/onnxruntime) | Silence detection (Silero VAD) | MIT |
| [Silero VAD](https://github.com/snakers4/silero-vad) | Silence detection model | MIT |
| [Hugging Face Hub](https://github.com/huggingface/huggingface_hub), [tokenizers](https://github.com/huggingface/tokenizers) | Model download, tokenization | Apache-2.0 |
| [NumPy](https://numpy.org) | Audio arrays | BSD-3-Clause |
| [pywebview](https://github.com/r0x0r/pywebview) | Native window | BSD-3-Clause |
| [deep-translator](https://github.com/nidhaloff/deep-translator) | Google Translate client | MIT |
| [Requests](https://github.com/psf/requests) | HTTP | Apache-2.0 |
| [Onest](https://github.com/simpals/onest) | Interface font | SIL Open Font License 1.1 (`src/audiotranslator/web/assets/fonts/OFL.txt`) |
| [Lucide](https://lucide.dev) | Interface icons | ISC |

## FFmpeg in the Windows builds

The Windows installer and portable zip include FFmpeg libraries exactly as shipped in the official PyAV wheels from PyPI. That FFmpeg build contains GPL-licensed components (for example x264 and x265), so the binary distribution as a whole is covered by the GNU GPL. The complete source code of AudioTranslator is in this repository; FFmpeg sources are available at <https://ffmpeg.org/download.html>, and the build scripts PyAV uses are at <https://github.com/PyAV-Org/pyav-ffmpeg>.
