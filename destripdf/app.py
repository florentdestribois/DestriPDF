"""Lancement : serveur local, ouverture du fichier demandé, fenêtre WebView2.

Le serveur et la lecture du PDF partent avant la fenêtre : la première page est
prête quand l'interface la demande.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import APP_NAME, __version__, startup
from .server import AppState, LocalServer
from .settings import LOCAL_DIR, Settings

log = logging.getLogger("destripdf")

WINDOW_ERROR = (
    "DestriPDF n'a pas pu afficher sa fenêtre : le moteur d'affichage de Windows (WebView2) ne répond pas.\n\n"
    "Aucun document n'a été modifié. Rouvrez le fichier ; si le problème persiste, ouvrez-le depuis "
    "l'Explorateur de fichiers ou redémarrez l'ordinateur.\n\n"
    f"Détails pour le dépannage : {LOCAL_DIR / 'logs'}"
)


def _setup_logging(debug: bool) -> None:
    log.setLevel(logging.DEBUG if debug else logging.INFO)
    try:
        directory = LOCAL_DIR / "logs"
        directory.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(directory / "destripdf.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(message)s"))
        log.addHandler(handler)
    except OSError:
        pass
    if debug or not getattr(sys, "frozen", False):
        log.addHandler(logging.StreamHandler())


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=APP_NAME, description="Lecture, modification, annotation et signature de PDF.")
    parser.add_argument("file", nargs="?", help="PDF à ouvrir")
    parser.add_argument("--serve", action="store_true", help="sans fenêtre : interface dans un navigateur (recette)")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    return parser.parse_args(argv)


class WindowDialogs:
    """Dialogues natifs de Windows, ouverts par la fenêtre pywebview."""

    def __init__(self, window):
        self.window = window

    def open_pdf(self, directory: str) -> str | None:
        import webview

        result = self.window.create_file_dialog(
            webview.FileDialog.OPEN,
            directory=directory or "",
            allow_multiple=False,
            file_types=("Documents PDF (*.pdf)", "Tous les fichiers (*.*)"),
        )
        if not result:
            return None
        return result[0] if isinstance(result, (list, tuple)) else str(result)

    def save_pdf(self, directory: str, filename: str) -> str | None:
        return self._save(directory, filename, ("Documents PDF (*.pdf)",))

    def save_jpeg(self, directory: str, filename: str) -> str | None:
        return self._save(directory, filename, ("Images JPEG (*.jpg;*.jpeg)",))

    def owner_handle(self) -> int:
        """Fenêtre propriétaire des fenêtres natives (préférences du pilote d'imprimante)."""
        from System import Func, Type

        form = self.window.native
        handle = []
        form.Invoke(Func[Type](lambda: handle.append(form.Handle.ToInt64())))
        return handle[0] if handle else 0

    def _save(self, directory: str, filename: str, file_types: tuple[str, ...]) -> str | None:
        import webview

        result = self.window.create_file_dialog(
            webview.FileDialog.SAVE,
            directory=directory or "",
            save_filename=filename,
            file_types=file_types,
        )
        if not result:
            return None
        return result[0] if isinstance(result, (list, tuple)) else str(result)


def _flush_and_exit(code: int) -> None:
    for handler in log.handlers:
        try:
            handler.flush()
        except Exception:  # noqa: BLE001
            pass
    os._exit(code)


def _window_timeout(relaunched: bool, started: float) -> None:
    """La fenêtre n'est pas apparue : piles pour le diagnostic, relance unique dans un
    environnement nettoyé, sinon message et fin du processus (jamais d'instance fantôme)."""
    elapsed = time.perf_counter() - started
    header = (
        f"{APP_NAME} {__version__} : fenêtre non affichée après {elapsed:.0f} s\n"
        f"processus {os.getpid()}, lancé par {startup.parent_process_name()}, relance : {'oui' if relaunched else 'non'}\n"
        f"WebView2 {startup.webview2_version()}\narguments : {sys.argv[1:]}"
    )
    try:
        dump = startup.dump_threads(LOCAL_DIR / "logs", header)
        log.error("fenêtre non affichée après %.0f s : piles des fils d'exécution dans %s", elapsed, dump.name)
    except OSError:
        log.error("fenêtre non affichée après %.0f s (piles non écrites)", elapsed, exc_info=True)
    if not relaunched and startup.relaunch(sys.argv[1:]):
        log.warning("relance dans un environnement nettoyé, avec le dossier WebView2 de secours")
        _flush_and_exit(0)
    startup.show_error(WINDOW_ERROR)
    _flush_and_exit(1)


def _test_store_factory():
    """Certificat de recette (PFX en mémoire) : seulement si la recette le demande."""
    pfx = os.environ.get("DESTRIPDF_TEST_PFX")
    if not pfx:
        return None
    from .signing import wincert

    data = Path(pfx).read_bytes()
    password = os.environ.get("DESTRIPDF_TEST_PFX_PASSWORD", "")
    return lambda: wincert.CertStore.from_pfx(data, password)


def main(argv: list[str] | None = None) -> int:
    started = time.perf_counter()
    args = _parse(sys.argv[1:] if argv is None else argv)
    _setup_logging(args.debug)
    # Lancé par une autre application PyInstaller (DestriCenter) : ses dossiers
    # temporaires `_MEI…` sont retirés du PATH avant de charger WebView2.
    relaunched = os.environ.get(startup.RELAUNCHED) == "1"
    cleaned_path, foreign = startup.clean_path(os.environ.get("PATH", ""))
    if foreign:
        os.environ["PATH"] = cleaned_path
    # Recette : réglages isolés, jamais ceux de l'utilisateur.
    settings_dir = os.environ.get("DESTRIPDF_SETTINGS_DIR")
    settings = Settings(Path(settings_dir) if settings_dir else None)
    state = AppState(settings, store_factory=_test_store_factory() if args.serve else None, mode="browser" if args.serve else "window")
    state.started_at = started
    if args.serve:
        # Recette : impressions écrites dans des fichiers, jamais sur une vraie imprimante.
        state.print_output_dir = os.environ.get("DESTRIPDF_TEST_PRINT_DIR") or None
    # Jeton fixe : recette uniquement (variable d'environnement de développement).
    server = LocalServer(state, port=args.port, token=os.environ.get("DESTRIPDF_TOKEN") or None)
    server.start()
    if args.file:
        state.open_in_background(args.file)
    else:
        # Préchargement de MuPDF pendant l'ouverture de la fenêtre.
        threading.Thread(target=lambda: __import__("pymupdf"), name="destripdf-preload", daemon=True).start()

    if args.serve:
        print(f"{APP_NAME} {__version__} — {server.url}", flush=True)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        finally:
            server.shutdown()
        return 0

    log.info(
        "démarrage %s %s (processus %s, lancé par %s%s) : %s ; WebView2 %s%s",
        APP_NAME, __version__, os.getpid(), startup.parent_process_name(), ", relance" if relaunched else "",
        Path(args.file).name if args.file else "sans document", startup.webview2_version(),
        f" ; {len(foreign)} dossier(s) d'une autre application retiré(s) du PATH" if foreign else "",
    )

    import webview

    window = webview.create_window(
        APP_NAME,
        server.url,
        width=1280,
        height=860,
        min_size=(900, 600),
        background_color="#F8F6F2",
        text_select=True,
    )
    state.dialogs = WindowDialogs(window)
    state.on_title = lambda title: setattr(window, "title", title)
    state.on_quit = window.destroy

    def on_closing():
        session = state.session
        dirty = bool(session is not None and session.dirty)
        log.info("fermeture demandée (document modifié : %s, sortie forcée : %s)", dirty, state.force_quit)
        if state.force_quit or not dirty:
            return True
        # Ne pas attendre le JavaScript ici : ce gestionnaire tourne dans le fil de la fenêtre.
        threading.Thread(target=lambda: window.evaluate_js("window.DestriPDF && window.DestriPDF.requestClose()"), daemon=True).start()
        return False

    window.events.closing += on_closing
    timeout = float(os.environ.get("DESTRIPDF_TEST_WINDOW_TIMEOUT") or startup.WINDOW_TIMEOUT)
    watchdog = startup.StartupWatchdog(timeout, lambda: _window_timeout(relaunched, started))
    window.events.shown += watchdog.shown
    window.events.shown += lambda: log.info("fenêtre affichée en %.0f ms", (time.perf_counter() - started) * 1000)
    window.events.loaded += lambda: log.info("interface chargée en %.0f ms", (time.perf_counter() - started) * 1000)
    # Le document passé en argument peut s'ouvrir avant la fenêtre : titre repris au chargement.
    window.events.loaded += state.refresh_title

    def on_drop(event):
        """Fichier glissé depuis l'Explorateur : l'interface l'ouvre par son chemin réel."""
        for item in (event.get("dataTransfer") or {}).get("files", []):
            path = item.get("pywebviewFullPath")
            if path and path.lower().endswith(".pdf") and os.path.isfile(path):
                window.evaluate_js(f"window.DestriPDF && window.DestriPDF.openDropped({json.dumps(path)})")
                return

    def bind_drop():
        from webview.dom import DOMEventHandler

        try:
            window.dom.document.events.drop += DOMEventHandler(on_drop, prevent_default=True)
        except Exception:  # noqa: BLE001 - repli : envoi du fichier par l'interface
            log.warning("chemin des fichiers déposés indisponible", exc_info=True)

    window.events.loaded += bind_drop

    # Relance après un blocage : dossier WebView2 de secours (un dossier tenu par un
    # processus WebView2 accroché bloque la création du moteur).
    storage = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / APP_NAME / ("webview-secours" if relaunched else "webview")
    watchdog.start()
    try:
        if os.environ.get("DESTRIPDF_TEST_STALL_WINDOW") == "1":
            # Recette de la surveillance : fenêtre volontairement jamais affichée.
            while True:
                time.sleep(3600)
        webview.start(gui="edgechromium", private_mode=False, storage_path=str(storage), debug=args.debug)
    finally:
        server.shutdown()
        if state.session is not None:
            state.session.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
