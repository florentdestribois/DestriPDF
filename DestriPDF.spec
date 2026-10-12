# -*- mode: python ; coding: utf-8 -*-
# Exécutable DestriPDF en mode dossier : aucun dépaquetage au lancement, démarrage rapide.
# Construction : .venv\Scripts\python.exe -m PyInstaller DestriPDF.spec --noconfirm

from PyInstaller.utils.hooks import collect_submodules

ROOT = SPECPATH

hiddenimports = (
    collect_submodules("destripdf")
    + collect_submodules("pyhanko.sign")
    + collect_submodules("pyhanko.stamp")
    + collect_submodules("pyhanko.pdf_utils")
    + collect_submodules("pyhanko_certvalidator")
    + collect_submodules("fontTools.subset")
    + [
        "webview.platforms.edgechromium",
        "webview.platforms.winforms",
        "clr_loader",
        "pythonnet",
        "winreg",
    ]
)

a = Analysis(
    [f"{ROOT}\\scripts\\destripdf_launcher.py"],
    pathex=[ROOT],
    binaries=[],
    datas=[(f"{ROOT}\\destripdf\\static", "destripdf\\static")],
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "_tkinter", "pytest", "IPython", "matplotlib", "numpy", "pandas", "PIL", "pydoc_data"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DestriPDF",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=f"{ROOT}\\assets\\destripdf.ico",
    version=f"{ROOT}\\build_version.txt",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="DestriPDF",
)
