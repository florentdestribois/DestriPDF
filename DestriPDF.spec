# -*- mode: python ; coding: utf-8 -*-
# Exécutable DestriPDF en mode dossier : aucun dépaquetage au lancement, démarrage rapide.
# Construction : .venv\Scripts\python.exe -m PyInstaller DestriPDF.spec --noconfirm

import os
import ssl

from PyInstaller.utils.hooks import collect_submodules

ROOT = SPECPATH

datas = [(f"{ROOT}\\destripdf\\static", "destripdf\\static")]
# Le runtime Python du poste (Codex, depuis le 25 octobre 2026) a un ssl.py qui
# charge ce fichier, voisin de ssl.py, à chaque contexte SSL : sans lui, l'import
# d'aiohttp échoue dans l'exécutable figé (FileNotFoundError) et la signature avec.
# ssl.py figé : dossier `_internal`.
_rejected_cas = os.path.join(os.path.dirname(ssl.__file__), "codex-rejected-cas.pem")
if os.path.exists(_rejected_cas):
    datas.append((_rejected_cas, "."))

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
    datas=datas,
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
