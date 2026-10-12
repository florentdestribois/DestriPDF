"""Recette de la surveillance du démarrage sur un exécutable (dist ou installé).

Usage : python scripts/recette/surveillance_demarrage.py <DestriPDF.exe> <document.pdf>

Fenêtre volontairement jamais affichée (DESTRIPDF_TEST_STALL_WINDOW), délai court,
PATH pollué comme par DestriCenter : la première instance doit retirer le dossier
étranger, relever ses piles et se relancer ; la relance doit relever ses piles,
afficher le message puis se terminer avec le code 1. Journal et réglages isolés
dans un dossier temporaire : rien n'est écrit dans ceux de l'utilisateur.
"""

import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

exe, pdf = sys.argv[1], sys.argv[2]
work = Path(tempfile.mkdtemp(prefix="destripdf-surveillance-"))
user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
kernel32.OpenProcess.restype = wt.HANDLE
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(("[OK] " if ok else "[ÉCHEC] ") + name + (f" — {detail}" if detail and not ok else ""))


def dialog_of_other_destripdf(first_pid: int):
    """Boîte de message « DestriPDF » (#32770) d'un autre processus que le premier."""
    found = []
    proc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def callback(hwnd, _):
        title, cls, pid = ctypes.create_unicode_buffer(64), ctypes.create_unicode_buffer(64), wt.DWORD()
        user32.GetWindowTextW(hwnd, title, 64)
        user32.GetClassNameW(hwnd, cls, 64)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if title.value == "DestriPDF" and cls.value == "#32770" and pid.value != first_pid and user32.IsWindowVisible(hwnd):
            found.append((hwnd, pid.value))
        return True

    user32.EnumWindows(proc(callback), 0)
    return found[0] if found else (None, None)


env = dict(os.environ)
env.update({
    "LOCALAPPDATA": str(work),
    "DESTRIPDF_SETTINGS_DIR": str(work / "reglages"),
    "DESTRIPDF_TEST_STALL_WINDOW": "1",
    "DESTRIPDF_TEST_WINDOW_TIMEOUT": "3",
    "PATH": env.get("PATH", "") + os.pathsep + r"C:\Users\tt\AppData\Local\Temp\_MEI99999\webview\lib",
})
first = subprocess.Popen([exe, pdf], env=env)
try:
    first.wait(25)
except subprocess.TimeoutExpired:
    first.kill()
check("première instance relancée puis terminée (code 0)", first.returncode == 0, f"code {first.returncode}")

hwnd, second_pid = None, None
deadline = time.time() + 25
while time.time() < deadline and hwnd is None:
    time.sleep(0.5)
    hwnd, second_pid = dialog_of_other_destripdf(first.pid)
check("relance bloquée à son tour : message affiché", hwnd is not None)
code = None
if hwnd is not None:
    handle = kernel32.OpenProcess(0x00100000 | 0x1000, False, second_pid)  # SYNCHRONIZE | QUERY_LIMITED
    user32.PostMessageW(hwnd, 0x0111, 1, 0)  # WM_COMMAND, IDOK
    kernel32.WaitForSingleObject(handle, 10000)
    exit_code = wt.DWORD()
    kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
    kernel32.CloseHandle(handle)
    code = exit_code.value
check("relance terminée après le message (code 1)", code == 1, f"code {code}")

log = (work / "DestriPDF" / "logs" / "destripdf.log").read_text(encoding="utf-8") if (work / "DestriPDF" / "logs" / "destripdf.log").exists() else ""
starts = [line for line in log.splitlines() if " démarrage DestriPDF " in line]
check("deux démarrages journalisés, le second marqué « relance »", len(starts) == 2 and "relance" in starts[1] and "relance" not in starts[0], str(starts))
check("dossier étranger retiré du PATH au premier démarrage", bool(starts) and "1 dossier(s) d'une autre application" in starts[0])
check("relance sans dossier étranger dans son PATH", len(starts) == 2 and "autre application" not in starts[1])
check("blocage journalisé deux fois", log.count("fenêtre non affichée après") == 2, log[-400:])
check("relance journalisée", "relance dans un environnement nettoyé" in log)
dumps = sorted((work / "DestriPDF" / "logs").glob("blocage-*.txt"))
check("piles des fils d'exécution écrites (deux fichiers)", len(dumps) == 2 and all("most recent call first" in d.read_text(encoding="utf-8") for d in dumps), str(dumps))

failed = [name for name, ok, _ in results if not ok]
print(f"\n{len(results) - len(failed)} / {len(results)} contrôles réussis (dossier de travail : {work})")
sys.exit(1 if failed else 0)
