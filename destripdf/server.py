"""Serveur HTTP local de l'interface.

Écoute sur 127.0.0.1 seulement, port aléatoire. Chaque chemin commence par un
jeton secret ; l'en-tête Host doit désigner ce serveur ; toute requête qui
modifie quelque chose porte un en-tête propre à l'application et, si le
navigateur l'envoie, une origine identique. Aucune ressource externe.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import re
import secrets
import threading
import time
from collections import OrderedDict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Protocol
from urllib.parse import parse_qs, quote, urlsplit

from . import APP_NAME, __version__
from .settings import Settings

log = logging.getLogger("destripdf")

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_JSON = 4 * 1024 * 1024
MAX_UPLOAD = 1024 * 1024 * 1024
RENDER_CACHE_BYTES = 160 * 1024 * 1024
API_HEADER = "X-DestriPDF"

CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; "
    "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
    "form-action 'none'; frame-ancestors 'none'"
)


class Dialogs(Protocol):
    def open_pdf(self, directory: str) -> str | None: ...

    def save_pdf(self, directory: str, filename: str) -> str | None: ...

    def save_jpeg(self, directory: str, filename: str) -> str | None: ...

    def owner_handle(self) -> int: ...


class ApiError(Exception):
    def __init__(self, message: str, code: str = "error", status: int = 400, extra: dict | None = None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.extra = extra or {}


class RenderCache:
    """Images de pages déjà rendues, sous un budget mémoire."""

    def __init__(self, budget: int = RENDER_CACHE_BYTES):
        self._items: OrderedDict[tuple, tuple[bytes, str]] = OrderedDict()
        self._size = 0
        self._budget = budget
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            item = self._items.get(key)
            if item is not None:
                self._items.move_to_end(key)
            return item

    def put(self, key, value: tuple[bytes, str]) -> None:
        with self._lock:
            if key in self._items:
                return
            self._items[key] = value
            self._size += len(value[0])
            while self._size > self._budget and self._items:
                _, (data, _) = self._items.popitem(last=False)
                self._size -= len(data)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._size = 0


class AppState:
    """État de l'application partagé par les requêtes."""

    def __init__(
        self,
        settings: Settings,
        *,
        dialogs: Dialogs | None = None,
        store_factory: Callable | None = None,
        mode: str = "browser",
    ):
        self.settings = settings
        self.dialogs = dialogs
        self.mode = mode
        # Impression par le pilote (remplacé par un double dans les tests) ; en
        # recette, chaque impression part dans un fichier de ce dossier.
        self.printing = None
        self.print_output_dir: str | None = None
        self._store_factory = store_factory
        self.session = None
        self.lock = threading.RLock()
        self.idle = threading.Event()
        self.idle.set()
        self.load_error: dict | None = None
        self.pending: dict | None = None  # PDF protégé en attente du mot de passe
        self.render_cache = RenderCache()
        self.validation: dict = {"key": None, "running": False, "reports": None, "error": None}
        self.on_title: Callable[[str], None] | None = None
        self.on_quit: Callable[[], None] | None = None
        self.force_quit = False
        self.started_at = time.perf_counter()
        self.first_render_logged = False

    # -- magasin de certificats --

    def store_factory(self):
        if self._store_factory is not None:
            return self._store_factory
        from .signing import wincert

        return wincert.CertStore.system

    # -- ouverture --

    def refresh_title(self) -> None:
        if not self.on_title:
            return
        s = self.session
        if s is None:
            title = APP_NAME
        else:
            title = f"{'• ' if s.dirty else ''}{s.name} — {APP_NAME}"
        try:
            self.on_title(title)
        except Exception:  # noqa: BLE001 - la fenêtre peut être en cours de fermeture
            log.debug("titre non mis à jour", exc_info=True)

    def open_bytes(self, data: bytes, *, path: str | None, name: str | None, password: str | None = None) -> dict:
        from .document import DocumentError, PdfSession

        try:
            session = PdfSession(data, path=path, name=name, password=password)
        except DocumentError as err:
            if err.code == "password":
                self.pending = {"data": data, "path": path, "name": name or (Path(path).name if path else "Document.pdf")}
                raise ApiError(
                    "Mot de passe incorrect." if password else "Ce PDF est protégé par un mot de passe.",
                    "password",
                ) from err
            raise
        with self.lock:
            old, self.session = self.session, session
            self.pending = None
            self.load_error = None
            self.render_cache.clear()
        if old is not None:
            old.close()
        if path:
            try:
                self.settings.add_recent(path)
            except OSError:
                log.warning("fichiers récents non enregistrés", exc_info=True)
        self.refresh_title()
        if session.signed_original:
            self.start_validation()
        return session.summary()

    def open_path(self, path: str, password: str | None = None) -> dict:
        from .document import read_file

        path = os.path.abspath(path)
        if not os.path.isfile(path):
            raise ApiError("Ce fichier n'existe plus.", "not_found")
        data = read_file(path)
        return self.open_bytes(data, path=path, name=Path(path).name, password=password)

    def open_in_background(self, path: str) -> None:
        self.idle.clear()

        def run():
            try:
                self.open_path(path)
            except ApiError as err:
                self.load_error = {"error": str(err), "code": err.code, "path": path}
            except Exception as err:  # noqa: BLE001
                code = getattr(err, "code", "error")
                self.load_error = {"error": str(err) or "Ouverture impossible.", "code": code, "path": path}
                if code == "error":
                    log.exception("ouverture de %s", path)
            finally:
                self.idle.set()

        threading.Thread(target=run, name="destripdf-open", daemon=True).start()

    def require_session(self):
        session = self.session
        if session is None:
            raise ApiError("Aucun document ouvert.", "no_document", HTTPStatus.CONFLICT)
        return session

    def close_document(self) -> None:
        with self.lock:
            old, self.session = self.session, None
            self.render_cache.clear()
            self.validation = {"key": None, "running": False, "reports": None, "error": None}
        if old is not None:
            old.close()
        self.refresh_title()

    # -- vérification des signatures --

    def start_validation(self) -> None:
        session = self.session
        if session is None:
            return
        data = session.original
        password = session.password
        key = (session.id, len(data), hash(data[-4096:]))
        with self.lock:
            if self.validation.get("key") == key and (self.validation["running"] or self.validation["reports"] is not None):
                return
            self.validation = {"key": key, "running": True, "reports": None, "error": None}

        def run():
            try:
                from .signing import pades

                reports = [r.to_json() for r in pades.validate_signatures(data, password=password)]
                error = None
            except Exception as exc:  # noqa: BLE001
                log.exception("vérification des signatures")
                reports, error = [], f"Vérification impossible : {exc}"
            with self.lock:
                if self.validation.get("key") == key:
                    self.validation.update(running=False, reports=reports, error=error)

        threading.Thread(target=run, name="destripdf-validation", daemon=True).start()

    def state(self) -> dict:
        session = self.session
        return {
            "app": {"name": APP_NAME, "version": __version__, "mode": self.mode, "dialogs": self.dialogs is not None},
            "doc": session.summary() if session else None,
            "loading": not self.idle.is_set(),
            "error": self.load_error,
            "password_needed": bool(self.pending),
            "pending_name": (self.pending or {}).get("name"),
            "settings": self.settings.public(),
            "recent": self.settings.recent(),
        }


# --- Gestionnaire HTTP ---------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    server_version = f"{APP_NAME}/{__version__}"
    protocol_version = "HTTP/1.1"
    routes: list[tuple[str, re.Pattern, str]] = []

    @property
    def app(self) -> AppState:
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, fmt, *args):  # journal discret
        log.debug("%s - %s", self.address_string(), fmt % args)

    # -- garde-fous --

    def _check_host(self) -> bool:
        host = (self.headers.get("Host") or "").lower()
        port = self.server.server_address[1]
        return host in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _split(self):
        parts = urlsplit(self.path)
        prefix = f"/{self.server.token}/"  # type: ignore[attr-defined]
        if not parts.path.startswith(prefix) and parts.path != prefix[:-1]:
            return None, {}
        rest = parts.path[len(prefix):] if parts.path.startswith(prefix) else ""
        return rest, parse_qs(parts.query)

    def _check_mutation(self) -> bool:
        if self.headers.get(API_HEADER) != "1":
            return False
        origin = self.headers.get("Origin")
        port = self.server.server_address[1]
        if origin and origin not in (f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
            return False
        site = self.headers.get("Sec-Fetch-Site")
        return site in (None, "same-origin", "none")

    # -- réponses --

    def _send(self, status: int, body: bytes, content_type: str, headers: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8", {"Cache-Control": "no-store"})

    def _error(self, status: int, message: str, code: str = "error", extra: dict | None = None) -> None:
        self._json({**(extra or {}), "error": message, "code": code}, status)

    def _content_length(self) -> int:
        try:
            return max(0, int(self.headers.get("Content-Length") or 0))
        except ValueError:
            return -1

    def _body(self, limit: int) -> bytes:
        self._consumed = True
        length = self._content_length()
        if length < 0:
            self.close_connection = True
            raise ApiError("Requête invalide.", "bad_request")
        if length > limit:
            self.close_connection = True  # corps non lu : la connexion ne peut pas resservir
            raise ApiError("Contenu trop volumineux.", "too_large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        chunks = []
        remaining = length
        while remaining:
            chunk = self.rfile.read(min(1 << 20, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _drain(self) -> None:
        """Lit le corps resté sans lecture, pour que la connexion persistante reste saine."""
        if self._consumed:
            return
        self._consumed = True
        length = self._content_length()
        if length < 0 or length > MAX_JSON:
            self.close_connection = True
            return
        remaining = length
        while remaining:
            chunk = self.rfile.read(min(65536, remaining))
            if not chunk:
                break
            remaining -= len(chunk)

    def _json_body(self) -> dict:
        raw = self._body(MAX_JSON)
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise ApiError("Requête invalide.", "bad_request")
        if not isinstance(data, dict):
            raise ApiError("Requête invalide.", "bad_request")
        return data

    # -- aiguillage --

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _dispatch(self, method: str) -> None:
        self._consumed = method in ("GET", "HEAD")
        try:
            self._route(method)
        finally:
            if not self._consumed:
                try:
                    self._drain()
                except OSError:
                    self.close_connection = True

    def _route(self, method: str) -> None:
        if not self._check_host():
            self.close_connection = True
            self._error(HTTPStatus.BAD_REQUEST, "Hôte refusé.", "bad_host")
            return
        rest, query = self._split()
        if rest is None:
            self.close_connection = True
            self._error(HTTPStatus.NOT_FOUND, "Introuvable.", "not_found")
            return
        if method != "GET" and not self._check_mutation():
            self.close_connection = True
            self._error(HTTPStatus.FORBIDDEN, "Requête refusée.", "forbidden")
            return
        try:
            if method == "GET" and (rest == "" or rest == "index.html"):
                self._index()
                return
            if method == "GET" and rest.startswith("static/"):
                self._static(rest[len("static/"):])
                return
            for route_method, pattern, name in self.routes:
                if route_method != method:
                    continue
                match = pattern.fullmatch(rest)
                if match:
                    getattr(self, name)(query, *match.groups())
                    return
            self._error(HTTPStatus.NOT_FOUND, "Introuvable.", "not_found")
        except ApiError as err:
            self._error(err.status, str(err), err.code, err.extra)
        except Exception as err:  # noqa: BLE001
            code = getattr(err, "code", None)
            if code and type(err).__name__ in ("DocumentError", "SigningError", "WinCertError"):
                self._error(HTTPStatus.BAD_REQUEST, str(err), code)
                return
            if isinstance(err, (ValueError, KeyError, TypeError, IndexError)):
                log.warning("requête invalide %s %s", method, rest, exc_info=True)
                self._error(HTTPStatus.BAD_REQUEST, "Requête invalide.", "bad_request")
                return
            if isinstance(err, (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)):
                return
            log.exception("erreur %s %s", method, rest)
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "Erreur inattendue : l'opération n'a pas abouti.", "internal")

    # -- fichiers statiques --

    def _index(self) -> None:
        body = (STATIC_DIR / "index.html").read_bytes()
        self._send(200, body, "text/html; charset=utf-8", {"Cache-Control": "no-store", "Content-Security-Policy": CSP})

    def _static(self, rel: str) -> None:
        target = (STATIC_DIR / rel).resolve()
        if STATIC_DIR not in target.parents or not target.is_file():
            self._error(HTTPStatus.NOT_FOUND, "Introuvable.", "not_found")
            return
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.suffix == ".js":
            ctype = "text/javascript; charset=utf-8"
        elif target.suffix == ".css":
            ctype = "text/css; charset=utf-8"
        elif target.suffix == ".ttf":
            ctype = "font/ttf"
        self._send(200, target.read_bytes(), ctype, {"Cache-Control": "no-cache"})

    # -- état et ouverture --

    def api_state(self, query):
        if query.get("wait") and not self.app.idle.is_set():
            self.app.idle.wait(20)
        self._json(self.app.state())

    def api_open(self, query):
        body = self._json_body()
        path = str(body.get("path") or "")
        if not path:
            raise ApiError("Chemin manquant.", "bad_request")
        self._json({"doc": self.app.open_path(path, body.get("password"))})

    def api_open_dialog(self, query):
        dialogs = self.app.dialogs
        if dialogs is None:
            raise ApiError("Dialogue indisponible.", "no_dialog", HTTPStatus.CONFLICT)
        path = dialogs.open_pdf(self.app.settings.get("last_dir") or "")
        if not path:
            self._json({"cancelled": True})
            return
        self._json({"doc": self.app.open_path(path)})

    def api_upload(self, query):
        data = self._body(MAX_UPLOAD)
        name = (query.get("name") or ["Document.pdf"])[0][:200] or "Document.pdf"
        if not data:
            raise ApiError("Fichier vide.", "empty")
        self._json({"doc": self.app.open_bytes(data, path=None, name=name)})

    def api_password(self, query):
        body = self._json_body()
        pending = self.app.pending
        if not pending:
            raise ApiError("Aucun document en attente de mot de passe.", "no_pending", HTTPStatus.CONFLICT)
        self._json({"doc": self.app.open_bytes(pending["data"], path=pending["path"], name=pending["name"], password=str(body.get("password") or ""))})

    def api_cancel_pending(self, query):
        self.app.pending = None
        self.app.load_error = None
        self._json({"ok": True})

    def api_close(self, query):
        self.app.close_document()
        self._json({"ok": True})

    def api_recent_remove(self, query):
        body = self._json_body()
        self.app.settings.remove_recent(str(body.get("path") or ""))
        self._json({"recent": self.app.settings.recent()})

    # -- pages --

    def _page_index(self, value: str) -> int:
        try:
            return int(value)
        except ValueError:
            raise ApiError("Page invalide.", "bad_page")

    def api_page_image(self, query, page):
        session = self.app.require_session()
        index = self._page_index(page)
        doc_id = (query.get("d") or [""])[0]
        if doc_id and doc_id != session.id:
            # Demande d'un document déjà refermé : jamais l'image d'un autre document.
            raise ApiError("Document remplacé.", "stale_document", HTTPStatus.CONFLICT)
        try:
            scale = float((query.get("s") or ["1"])[0])
        except ValueError:
            scale = 1.0
        scale = round(max(0.05, min(scale, 8.0)), 3)
        version = session.page_versions[index] if 0 <= index < len(session.page_versions) else -1
        key = (session.id, index, version, scale)
        cached = self.app.render_cache.get(key)
        if cached is None:
            cached = session.render(index, scale)
            self.app.render_cache.put(key, cached)
        data, ctype = cached
        if not self.app.first_render_logged:
            self.app.first_render_logged = True
            log.info("première page servie %.0f ms après le lancement", (time.perf_counter() - self.app.started_at) * 1000)
        requested = (query.get("v") or [""])[0]
        immutable = requested == str(version) and doc_id == session.id
        cache = "private, max-age=31536000, immutable" if immutable else "no-store"
        self._send(200, data, ctype, {"Cache-Control": cache})

    def api_page_text(self, query, page):
        session = self.app.require_session()
        self._json(session.page_text(self._page_index(page)))

    def api_page_annots(self, query, page):
        session = self.app.require_session()
        index = self._page_index(page)
        self._json({"page": index, "annots": session.annotations(index), "fields": session.form_fields(index)})

    def api_annotations(self, query):
        self._json({"annots": self.app.require_session().all_annotations()})

    def api_search(self, query):
        q = (query.get("q") or [""])[0][:500]
        self._json({"hits": self.app.require_session().search(q)})

    def api_fonts(self, query):
        from .fonts import FONT_INDEX

        self._json({"families": FONT_INDEX.families()})

    # -- modifications --

    def _done(self, summary: dict, **extra) -> None:
        self.app.refresh_title()
        self._json({"doc": summary, **extra})

    def api_edit_line(self, query):
        from .document import LineRef, Run

        body = self._json_body()
        session = self.app.require_session()
        line = body["line"]
        runs = [
            Run(
                text=str(r.get("text", ""))[:5000],
                family=str(r.get("family", ""))[:100],
                size=float(r.get("size") or 11),
                color=str(r.get("color") or "#000000"),
                bold=bool(r.get("bold")),
                italic=bool(r.get("italic")),
            )
            for r in body.get("runs", [])[:200]
        ]
        ref = LineRef(bbox=tuple(float(v) for v in line["bbox"])[:4], text=str(line.get("text", "")))
        self._done(session.edit_line(int(body["page"]), ref, runs, str(body.get("align") or "left")))

    def api_annot_add(self, query):
        body = self._json_body()
        session = self.app.require_session()
        spec = dict(body.get("annot") or {})
        if spec.get("type") == "stamp_image":
            spec["image"] = self.app.settings.signature_image()
        if not spec.get("author"):
            spec["author"] = self.app.settings.get("author")
        summary = session.add_annotation(int(body["page"]), spec)
        self._done(summary, created=summary.pop("created", None))

    def api_annot_update(self, query):
        body = self._json_body()
        session = self.app.require_session()
        self._done(session.update_annotation(int(body["page"]), int(body["id"]), dict(body.get("changes") or {})))

    def api_annot_delete(self, query):
        body = self._json_body()
        session = self.app.require_session()
        self._done(session.delete_annotation(int(body["page"]), int(body["id"])))

    def api_erase(self, query):
        body = self._json_body()
        self._done(self.app.require_session().erase(int(body["page"]), [float(v) for v in body["rect"]][:4]))

    def api_field(self, query):
        body = self._json_body()
        self._done(self.app.require_session().set_field(int(body["page"]), int(body["id"]), body.get("value")))

    def api_pages_rotate(self, query):
        body = self._json_body()
        pages = [int(p) for p in body.get("pages", [])][:10000]
        self._done(self.app.require_session().rotate_pages(pages, int(body.get("angle", 90))))

    def api_pages_delete(self, query):
        body = self._json_body()
        self._done(self.app.require_session().delete_pages([int(p) for p in body.get("pages", [])][:10000]))

    def api_pages_move(self, query):
        body = self._json_body()
        self._done(self.app.require_session().move_page(int(body["from"]), int(body["to"])))

    def _printing(self):
        if self.app.printing is None:
            from .printing import WindowsPrinting

            self.app.printing = WindowsPrinting()
        return self.app.printing

    def _printer_name(self, body) -> str:
        name = str(body.get("printer") or "")
        if not name or name not in self._printing().printers()[0]:
            raise ApiError("Choisissez une imprimante du poste.", "bad_printer")
        return name

    def api_printers(self, query):
        from .printing import PrintError

        try:
            names, default = self._printing().printers()
        except (PrintError, OSError) as exc:
            raise ApiError(f"Imprimantes illisibles : {exc}", "printers_failed") from exc
        last = self.app.settings.get("last_printer")
        self._json({"printers": names, "default": default, "selected": last if last in names else default})

    def api_printer_capabilities(self, query):
        """Ce que le pilote permet pour le livret : formats ordinaires, recto verso bord court."""
        from .printing import PrintError

        name = self._printer_name({"printer": (query.get("printer") or [""])[0]})
        try:
            caps = self._printing().capabilities(name)
        except PrintError as exc:
            raise ApiError(str(exc), "print_failed") from exc
        flipped = name in (self.app.settings.get("booklet_flipped") or [])
        self._json({"printer": name, **caps, "flip_backs": flipped})

    def _print_pages(self, body, count: int) -> list[int]:
        from .printing import PrintError, parse_pages

        scope = body.get("pages") or "all"
        if scope == "all":
            return list(range(count))
        if scope == "current":
            try:
                current = int(body.get("current", 0))
            except (TypeError, ValueError):
                current = -1
            if not 0 <= current < count:
                raise ApiError("Page inexistante.", "bad_page")
            return [current]
        try:
            return parse_pages(str(scope), count)
        except PrintError as exc:
            raise ApiError(str(exc), "bad_page") from exc

    def api_booklet_plan(self, query):
        """Faces du livret pour les pages choisies : (gauche, droite), numéros de page."""
        from .booklet import booklet_sides

        session = self.app.require_session()
        binding = (query.get("binding") or ["left"])[0]
        if binding not in ("left", "right"):
            raise ApiError("Reliure inconnue.", "bad_binding")
        pages = self._print_pages({"pages": (query.get("pages") or ["all"])[0],
                                   "current": (query.get("current") or ["0"])[0]}, session.page_count)
        faces = [[None if k is None else pages[k] + 1 for k in face] for face in booklet_sides(len(pages), binding)]
        self._json({"faces": faces, "sheets": len(faces) // 2, "pages": len(pages)})

    def api_print_preferences(self, query):
        """Fenêtre de préférences du pilote (recto verso, bac…), gardées pour l'impression."""
        from .printing import PrintError

        body = self._json_body()
        name = self._printer_name(body)
        dialogs = self.app.dialogs
        if dialogs is None:
            raise ApiError("Dialogue indisponible.", "no_dialog", HTTPStatus.CONFLICT)
        try:
            changed = self._printing().preferences(dialogs.owner_handle(), name)
        except PrintError as exc:
            raise ApiError(str(exc), "print_failed") from exc
        self._json({"changed": changed})

    def api_print(self, query):
        """Envoi au pilote de l'imprimante choisie : pages normales ou livret mis en
        page par DestriPDF (jamais la fonction Livret de l'imprimante)."""
        from .booklet import MIN_MARGIN, SHEETS
        from .document import FITZ_LOCK, render_bgra
        from .printing import MAX_COPIES, PrintError

        body = self._json_body()
        session = self.app.require_session()
        output = None
        if self.app.dialogs is None:
            # Mode navigateur : seule la recette imprime, dans un fichier.
            if not self.app.print_output_dir:
                raise ApiError("Impression disponible dans la fenêtre DestriPDF.", "no_dialog", HTTPStatus.CONFLICT)
            output = str(Path(self.app.print_output_dir) / f"impression-{int(time.time() * 1000)}.pdf")
        name = self._printer_name(body)
        try:
            copies = int(body.get("copies", 1))
        except (TypeError, ValueError):
            copies = 0
        if not 1 <= copies <= MAX_COPIES:
            raise ApiError(f"Nombre de copies entre 1 et {MAX_COPIES}.", "bad_copies")
        pages = self._print_pages(body, session.page_count)
        layout = body.get("layout") or "normal"
        if layout not in ("normal", "booklet"):
            raise ApiError("Mise en page inconnue.", "bad_layout")
        result = {"pages": len(pages), "copies": copies, "layout": layout}
        if layout == "booklet":
            sheet = body.get("sheet") or "a4"
            binding = body.get("binding") or "left"
            if sheet not in SHEETS:
                raise ApiError("Format de feuille inconnu.", "bad_sheet")
            if binding not in ("left", "right"):
                raise ApiError("Reliure inconnue.", "bad_binding")
            flip = bool(body.get("flip_backs"))
            made = {}

            def impose(margin: float):
                made["faces"] = session.impose_booklet(pages, SHEETS[sheet], max(MIN_MARGIN, margin), binding)
                return made["faces"]

            def render_face(faces, index: int, scale: float, rotate: int):
                return render_bgra(faces.__getitem__, index, scale, rotate)

            try:
                faces = self._printing().print_booklet(name, copies, session.name, sheet, impose, render_face,
                                                       upside_down_backs=flip, output=output)
            except PrintError as exc:
                raise ApiError(str(exc), "print_failed") from exc
            finally:
                if "faces" in made:
                    with FITZ_LOCK:
                        made["faces"].close()
            self.app.settings.remember_booklet_flip(name, flip)
            result.update({"sheets": faces // 2, "faces": faces, "sheet": sheet})
        else:
            try:
                self._printing().print_document(name, copies, session.name, pages, session.page_size,
                                                session.render_print, output=output)
            except PrintError as exc:
                raise ApiError(str(exc), "print_failed") from exc
        self.app.settings.remember_printer(name)
        if output:
            result["output"] = output
        self._json(result)

    def api_pages_insert_dialog(self, query):
        body = self._json_body()
        session = self.app.require_session()
        dialogs = self.app.dialogs
        if dialogs is None:
            raise ApiError("Dialogue indisponible.", "no_dialog", HTTPStatus.CONFLICT)
        path = dialogs.open_pdf(self.app.settings.get("last_dir") or "")
        if not path:
            self._json({"cancelled": True})
            return
        from .document import read_file

        at = body.get("at")
        self._done(session.insert_pdf(read_file(path), None if at is None else int(at)))

    def api_pages_insert_upload(self, query):
        session = self.app.require_session()
        data = self._body(MAX_UPLOAD)
        at = (query.get("at") or [None])[0]
        self._done(session.insert_pdf(data, None if at in (None, "") else int(at)))

    def api_undo(self, query):
        self._done(self.app.require_session().undo())

    def api_redo(self, query):
        self._done(self.app.require_session().redo())

    # -- enregistrement --

    def _suggested_dir(self, session) -> str:
        if session.path:
            return str(Path(session.path).parent)
        return self.app.settings.get("last_dir") or str(Path.home() / "Documents")

    def _after_save(self, session) -> None:
        if session.path:
            self.app.settings.add_recent(session.path)
        if session.signed_original:
            self.app.start_validation()

    def _save_to(self, session, path: str | None, force_full: bool) -> dict:
        from .document import DocumentError

        try:
            return session.save(path, force_full=force_full)
        except DocumentError as err:
            if err.code == "repaired_signed":
                # L'interface demande confirmation puis rappelle avec force_full et ce chemin.
                raise ApiError(str(err), err.code, HTTPStatus.CONFLICT, {"path": path or session.path}) from err
            raise

    def api_save(self, query):
        body = self._json_body()
        session = self.app.require_session()
        if not session.path:
            raise ApiError("Choisissez où enregistrer ce document.", "need_path", HTTPStatus.CONFLICT)
        summary = self._save_to(session, None, bool(body.get("force_full")))
        self._after_save(session)
        self._done(summary)

    def api_save_as(self, query):
        body = self._json_body()
        session = self.app.require_session()
        path = str(body.get("path") or "")
        if not path:
            dialogs = self.app.dialogs
            if dialogs is None:
                raise ApiError("Indiquez le chemin du fichier.", "need_path", HTTPStatus.CONFLICT)
            path = dialogs.save_pdf(self._suggested_dir(session), session.name) or ""
            if not path:
                self._json({"cancelled": True})
                return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        summary = self._save_to(session, path, bool(body.get("force_full")))
        self._after_save(session)
        self._done(summary)

    EXPORT_DPI = (150, 300)

    def api_export_jpeg(self, query):
        """Pages en images JPG : la page affichée, ou toutes, numérotées d'après le nom choisi."""
        from .document import atomic_write

        body = self._json_body()
        session = self.app.require_session()
        count = session.page_count
        if body.get("scope") == "all":
            pages = list(range(count))
        else:
            try:
                page = int(body.get("page", 0))
            except (TypeError, ValueError):
                page = -1
            if not 0 <= page < count:
                raise ApiError("Page inexistante.", "bad_page")
            pages = [page]
        try:
            dpi = int(body.get("dpi") or 150)
        except (TypeError, ValueError):
            dpi = 0
        if dpi not in self.EXPORT_DPI:
            raise ApiError("Résolution non prise en charge.", "bad_dpi")
        stem = Path(session.name).stem or "document"
        path = str(body.get("path") or "")
        if not path:
            dialogs = self.app.dialogs
            if dialogs is None:
                raise ApiError("Indiquez le chemin de l'image.", "need_path", HTTPStatus.CONFLICT)
            suggested = f"{stem} - page {pages[0] + 1}.jpg" if len(pages) == 1 else f"{stem}.jpg"
            path = dialogs.save_jpeg(self._suggested_dir(session), suggested) or ""
            if not path:
                self._json({"cancelled": True})
                return
        if not path.lower().endswith((".jpg", ".jpeg")):
            path += ".jpg"
        target = Path(path)
        digits = len(str(count))
        files, reduced = [], False
        for index in pages:
            out = target if len(pages) == 1 else target.with_name(f"{target.stem} - page {index + 1:0{digits}d}{target.suffix}")
            data, effective = session.render_jpeg(index, dpi)
            reduced = reduced or effective < dpi
            atomic_write(out, data)
            files.append(str(out))
        self.app.settings.remember_dir(str(target))
        self._json({"files": files, "dir": str(target.parent), "reduced": reduced})

    def api_download(self, query):
        session = self.app.require_session()
        from .document import FITZ_LOCK

        with FITZ_LOCK:
            data = session.export_bytes()
        name = session.name if session.name.lower().endswith(".pdf") else session.name + ".pdf"
        self._send(200, data, "application/pdf", {
            "Cache-Control": "no-store",
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}",
        })

    # -- signature --

    def api_certificates(self, query):
        from .signing import wincert

        try:
            with self.app.store_factory()() as store:
                entries = [e.to_json() for e in store.certificates() if e.has_private_key]
        except wincert.WinCertError as err:
            raise ApiError(str(err), err.code)
        self._json({"certificates": entries})

    def api_signatures(self, query):
        session = self.app.require_session()
        if not session.signed_original:
            self._json({"pending": False, "reports": []})
            return
        self.app.start_validation()
        v = self.app.validation
        self._json({"pending": bool(v.get("running")), "reports": v.get("reports") or [], "error": v.get("error")})

    def api_sign(self, query):
        from .document import FITZ_LOCK, atomic_write
        from .signing import pades, wincert

        body = self._json_body()
        session = self.app.require_session()
        thumbprint = str(body.get("certificate") or "")
        if not re.fullmatch(r"[0-9A-Fa-f]{40}", thumbprint):
            raise ApiError("Choisissez un certificat.", "no_certificate")
        reason = str(body.get("reason") or "")[:200]
        location = str(body.get("location") or "")[:200]
        appearance = None
        visible = body.get("visible")
        if visible:
            page = int(visible["page"])
            rect = session.unrotated_rect(page, [float(v) for v in visible["rect"]][:4])
            image = self.app.settings.signature_image() if body.get("with_image") else None
            appearance = pades.Appearance(page_index=page, rect=rect, image_png=image)
        path = str(body.get("path") or "")
        if not path:
            dialogs = self.app.dialogs
            if dialogs is None:
                raise ApiError("Indiquez le fichier signé à créer.", "need_path", HTTPStatus.CONFLICT)
            stem = Path(session.name).stem
            path = dialogs.save_pdf(self._suggested_dir(session), f"{stem} - signé.pdf") or ""
            if not path:
                self._json({"cancelled": True})
                return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        hwnd = wincert.foreground_window_of_this_process() if self.app.mode == "window" else None
        options = pades.SignOptions(
            thumbprint=thumbprint,
            reason=reason,
            location=location,
            appearance=appearance,
            timestamp_url=self.app.settings.get("timestamp_url") or "",
            hwnd=hwnd,
            password=session.password,
            ltv=bool(self.app.settings.get("sign_ltv")),
        )
        with FITZ_LOCK:
            data = session.export_bytes()
        signed, info = pades.sign_pdf(data, options, store_factory=self.app.store_factory())
        atomic_write(path, signed)
        summary = session.replace_with(signed, path=path)
        self.app.render_cache.clear()
        self.app.settings.add_recent(path)
        self.app.settings.update({"sign_reason": reason, "sign_location": location, "sign_visible": bool(visible), "sign_with_image": bool(body.get("with_image"))})
        self.app.start_validation()
        self._done(summary, signature=info)

    # -- réglages --

    def api_settings_get(self, query):
        self._json({"settings": self.app.settings.public()})

    def api_settings_set(self, query):
        try:
            self._json({"settings": self.app.settings.update(self._json_body())})
        except ValueError as err:
            raise ApiError(str(err), "bad_setting")

    def api_signature_image_get(self, query):
        data = self.app.settings.signature_image()
        if data is None:
            self._error(HTTPStatus.NOT_FOUND, "Aucune image de signature.", "no_image")
            return
        self._send(200, data, "image/png", {"Cache-Control": "no-store"})

    def api_signature_image_set(self, query):
        try:
            self.app.settings.set_signature_image(self._body(2 * 1024 * 1024 + 1))
        except ValueError as err:
            raise ApiError(str(err), "bad_image")
        self._json({"settings": self.app.settings.public()})

    def api_signature_image_delete(self, query):
        self.app.settings.delete_signature_image()
        self._json({"settings": self.app.settings.public()})

    # -- application --

    def api_quit(self, query):
        self.app.force_quit = True
        self._json({"ok": True})
        if self.app.on_quit:
            threading.Thread(target=self.app.on_quit, daemon=True).start()


def _route(method: str, pattern: str, name: str):
    Handler.routes.append((method, re.compile(pattern), name))


for _method, _pattern, _name in (
    ("GET", r"api/state", "api_state"),
    ("POST", r"api/open", "api_open"),
    ("POST", r"api/open-dialog", "api_open_dialog"),
    ("POST", r"api/upload", "api_upload"),
    ("POST", r"api/password", "api_password"),
    ("POST", r"api/cancel-pending", "api_cancel_pending"),
    ("POST", r"api/close", "api_close"),
    ("POST", r"api/recent/remove", "api_recent_remove"),
    ("GET", r"api/page/(\d+)/image", "api_page_image"),
    ("GET", r"api/page/(\d+)/text", "api_page_text"),
    ("GET", r"api/page/(\d+)/annots", "api_page_annots"),
    ("GET", r"api/annotations", "api_annotations"),
    ("GET", r"api/search", "api_search"),
    ("GET", r"api/fonts", "api_fonts"),
    ("POST", r"api/edit-line", "api_edit_line"),
    ("POST", r"api/annot/add", "api_annot_add"),
    ("POST", r"api/annot/update", "api_annot_update"),
    ("POST", r"api/annot/delete", "api_annot_delete"),
    ("POST", r"api/erase", "api_erase"),
    ("POST", r"api/field", "api_field"),
    ("POST", r"api/pages/rotate", "api_pages_rotate"),
    ("POST", r"api/pages/delete", "api_pages_delete"),
    ("POST", r"api/pages/move", "api_pages_move"),
    ("POST", r"api/pages/insert-dialog", "api_pages_insert_dialog"),
    ("POST", r"api/pages/insert-upload", "api_pages_insert_upload"),
    ("POST", r"api/undo", "api_undo"),
    ("POST", r"api/redo", "api_redo"),
    ("POST", r"api/save", "api_save"),
    ("POST", r"api/save-as", "api_save_as"),
    ("POST", r"api/export-jpeg", "api_export_jpeg"),
    ("GET", r"api/printers", "api_printers"),
    ("GET", r"api/printers/capabilities", "api_printer_capabilities"),
    ("POST", r"api/print/preferences", "api_print_preferences"),
    ("GET", r"api/print/booklet-plan", "api_booklet_plan"),
    ("POST", r"api/print", "api_print"),
    ("GET", r"api/download", "api_download"),
    ("GET", r"api/certificates", "api_certificates"),
    ("GET", r"api/signatures", "api_signatures"),
    ("POST", r"api/sign", "api_sign"),
    ("GET", r"api/settings", "api_settings_get"),
    ("POST", r"api/settings", "api_settings_set"),
    ("GET", r"api/signature-image", "api_signature_image_get"),
    ("POST", r"api/signature-image", "api_signature_image_set"),
    ("DELETE", r"api/signature-image", "api_signature_image_delete"),
    ("POST", r"api/quit", "api_quit"),
):
    _route(_method, _pattern, _name)


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, app: AppState, port: int = 0, token: str | None = None):
        super().__init__(("127.0.0.1", port), Handler)
        self.app = app
        self.token = token or secrets.token_urlsafe(24)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/{self.token}/"

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self.serve_forever, kwargs={"poll_interval": 0.25}, name="destripdf-http", daemon=True)
        thread.start()
        return thread
