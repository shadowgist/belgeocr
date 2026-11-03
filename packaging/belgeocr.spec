# PyInstaller spec: pyinstaller packaging/belgeocr.spec
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH).parent

a = Analysis(
    [str(root / "run_belgeocr.py")],
    pathex=[str(root)],
    datas=[(str(root / "belgeocr" / "resources"), "resources")] + collect_data_files("qtawesome"),
    hiddenimports=["qtpy", "PySide6.QtSvg"],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtQml", "PySide6.QtQuick",
              "PySide6.Qt3DCore", "PySide6.QtMultimedia", "matplotlib", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BelgeOCR",
    console=False,
    icon=str(root / "packaging" / "icon.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="BelgeOCR")
