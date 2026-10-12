"""Démarrage sous surveillance : environnement hérité, journal, fenêtre qui n'apparaît pas.

DestriPDF est souvent lancé par une autre application (DestriCenter ouvre les
fiches techniques par le shell Windows). Il hérite alors de son environnement,
dont les dossiers temporaires PyInstaller (`_MEI…`) qu'elle ajoute au PATH. Le
12 octobre 2026, une instance lancée ainsi est restée sans fenêtre, WebView2 en
attente : si la fenêtre n'apparaît pas à temps, les piles des fils d'exécution
sont écrites pour le diagnostic, puis DestriPDF se relance une fois dans un
environnement nettoyé avec un dossier WebView2 de secours ; en dernier recours,
un message explique quoi faire et le processus se termine, au lieu de rester
ouvert sans fenêtre.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import faulthandler
import os
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path

WINDOW_TIMEOUT = 20.0  # secondes ; la fenêtre apparaît d'ordinaire en moins de 2 s
RELAUNCHED = "DESTRIPDF_RELAUNCHED"
_FOREIGN_EXTRACTION = re.compile(r"[\\/]_MEI\d+([\\/]|$)", re.IGNORECASE)
_WEBVIEW2_CLIENT = r"Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def clean_path(value: str) -> tuple[str, list[str]]:
    """PATH sans les dossiers d'extraction PyInstaller d'une autre application
    (DestriPDF est en mode dossier : aucun `_MEI…` ne lui appartient)."""
    kept, removed = [], []
    for entry in value.split(os.pathsep):
        if entry and _FOREIGN_EXTRACTION.search(entry):
            removed.append(entry)
        elif entry:
            kept.append(entry)
    return os.pathsep.join(kept), removed


def relaunch_environment(environ: Mapping[str, str]) -> dict[str, str]:
    """Environnement d'une relance : sans les variables du chargeur PyInstaller ni
    les réglages Python/pythonnet hérités, PATH nettoyé, relance marquée."""
    dropped = {"_MEIPASS2", "PYTHONHOME", "PYTHONPATH", "PYTHONNET_RUNTIME", "PYTHONNET_PYDLL"}
    env = {k: v for k, v in environ.items() if not k.upper().startswith("_PYI_") and k.upper() not in dropped}
    path_key = next((k for k in env if k.upper() == "PATH"), "PATH")
    env[path_key] = clean_path(env.get(path_key, ""))[0]
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    env[RELAUNCHED] = "1"
    return env


def relaunch_command(argv: list[str]) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, *argv]
    return [sys.executable, "-m", "destripdf", *argv]


def relaunch(argv: list[str]) -> bool:
    """Nouvelle instance détachée, hors de l'objet tâche du lanceur si Windows le permet."""
    detached = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    breakaway = 0x01000000  # CREATE_BREAKAWAY_FROM_JOB
    for flags in (detached | breakaway, detached):
        try:
            subprocess.Popen(relaunch_command(argv), env=relaunch_environment(os.environ), creationflags=flags, close_fds=True)
            return True
        except OSError:
            continue
    return False


class _ProcessEntry(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wt.DWORD), ("szExeFile", ctypes.c_wchar * 260),
    ]


def parent_process_name() -> str:
    """Nom du programme qui a lancé DestriPDF (explorer.exe, DestriCenter.exe…)."""
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
        kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE
        for name in ("Process32FirstW", "Process32NextW"):
            getattr(kernel32, name).argtypes = [wt.HANDLE, ctypes.POINTER(_ProcessEntry)]
        kernel32.CloseHandle.argtypes = [wt.HANDLE]
        snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
        if not snapshot or snapshot == wt.HANDLE(-1).value:
            return "inconnu"
        try:
            names, parents = {}, {}
            entry = _ProcessEntry()
            entry.dwSize = ctypes.sizeof(_ProcessEntry)
            ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while ok:
                names[entry.th32ProcessID] = entry.szExeFile
                parents[entry.th32ProcessID] = entry.th32ParentProcessID
                ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
            return names.get(parents.get(os.getpid(), 0), "inconnu")
        finally:
            kernel32.CloseHandle(snapshot)
    except Exception:  # noqa: BLE001 - diagnostic seulement
        return "inconnu"


def webview2_version() -> str:
    try:
        import winreg
    except ImportError:  # pragma: no cover - hors Windows
        return "inconnue"
    for root, key in (
        (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\WOW6432Node\\" + _WEBVIEW2_CLIENT),
        (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\" + _WEBVIEW2_CLIENT),
        (winreg.HKEY_CURRENT_USER, "Software\\" + _WEBVIEW2_CLIENT),
    ):
        try:
            with winreg.OpenKey(root, key) as handle:
                value, _kind = winreg.QueryValueEx(handle, "pv")
                if value and value != "0.0.0.0":
                    return str(value)
        except OSError:
            continue
    return "absente"


def dump_threads(directory: Path, header: str) -> Path:
    """Piles de tous les fils d'exécution (où la fenêtre est bloquée) dans un fichier."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"blocage-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}.txt"
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(header.rstrip() + "\n\n")
        handle.flush()
        faulthandler.dump_traceback(file=handle, all_threads=True)
    return path


def show_error(message: str) -> None:
    """Message natif, sans dépendre de la fenêtre qui ne s'affiche pas."""
    try:
        flags = 0x00000030 | 0x00010000 | 0x00040000  # MB_ICONWARNING | MB_SETFOREGROUND | MB_TOPMOST
        ctypes.windll.user32.MessageBoxW(None, message, "DestriPDF", flags)
    except Exception:  # noqa: BLE001 - pas d'interface : le journal suffit
        pass


class StartupWatchdog:
    """Appelle `on_timeout` si la fenêtre n'est pas affichée dans le délai."""

    def __init__(self, timeout: float, on_timeout: Callable[[], None]):
        self.timeout = timeout
        self._on_timeout = on_timeout
        self._shown = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._watch, name="destripdf-surveillance", daemon=True).start()

    def shown(self) -> None:
        self._shown.set()

    def _watch(self) -> None:
        if not self._shown.wait(self.timeout):
            self._on_timeout()
