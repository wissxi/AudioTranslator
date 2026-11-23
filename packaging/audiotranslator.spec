# PyInstaller build: pyinstaller packaging/audiotranslator.spec --noconfirm
# Produces dist/AudioTranslator/ (one folder: fast start, fewer antivirus false positives).
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = Path(SPECPATH).parent
VERSION = re.search(r'__version__ = "([^"]+)"', (ROOT / "src/audiotranslator/__init__.py").read_text()).group(1)

datas = [(str(ROOT / "src/audiotranslator/web"), "audiotranslator/web")]
datas += collect_data_files("faster_whisper")  # Silero VAD model
binaries = collect_dynamic_libs("ctranslate2")

version_info = None
if sys.platform == "win32":
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
    )

    numbers = tuple(int(x) for x in VERSION.split(".")) + (0,)
    version_info = VSVersionInfo(
        ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
        kids=[
            StringFileInfo([StringTable("040904B0", [
                StringStruct("CompanyName", "wissxi"),
                StringStruct("FileDescription", "AudioTranslator — speech to text and translation"),
                StringStruct("FileVersion", VERSION),
                StringStruct("InternalName", "AudioTranslator"),
                StringStruct("OriginalFilename", "AudioTranslator.exe"),
                StringStruct("ProductName", "AudioTranslator"),
                StringStruct("ProductVersion", VERSION),
                StringStruct("LegalCopyright", "MIT License"),
            ])]),
            VarFileInfo([VarStruct("Translation", [1033, 1200])]),
        ],
    )

a = Analysis(
    [str(ROOT / "packaging/launcher.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=["audiotranslator.cli"],
    excludes=["tkinter", "PIL", "matplotlib", "PyQt5", "PyQt6", "PySide2", "PySide6", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AudioTranslator",
    console=False,
    icon=str(ROOT / "assets/icon.ico"),
    version=version_info,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="AudioTranslator", upx=False)
