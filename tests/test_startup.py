"""Démarrage sous surveillance : environnement hérité d'un lanceur, fenêtre qui n'apparaît pas."""

import os
import threading
import time

from destripdf import startup

MEI = r"C:\Users\tt\AppData\Local\Temp\_MEI19082"


def test_clean_path_removes_other_app_extraction_dirs():
    value = os.pathsep.join([
        r"C:\Windows\system32",
        MEI + r"\pywin32_system32",
        MEI + r"\webview\lib\runtimes\win-x64\native",
        r"C:\Program Files\DestriPDF\_internal\webview\lib\runtimes\win-x64\native",
        r"C:\Outils\_MEIllEURS",  # pas un dossier d'extraction PyInstaller
        "",
    ])
    cleaned, removed = startup.clean_path(value)
    assert removed == [MEI + r"\pywin32_system32", MEI + r"\webview\lib\runtimes\win-x64\native"]
    assert cleaned.split(os.pathsep) == [
        r"C:\Windows\system32",
        r"C:\Program Files\DestriPDF\_internal\webview\lib\runtimes\win-x64\native",
        r"C:\Outils\_MEIllEURS",
    ]


def test_relaunch_environment_is_clean_and_marked():
    inherited = {
        "Path": os.pathsep.join([r"C:\Windows", MEI + r"\webview"]),
        "_PYI_APPLICATION_HOME_DIR": MEI,
        "_PYI_ARCHIVE_FILE": r"C:\Programmes\DestriCenter.exe",
        "_MEIPASS2": MEI,
        "PYTHONNET_RUNTIME": "coreclr",
        "USERPROFILE": r"C:\Users\tt",
    }
    env = startup.relaunch_environment(inherited)
    assert not any(k.startswith("_PYI_") for k in env) and "_MEIPASS2" not in env and "PYTHONNET_RUNTIME" not in env
    assert env["Path"] == r"C:\Windows"
    assert env["USERPROFILE"] == r"C:\Users\tt"
    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1" and env[startup.RELAUNCHED] == "1"


def test_watchdog_fires_only_when_the_window_never_shows():
    fired = threading.Event()
    stuck = startup.StartupWatchdog(0.2, fired.set)
    stuck.start()
    assert fired.wait(2), "surveillance non déclenchée"

    calls = []
    fine = startup.StartupWatchdog(0.3, lambda: calls.append(1))
    fine.start()
    fine.shown()
    time.sleep(0.6)
    assert not calls


def test_dump_threads_records_every_stack(tmp_path):
    blocker = threading.Event()
    worker = threading.Thread(target=blocker.wait, name="fil-bloque", daemon=True)
    worker.start()
    try:
        path = startup.dump_threads(tmp_path, "DestriPDF : fenêtre non affichée")
    finally:
        blocker.set()
    text = path.read_text(encoding="utf-8")
    assert path.name.startswith("blocage-") and text.startswith("DestriPDF : fenêtre non affichée")
    assert "Current thread 0x" in text and "test_dump_threads_records_every_stack" in text  # fil courant
    assert "Thread 0x" in text.replace("Current thread 0x", "") and "in wait" in text  # et le fil bloqué


def test_launcher_and_webview2_are_described():
    assert startup.parent_process_name() not in ("", None)
    assert isinstance(startup.webview2_version(), str) and startup.webview2_version()


def test_relaunch_command_runs_the_package_from_sources():
    command = startup.relaunch_command(["facture.pdf"])
    assert command[-1] == "facture.pdf"
    assert command[1:3] == ["-m", "destripdf"]  # tests : sources, pas l'exécutable figé
