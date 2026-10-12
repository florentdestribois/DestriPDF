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

from . import APP_NAME, __version__
from .server import AppState, LocalServer
from .settings import LOCAL_DIR, Settings

log = logging.getLogger("destripdf")


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
        import webview

        result = self.window.create_file_dialog(
            webview.FileDialog.SAVE,
            directory=directory or "",
            save_filename=filename,
            file_types=("Documents PDF (*.pdf)",),
        )
        if not result:
            return None
        return result[0] if isinstance(result, (list, tuple)) else str(result)


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
    # Recette : réglages isolés, jamais ceux de l'utilisateur.
    settings_dir = os.environ.get("DESTRIPDF_SETTINGS_DIR")
    settings = Settings(Path(settings_dir) if settings_dir else None)
    state = AppState(settings, store_factory=_test_store_factory() if args.serve else None, mode="browser" if args.serve else "window")
    state.started_at = started
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
    window.events.shown += lambda: log.info("fenêtre affichée en %.0f ms", (time.perf_counter() - started) * 1000)
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

    storage = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / APP_NAME / "webview"
    try:
        webview.start(gui="edgechromium", private_mode=False, storage_path=str(storage), debug=args.debug)
    finally:
        server.shutdown()
        if state.session is not None:
            state.session.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
