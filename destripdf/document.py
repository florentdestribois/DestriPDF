"""Document ouvert : rendu, texte, modifications, annulation et enregistrement.

Toutes les coordonnées échangées avec l'interface sont celles de la page
affichée (rotation appliquée), en points, origine en haut à gauche. MuPDF
travaille, lui, dans l'espace non pivoté : les conversions se font ici.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import tempfile
import threading
import time
import uuid
import zlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

import pymupdf as fitz

from . import fonts

fitz.TOOLS.set_small_glyph_heights(False)

# PyMuPDF n'est pas sûr entre fils d'exécution : un seul verrou pour tout MuPDF.
FITZ_LOCK = threading.RLock()

HISTORY_BUDGET = 400 * 1024 * 1024
MAX_RENDER_PIXELS = 40_000_000  # garde-fou mémoire pour un zoom extrême

ANNOT_LABELS = {
    "Text": "Note",
    "FreeText": "Texte",
    "Highlight": "Surlignage",
    "Underline": "Soulignement",
    "StrikeOut": "Texte barré",
    "Squiggly": "Soulignement ondulé",
    "Ink": "Dessin",
    "Square": "Rectangle",
    "Circle": "Ellipse",
    "Line": "Flèche",
    "Polygon": "Polygone",
    "PolyLine": "Ligne brisée",
    "Stamp": "Tampon",
    "FileAttachment": "Pièce jointe",
    "Caret": "Insertion",
    "Redact": "Caviardage en attente",
}
MOVABLE = {"Text", "FreeText", "Square", "Circle", "Stamp", "Ink", "Line"}
EDITABLE_CONTENT = {"Text", "FreeText", "Square", "Circle", "Highlight", "Underline", "StrikeOut", "Ink", "Line", "Stamp"}


class DocumentError(Exception):
    """Erreur présentée telle quelle à l'utilisateur."""

    def __init__(self, message: str, code: str = "error"):
        super().__init__(message)
        self.code = code


# --- Historique --------------------------------------------------------------


class History:
    """États successifs du document (PDF complets) sous un budget mémoire.

    Chaque état reçoit un identifiant unique : après « enregistrer, annuler,
    autre modification », le nouvel état n'est jamais pris pour l'état
    enregistré, même s'il occupe la même place dans la pile.
    """

    _ids = 0

    def __init__(self, initial: bytes, budget: int = HISTORY_BUDGET):
        self._states: list[bytes] = [initial]
        self._labels: list[str] = ["Ouverture"]
        self._state_ids: list[int] = [self._new_id()]
        self._index = 0
        self._budget = budget

    @classmethod
    def _new_id(cls) -> int:
        cls._ids += 1
        return cls._ids

    @property
    def state_id(self) -> int:
        """Identifiant de l'état courant (sert à savoir si le document est enregistré)."""
        return self._state_ids[self._index]

    @property
    def current(self) -> bytes:
        return self._states[self._index]

    def push(self, data: bytes, label: str) -> None:
        del self._states[self._index + 1 :]
        del self._labels[self._index + 1 :]
        del self._state_ids[self._index + 1 :]
        self._states.append(data)
        self._labels.append(label)
        self._state_ids.append(self._new_id())
        self._index += 1
        total = sum(len(s) for s in self._states)
        while total > self._budget and self._index > 1:
            total -= len(self._states[0])
            del self._states[0]
            del self._labels[0]
            del self._state_ids[0]
            self._index -= 1

    def can_undo(self) -> bool:
        return self._index > 0

    def can_redo(self) -> bool:
        return self._index < len(self._states) - 1

    def undo_label(self) -> str:
        return self._labels[self._index] if self.can_undo() else ""

    def redo_label(self) -> str:
        return self._labels[self._index + 1] if self.can_redo() else ""

    def undo(self) -> bytes:
        if not self.can_undo():
            raise DocumentError("Rien à annuler.", "nothing")
        self._index -= 1
        return self._states[self._index]

    def redo(self) -> bytes:
        if not self.can_redo():
            raise DocumentError("Rien à rétablir.", "nothing")
        self._index += 1
        return self._states[self._index]

    def reset(self, data: bytes) -> None:
        self._states, self._labels, self._state_ids = [data], ["Ouverture"], [self._new_id()]
        self._index = 0


# --- Outils géométriques -----------------------------------------------------


def _rect_list(rect: fitz.Rect, nd: int = 2) -> list[float]:
    return [round(rect.x0, nd), round(rect.y0, nd), round(rect.x1, nd), round(rect.y1, nd)]


def _to_display(page: fitz.Page, rect) -> fitz.Rect:
    r = fitz.Rect(rect) * page.rotation_matrix
    r.normalize()
    return r


def _to_unrot(page: fitz.Page, rect) -> fitz.Rect:
    r = fitz.Rect(rect) * page.derotation_matrix
    r.normalize()
    return r


def _pt_display(page: fitz.Page, point) -> fitz.Point:
    return fitz.Point(point) * page.rotation_matrix


def _pt_unrot(page: fitz.Page, point) -> fitz.Point:
    return fitz.Point(point) * page.derotation_matrix


def _color_hex(value: int | Iterable[float] | None) -> str:
    if value is None:
        return ""
    if isinstance(value, int):
        return f"#{value & 0xFFFFFF:06x}"
    comps = list(value)
    if len(comps) == 1:
        comps = comps * 3
    if len(comps) == 4:  # CMJN approché
        c, m, y, k = comps
        comps = [(1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k)]
    if len(comps) != 3:
        return ""
    return "#" + "".join(f"{max(0, min(255, round(v * 255))):02x}" for v in comps)


def parse_color(value: str | None, default=(0, 0, 0)) -> tuple[float, float, float]:
    if not value:
        return default
    match = re.fullmatch(r"#?([0-9a-fA-F]{6})", value.strip())
    if not match:
        return default
    h = match.group(1)
    return tuple(int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))


def encode_png(samples: bytes, width: int, height: int, channels: int) -> bytes:
    """PNG minimal (filtre nul, zlib rapide) : plus rapide que l'encodeur MuPDF."""
    stride = width * channels
    raw = bytearray()
    for y in range(height):
        raw += b"\x00"
        raw += samples[y * stride : (y + 1) * stride]
    color_type = {1: 0, 3: 2, 4: 6}[channels]

    def chunk(tag: bytes, data: bytes) -> bytes:
        return len(data).to_bytes(4, "big") + tag + data + (zlib.crc32(tag + data) & 0xFFFFFFFF).to_bytes(4, "big")

    header = width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes([8, color_type, 0, 0, 0])
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(raw), 2)) + chunk(b"IEND", b"")


def has_signatures(doc: fitz.Document) -> bool:
    """Le document porte-t-il une signature remplie ?

    /SigFlags manque dans certains PDF signés : les champs font foi. En cas de
    doute, le document est traité comme signé (enregistrement incrémental, qui
    ne détruit rien).
    """
    try:
        if doc.get_sigflags() < 1 and not doc.is_form_pdf:
            return False
        for page in doc:
            for widget in page.widgets(types=[fitz.PDF_WIDGET_TYPE_SIGNATURE]):
                if widget.is_signed:
                    return True
    except Exception:  # noqa: BLE001
        return True
    return False


def _direction(dir_vec) -> tuple[int, int] | None:
    """Direction d'écriture arrondie à l'un des quatre axes, sinon None."""
    dx, dy = dir_vec
    if abs(dx) > 0.995:
        return (1 if dx > 0 else -1, 0)
    if abs(dy) > 0.995:
        return (0, 1 if dy > 0 else -1)
    return None


def atomic_write(path: str | os.PathLike, data: bytes) -> None:
    """Écriture atomique : fichier temporaire voisin puis remplacement."""
    target = Path(path)
    directory = target.parent
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".destripdf-", suffix=".tmp", dir=str(directory))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.replace(tmp, target)
        except PermissionError as exc:
            raise DocumentError(
                f"« {target.name} » est ouvert ou verrouillé par un autre logiciel : fermez-le ou enregistrez sous un autre nom.",
                "locked",
            ) from exc
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# --- Session de document -----------------------------------------------------


@dataclass
class LineRef:
    """Ligne désignée par l'interface : cadre affiché et texte d'origine."""

    bbox: tuple[float, float, float, float]
    text: str


@dataclass
class Run:
    text: str
    family: str = ""
    size: float = 11.0
    color: str = "#000000"
    bold: bool = False
    italic: bool = False


@dataclass
class _ServerLine:
    """Segment de ligne (texte sans grand écart), coordonnées non pivotées."""

    bbox: fitz.Rect
    direction: tuple[int, int] | None
    spans: list[dict]  # text, font, size, flags, color, origin, bbox
    text: str
    origin: fitz.Point  # ligne de base du fragment principal
    t0: float  # étendue le long de la direction, depuis `origin`
    t1: float

    @property
    def main_size(self) -> float:
        return max((s["size"] for s in self.spans), default=11.0)

    @property
    def min_size(self) -> float:
        return min((s["size"] for s in self.spans), default=11.0) or 1.0


GAP_SPLIT = 0.9  # écart (en corps) au-delà duquel une ligne se coupe en segments
TEXT_FLAGS = fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_PRESERVE_LIGATURES | fitz.TEXT_MEDIABOX_CLIP


SEARCH_FLAGS = TEXT_FLAGS | fitz.TEXT_DEHYPHENATE


def _textpage(page: fitz.Page, flags: int = TEXT_FLAGS, *, contents_only: bool = True) -> fitz.TextPage:
    """Page de texte en coordonnées non pivotées, sans jamais modifier le document.

    PyMuPDF remet /Rotate à 0 le temps de l'extraction : sur une page dont la
    rotation est héritée, la page reçoit alors un /Rotate explicite, ce qui
    modifie un PDF signé au simple affichage. Ici, la matrice de dé-rotation
    produit les mêmes coordonnées sans toucher à la page. `contents_only` écarte
    annotations, champs et apparences de signature (texte non modifiable).
    """
    fz_page = page.this
    if isinstance(fz_page, fitz.mupdf.PdfPage):
        fz_page = fz_page.super()
    derot = page.derotation_matrix if page.rotation else fitz.Identity
    bound = fitz.Rect(page.rect) * derot
    bound.normalize()
    tpage = fitz.mupdf.FzStextPage(fitz.mupdf.FzRect(bound.x0, bound.y0, bound.x1, bound.y1))
    device = fitz.mupdf.fz_new_stext_device(tpage, fitz.mupdf.FzStextOptions(flags))
    run = fitz.mupdf.fz_run_page_contents if contents_only else fitz.mupdf.fz_run_page
    run(fz_page, device, fitz.mupdf.FzMatrix(derot.a, derot.b, derot.c, derot.d, derot.e, derot.f), fitz.mupdf.FzCookie())
    fitz.mupdf.fz_close_device(device)
    textpage = fitz.TextPage(tpage)
    textpage.parent = page
    return textpage


def _contents_textpage(page: fitz.Page, flags: int = TEXT_FLAGS) -> fitz.TextPage:
    """Texte du seul contenu de la page (voir `_textpage`)."""
    return _textpage(page, flags, contents_only=True)


def _segments(page: fitz.Page) -> list[_ServerLine]:
    """Lignes de la page découpées aux grands écarts (colonnes, tabulations)."""
    raw = page.get_text("rawdict", textpage=_contents_textpage(page))
    segments: list[_ServerLine] = []
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            dvec = line.get("dir", (1, 0))
            direction = _direction(dvec)
            d = fitz.Point(direction or dvec)
            groups: list[list[tuple[dict, dict]]] = [[]]
            prev_end = None
            for span in line.get("spans", []):
                size = span.get("size", 11) or 11
                for ch in span.get("chars", []):
                    box = fitz.Rect(ch["bbox"])
                    a0 = box.x0 * d.x + box.y0 * d.y
                    a1 = box.x1 * d.x + box.y1 * d.y
                    a0, a1 = min(a0, a1), max(a0, a1)
                    if ch["c"].isspace() and (a1 - a0) > GAP_SPLIT * size:
                        groups.append([])  # espace élargi : séparation de colonnes
                        prev_end = None
                        continue
                    if prev_end is not None and a0 - prev_end > GAP_SPLIT * size and groups[-1]:
                        groups.append([])
                    groups[-1].append((span, ch))
                    prev_end = a1
            for group in groups:
                while group and group[0][1]["c"].isspace():
                    group.pop(0)
                while group and group[-1][1]["c"].isspace():
                    group.pop()
                if not group:
                    continue
                spans: list[dict] = []
                for span, ch in group:
                    key = (span.get("font"), span.get("size"), span.get("color"), span.get("flags"))
                    if spans and spans[-1]["key"] == key:
                        spans[-1]["text"] += ch["c"]
                        spans[-1]["bbox"] |= fitz.Rect(ch["bbox"])
                    else:
                        spans.append({
                            "key": key,
                            "text": ch["c"],
                            "font": span.get("font", ""),
                            "size": span.get("size", 11) or 11,
                            "flags": span.get("flags", 0),
                            "color": span.get("color", 0),
                            "origin": fitz.Point(ch["origin"]),
                            "bbox": fitz.Rect(ch["bbox"]),
                        })
                bbox = fitz.Rect(spans[0]["bbox"])
                for s in spans[1:]:
                    bbox |= s["bbox"]
                main = max(spans, key=lambda s: s["size"])
                origin = fitz.Point(main["origin"])
                along = []
                for s in spans:
                    r = s["bbox"]
                    for corner in (r.tl, r.tr, r.bl, r.br):
                        along.append((corner.x - origin.x) * d.x + (corner.y - origin.y) * d.y)
                segments.append(_ServerLine(
                    bbox=bbox,
                    direction=direction,
                    spans=spans,
                    text="".join(s["text"] for s in spans),
                    origin=origin,
                    t0=min(along),
                    t1=max(along),
                ))
    return segments


def _close(a: fitz.Rect, b: fitz.Rect, tol: float = 2.0) -> bool:
    return max(abs(a.x0 - b.x0), abs(a.y0 - b.y0), abs(a.x1 - b.x1), abs(a.y1 - b.y1)) <= tol


def _alignment_hint(seg: _ServerLine, others: list[_ServerLine]) -> str:
    """Alignement probable d'une cellule : droite pour une colonne de montants."""
    if seg.direction != (1, 0):
        return "left"
    pitch = seg.main_size * 4
    left = right = center = 0
    cx = (seg.bbox.x0 + seg.bbox.x1) / 2
    for other in others:
        if other is seg or other.direction != (1, 0):
            continue
        if abs(other.bbox.y0 - seg.bbox.y0) > pitch or abs(other.bbox.y0 - seg.bbox.y0) < 0.5:
            continue
        if abs(other.bbox.x0 - seg.bbox.x0) < 0.8:
            left += 1
        if abs(other.bbox.x1 - seg.bbox.x1) < 0.8:
            right += 1
        if abs((other.bbox.x0 + other.bbox.x1) / 2 - cx) < 0.8:
            center += 1
    if right > left and right >= center:
        return "right"
    if center > left and center > right:
        return "center"
    return "left"


class PdfSession:
    """Un document ouvert, ses états successifs et ses opérations."""

    def __init__(self, data: bytes, *, path: str | None = None, name: str | None = None, password: str | None = None):
        self.id = uuid.uuid4().hex
        self.path = str(path) if path else None
        self.name = name or (Path(path).name if path else "Document.pdf")
        self.password = password
        with FITZ_LOCK:
            self.doc = self._open(data)
            self.signed_original = has_signatures(self.doc)
            self.encrypted = bool(self.doc.metadata.get("encryption")) if self.doc.metadata else False
            self.original = data
            self.history = History(data)
            self.saved_state = self.history.state_id
            self.version = 1
            self.page_versions = [1] * self.doc.page_count
            self._heavy_cache: dict[tuple[int, int], bool] = {}
            self._text_cache: dict[tuple[int, int], dict] = {}
        self.opened_at = time.time()

    # -- ouverture / états --

    def _open(self, data: bytes) -> fitz.Document:
        try:
            doc = fitz.open("pdf", data)
        except Exception as exc:  # noqa: BLE001
            raise DocumentError("Ce fichier n'est pas un PDF lisible.", "not_pdf") from exc
        if doc.needs_pass:
            if not self.password or not doc.authenticate(self.password):
                doc.close()
                raise DocumentError("Ce PDF est protégé par un mot de passe.", "password")
        if doc.page_count == 0:
            doc.close()
            raise DocumentError("Ce PDF ne contient aucune page.", "empty")
        return doc

    def _reload(self, data: bytes) -> None:
        old = self.doc
        self.doc = self._open(data)
        try:
            old.close()
        except Exception:  # noqa: BLE001
            pass
        self.version += 1
        self.page_versions = [self.version] * self.doc.page_count
        self._heavy_cache.clear()
        self._text_cache.clear()

    def _snapshot(self) -> bytes:
        return self.doc.tobytes(garbage=0, encryption=fitz.PDF_ENCRYPT_KEEP)

    def _mutate(self, label: str, fn: Callable[[], object], pages: Iterable[int] | None = None, *, structure: bool = False):
        """Applique une opération ; en cas d'échec, revient à l'état courant."""
        with FITZ_LOCK:
            try:
                result = fn()
                data = self._snapshot()
            except Exception:
                self._reload(self.history.current)
                raise
            self.history.push(data, label)
            self.version += 1
            if structure or pages is None:
                self.page_versions = [self.version] * self.doc.page_count
                self._heavy_cache.clear()
                self._text_cache.clear()
            else:
                for index in pages:
                    if 0 <= index < len(self.page_versions):
                        self.page_versions[index] = self.version
            return result

    @property
    def dirty(self) -> bool:
        return self.history.state_id != self.saved_state

    def undo(self) -> dict:
        with FITZ_LOCK:
            self._reload(self.history.undo())
            return self.summary()

    def redo(self) -> dict:
        with FITZ_LOCK:
            self._reload(self.history.redo())
            return self.summary()

    def close(self) -> None:
        with FITZ_LOCK:
            try:
                self.doc.close()
            except Exception:  # noqa: BLE001
                pass

    # -- description --

    def page(self, index: int) -> fitz.Page:
        if not 0 <= index < self.doc.page_count:
            raise DocumentError("Page inexistante.", "bad_page")
        return self.doc[index]

    def unrotated_rect(self, index: int, rect_disp) -> tuple[float, float, float, float]:
        """Cadre affiché -> coordonnées MuPDF non pivotées (pour la signature)."""
        with FITZ_LOCK:
            r = _to_unrot(self.page(index), rect_disp)
            return (r.x0, r.y0, r.x1, r.y1)

    def pages_info(self) -> list[dict]:
        out = []
        for i, page in enumerate(self.doc):
            rect = page.rect
            out.append({"w": round(rect.width, 3), "h": round(rect.height, 3), "rot": page.rotation, "v": self.page_versions[i]})
        return out

    def summary(self) -> dict:
        with FITZ_LOCK:
            meta = self.doc.metadata or {}
            return {
                "id": self.id,
                "name": self.name,
                "path": self.path,
                "title": meta.get("title") or "",
                "page_count": self.doc.page_count,
                "pages": self.pages_info(),
                "version": self.version,
                "dirty": self.dirty,
                "can_undo": self.history.can_undo(),
                "can_redo": self.history.can_redo(),
                "undo_label": self.history.undo_label(),
                "redo_label": self.history.redo_label(),
                "signed": self.signed_original,
                "encrypted": self.encrypted,
                "has_forms": bool(self.doc.is_form_pdf),
                "toc": [[lvl, title, page - 1] for lvl, title, page in self.doc.get_toc(simple=True)][:2000],
            }

    # -- rendu --

    def _image_heavy(self, index: int) -> bool:
        key = (index, self.page_versions[index])
        cached = self._heavy_cache.get(key)
        if cached is not None:
            return cached
        page = self.doc[index]
        bound = fitz.Rect(page.rect) * (page.derotation_matrix if page.rotation else fitz.Identity)
        bound.normalize()
        area = abs(bound) or 1
        covered = 0.0
        try:
            textpage = _textpage(page, fitz.TEXT_PRESERVE_IMAGES)
            for info in textpage.extractIMGINFO():
                covered += abs(fitz.Rect(info["bbox"]) & bound)
        except Exception:  # noqa: BLE001
            covered = 0
        heavy = covered / area > 0.35
        self._heavy_cache[key] = heavy
        return heavy

    def render(self, index: int, scale: float) -> tuple[bytes, str]:
        scale = max(0.05, min(float(scale), 8.0))
        with FITZ_LOCK:
            page = self.page(index)
            rect = page.rect
            pixels = rect.width * rect.height * scale * scale
            if pixels > MAX_RENDER_PIXELS:
                scale = math.sqrt(MAX_RENDER_PIXELS / (rect.width * rect.height))
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False, annots=True)
            if self._image_heavy(index):
                return pix.tobytes("jpg", jpg_quality=88), "image/jpeg"
            samples, width, height, channels = pix.samples, pix.width, pix.height, pix.n
        return encode_png(samples, width, height, channels), "image/png"

    # -- texte --

    def page_text(self, index: int) -> dict:
        with FITZ_LOCK:
            self.page(index)  # contrôle de l'index avant tout accès
            key = (index, self.page_versions[index])
            cached = self._text_cache.get(key)
            if cached is not None:
                return cached
            page = self.page(index)
            segments = _segments(page)
            rot = page.rotation_matrix
            linear = fitz.Matrix(rot.a, rot.b, rot.c, rot.d, 0, 0)
            lines = []
            for number, seg in enumerate(segments):
                dvec = fitz.Point(seg.direction) if seg.direction else fitz.Point(1, 0)
                disp = dvec * linear
                angle = round(math.degrees(math.atan2(disp.y, disp.x)), 2)
                out_spans = []
                for span in seg.spans:
                    flags = span["flags"]
                    choice = fonts.choose_font(
                        span["font"],
                        bold=bool(flags & 16),
                        italic=bool(flags & 2),
                        serif=bool(flags & 4),
                        mono=bool(flags & 8),
                    )
                    out_spans.append({
                        "text": span["text"],
                        "bbox": _rect_list(_to_display(page, span["bbox"])),
                        "origin": [round(c, 2) for c in _pt_display(page, span["origin"])],
                        "size": round(span["size"], 2),
                        "font": span["font"],
                        "family": choice.family,
                        "exact": choice.exact,
                        "bold": choice.bold,
                        "italic": choice.italic,
                        "color": _color_hex(span["color"]),
                    })
                lines.append({
                    "id": number,
                    "bbox": _rect_list(_to_display(page, seg.bbox)),
                    "angle": angle,
                    "text": seg.text,
                    "editable": seg.direction is not None and abs(angle) < 0.5,
                    "align": _alignment_hint(seg, segments),
                    "spans": out_spans,
                })
            result = {"page": index, "v": self.page_versions[index], "lines": lines}
            self._text_cache[key] = result
            return result

    def search(self, query: str, limit: int = 5000) -> list[dict]:
        query = (query or "").strip()
        if not query:
            return []
        hits = []
        with FITZ_LOCK:
            for page in self.doc:
                # Annotations comprises : on retrouve aussi ses notes et textes ajoutés.
                textpage = _textpage(page, SEARCH_FLAGS, contents_only=False)
                for rect in page.search_for(query, textpage=textpage):
                    hits.append({"page": page.number, "rect": _rect_list(_to_display(page, rect))})
                    if len(hits) >= limit:
                        return hits
        return hits

    # -- modification d'une ligne --

    def _match_line(self, page: fitz.Page, ref: LineRef) -> _ServerLine:
        target = _to_unrot(page, ref.bbox)
        best, best_score = None, 0.0
        for line in _segments(page):
            inter = abs(line.bbox & target)
            union = abs(line.bbox) + abs(target) - inter
            score = inter / union if union else 0
            if line.text.strip() == ref.text.strip():
                score += 0.5
            if score > best_score:
                best, best_score = line, score
        if best is None or best_score < 0.9:
            raise DocumentError("Cette ligne a changé depuis l'affichage : cliquez de nouveau dessus.", "stale")
        if best.direction is None:
            raise DocumentError("Le texte incliné ne se modifie pas : utilisez « Effacer une zone » puis « Ajouter du texte ».", "angled")
        return best

    @staticmethod
    def _band(line: _ServerLine, lo: float, hi: float) -> fitz.Rect:
        """Bande au cœur de la ligne, entre lo et hi corps au-dessus de la ligne de base."""
        d = fitz.Point(line.direction)
        up = fitz.Point(d.y, -d.x)
        size = line.min_size
        inset = min(1.0, max(0.1, (line.t1 - line.t0) * 0.01))
        o = line.origin
        points = [
            fitz.Point(o.x + d.x * t + up.x * u, o.y + d.y * t + up.y * u)
            for t in (line.t0 + inset, line.t1 - inset)
            for u in (lo * size, hi * size)
        ]
        rect = fitz.Rect(points[0], points[0])
        for p in points[1:]:
            rect |= p
        return rect

    def _pending_redactions(self, page: fitz.Page) -> bool:
        return any(a.type[0] == fitz.PDF_ANNOT_REDACT for a in page.annots())

    def edit_line(self, index: int, ref: LineRef, runs: list[Run], align: str = "left") -> dict:
        """Remplace un segment de texte : retrait de l'ancien, écriture du nouveau."""
        if align not in ("left", "center", "right"):
            align = "left"

        def apply():
            page = self.page(index)
            if self._pending_redactions(page):
                raise DocumentError("Cette page contient des caviardages en attente : appliquez-les ou retirez-les d'abord.", "pending_redactions")
            line = self._match_line(page, ref)
            for lo, hi in ((0.18, 0.62), (0.3, 0.5)):
                # Bande au cœur de la ligne : elle touche chaque glyphe du segment, jamais ses voisins.
                band = self._band(line, lo, hi)
                zone = fitz.Rect(band.x0 - 2, band.y0 - 2, band.x1 + 2, band.y1 + 2)
                neighbours = [s for s in _segments(page) if s.bbox.intersects(zone) and not (_close(s.bbox, line.bbox, 0.01) and s.text == line.text)]
                page.add_redact_annot(band, fill=False)
                page.apply_redactions(
                    images=fitz.PDF_REDACT_IMAGE_NONE,
                    graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                    text=fitz.PDF_REDACT_TEXT_REMOVE,
                )
                remaining = _segments(page)

                def known(seg: _ServerLine) -> bool:
                    return any(n.text == seg.text and _close(n.bbox, seg.bbox) for n in neighbours)

                intact = all(any(r.text == n.text and _close(r.bbox, n.bbox) for r in remaining) for n in neighbours)
                leftover = [r for r in remaining if r.bbox.intersects(band) and r.text.strip() and not known(r)]
                if intact and not leftover:
                    break
                # Échec : on repart de l'état courant et on resserre la bande.
                self._reload(self.history.current)
                page = self.page(index)
                line = self._match_line(page, ref)
            else:
                raise DocumentError(
                    "Impossible d'isoler cette ligne sans toucher ses voisines : utilisez « Effacer une zone » puis « Ajouter du texte ».",
                    "overlap",
                )
            self._write_runs(page, line, runs, align)

        self._mutate("Modification du texte", apply, [index])
        return self.summary()

    def _write_runs(self, page: fitz.Page, line: _ServerLine, runs: list[Run], align: str) -> None:
        origin, t0, t1 = line.origin, line.t0, line.t1
        prepared = []
        width = 0.0
        for run in runs:
            # Espaces insécables -> espace : un même glyphe pour deux caractères
            # rendrait la copie et la recherche du texte ambiguës.
            run.text = run.text.replace(" ", " ").replace(" ", " ")
            if not run.text:
                continue
            size = max(1.0, min(float(run.size or 11), 400.0))
            choice = fonts.font_for_family(run.family, bold=run.bold, italic=run.italic) if run.family else fonts.choose_font(
                "", bold=run.bold, italic=run.italic, serif=False, mono=False
            )
            font = fonts.subset_font(choice, run.text)
            prepared.append((run, size, font))
            width += font.text_length(run.text, fontsize=size)
        if not prepared:
            return
        start = t0
        if align == "center":
            start = (t0 + t1) / 2 - width / 2
        elif align == "right":
            start = t1 - width
        rotation = {(1, 0): 0, (0, 1): -90, (-1, 0): 180, (0, -1): 90}[line.direction]
        x = start
        for run, size, font in prepared:
            # On écrit à plat à partir de l'origine, puis on fait pivoter autour d'elle.
            pos = fitz.Point(origin.x + x, origin.y)
            writer = fitz.TextWriter(page.rect, color=parse_color(run.color))
            writer.append(pos, run.text, font=font, fontsize=size)
            if rotation:
                writer.write_text(page, morph=(origin, fitz.Matrix(rotation)))
            else:
                writer.write_text(page)
            x += font.text_length(run.text, fontsize=size)

    # -- annotations --

    def _author(self, author: str | None) -> str:
        return (author or os.environ.get("USERNAME") or "").strip()[:80]

    def annotations(self, index: int) -> list[dict]:
        with FITZ_LOCK:
            page = self.page(index)
            out = []
            for annot in page.annots():
                kind = annot.type[1]
                info = annot.info
                colors = annot.colors or {}
                item = {
                    "id": annot.xref,
                    "type": kind,
                    "label": ANNOT_LABELS.get(kind, kind),
                    "rect": _rect_list(_to_display(page, annot.rect)),
                    "content": info.get("content", ""),
                    "author": info.get("title", ""),
                    "modified": _pdf_date(info.get("modDate") or info.get("creationDate") or ""),
                    "color": _color_hex(colors.get("stroke")) or _color_hex(colors.get("fill")),
                    "width": (annot.border or {}).get("width", 1) if kind not in ("Text", "FreeText") else 0,
                    "movable": kind in MOVABLE,
                    "editable": kind in EDITABLE_CONTENT,
                }
                if kind == "FreeText":
                    item["fontsize"] = _freetext_size(annot)
                    item["text_color"] = _freetext_color(annot)
                out.append(item)
            return out

    def all_annotations(self) -> list[dict]:
        with FITZ_LOCK:
            result = []
            for index in range(self.doc.page_count):
                for item in self.annotations(index):
                    if item["type"] in ("Popup", "Link", "Widget"):
                        continue
                    item["page"] = index
                    result.append(item)
            return result

    def _annot(self, page: fitz.Page, annot_id: int) -> fitz.Annot:
        for annot in page.annots():
            if annot.xref == int(annot_id):
                return annot
        raise DocumentError("Cette annotation n'existe plus.", "stale")

    def add_annotation(self, index: int, spec: dict) -> dict:
        kind = spec.get("type")
        author = self._author(spec.get("author"))
        color = parse_color(spec.get("color"), (0.93, 0.76, 0.15) if kind == "highlight" else (0.16, 0.2, 0.23))
        width = max(0.25, min(float(spec.get("width") or 1.5), 24.0))
        created: dict = {}

        def apply():
            page = self.page(index)
            if kind == "note":
                point = _pt_unrot(page, spec["point"])
                annot = page.add_text_annot(point, spec.get("content", ""), icon="Comment")
                annot.set_colors(stroke=parse_color(spec.get("color"), (0.98, 0.8, 0.25)))
            elif kind == "freetext":
                size = max(4.0, min(float(spec.get("fontsize") or 12), 144.0))
                rect = _to_unrot(page, _freetext_box(spec["rect"], spec.get("content", ""), size))
                annot = page.add_freetext_annot(
                    rect,
                    spec.get("content", ""),
                    fontsize=size,
                    fontname="helv",
                    text_color=parse_color(spec.get("color"), (0, 0, 0)),
                    rotate=page.rotation,
                )
            elif kind in ("highlight", "underline", "strikeout"):
                # Coins transformés un à un : le quadrilatère garde le sens de lecture
                # affiché (indispensable sur une page pivotée).
                quads = [fitz.Rect(r).quad * page.derotation_matrix for r in spec.get("rects", []) if len(r) == 4]
                if not quads:
                    raise DocumentError("Sélectionnez du texte à marquer.", "empty")
                adder = {"highlight": page.add_highlight_annot, "underline": page.add_underline_annot, "strikeout": page.add_strikeout_annot}[kind]
                annot = adder(quads=quads)
                annot.set_colors(stroke=color)
            elif kind == "ink":
                strokes = [[tuple(_pt_unrot(page, p)) for p in stroke] for stroke in spec.get("strokes", []) if len(stroke) >= 2]
                if not strokes:
                    raise DocumentError("Tracé vide.", "empty")
                annot = page.add_ink_annot(strokes)
                annot.set_border(width=width)
                annot.set_colors(stroke=color)
            elif kind in ("rect", "ellipse"):
                rect = _to_unrot(page, spec["rect"])
                annot = page.add_rect_annot(rect) if kind == "rect" else page.add_circle_annot(rect)
                annot.set_border(width=width)
                annot.set_colors(stroke=color)
            elif kind == "arrow":
                p1, p2 = _pt_unrot(page, spec["from"]), _pt_unrot(page, spec["to"])
                annot = page.add_line_annot(p1, p2)
                annot.set_border(width=width)
                annot.set_colors(stroke=color, fill=color)
                annot.set_line_ends(fitz.PDF_ANNOT_LE_NONE, fitz.PDF_ANNOT_LE_CLOSED_ARROW)
            elif kind == "stamp_image":
                rect = _to_unrot(page, spec["rect"])
                image = spec.get("image")
                if not image:
                    raise DocumentError("Aucune image de signature enregistrée.", "no_image")
                if page.rotation:
                    # L'apparence se dessine dans l'espace non pivoté : on pré-tourne
                    # l'image pour qu'elle s'affiche droite.
                    image = _rotated_png(image, page.rotation)
                annot = page.add_stamp_annot(rect, stamp=image)
            else:
                raise DocumentError("Type d'annotation inconnu.", "bad_type")
            content = str(spec.get("content") or ("Signature manuscrite" if kind == "stamp_image" else ""))[:20000]
            annot.set_info(title=author, content=content)
            annot.update()
            created["id"] = annot.xref

        labels = {
            "note": "Ajout d'une note", "freetext": "Ajout de texte", "highlight": "Surlignage",
            "underline": "Soulignement", "strikeout": "Texte barré", "ink": "Dessin", "rect": "Rectangle",
            "ellipse": "Ellipse", "arrow": "Flèche", "stamp_image": "Signature manuscrite",
        }
        self._mutate(labels.get(kind, "Annotation"), apply, [index])
        out = self.summary()
        out["created"] = created.get("id")
        return out

    def update_annotation(self, index: int, annot_id: int, changes: dict) -> dict:
        def apply():
            page = self.page(index)
            annot = self._annot(page, annot_id)
            kind = annot.type[1]
            if "content" in changes and kind in EDITABLE_CONTENT:
                annot.set_info(content=str(changes["content"])[:20000])
                if kind == "FreeText":
                    shown = _to_display(page, annot.rect)
                    grown = _freetext_box(shown, str(changes["content"]), _freetext_size(annot))
                    if grown != shown:
                        annot.set_rect(_to_unrot(page, grown))
            if "rect" in changes or "offset" in changes:
                if kind not in MOVABLE:
                    raise DocumentError("Cette annotation ne se déplace pas.", "immovable")
                if kind in ("Ink", "Line"):
                    dx, dy = changes.get("offset", (0, 0))
                    annot = self._move_by_recreate(page, annot, dx, dy)
                else:
                    if "rect" in changes:
                        rect = _to_unrot(page, changes["rect"])
                    else:
                        dx, dy = changes["offset"]
                        shown = _to_display(page, annot.rect)
                        rect = _to_unrot(page, shown + (dx, dy, dx, dy))
                    if rect.width < 2 or rect.height < 2:
                        raise DocumentError("Cadre trop petit.", "bad_rect")
                    annot.set_rect(rect)
            if "color" in changes:
                color = parse_color(changes["color"])
                if kind == "FreeText":
                    annot.update(text_color=color)
                else:
                    annot.set_colors(stroke=color, fill=color if kind == "Line" else None)
            if "width" in changes and kind in ("Ink", "Square", "Circle", "Line"):
                annot.set_border(width=max(0.25, min(float(changes["width"]), 24.0)))
            if kind == "FreeText":
                size = changes.get("fontsize")
                annot.update(fontsize=float(size) if size else _freetext_size(annot), text_color=parse_color(changes["color"]) if "color" in changes else None)
            else:
                annot.update()

        self._mutate("Modification d'une annotation", apply, [index])
        return self.summary()

    def _move_by_recreate(self, page: fitz.Page, annot: fitz.Annot, dx: float, dy: float) -> fitz.Annot:
        """Déplace un tracé ou une flèche : recréation à l'identique, décalée."""
        kind = annot.type[1]
        info = annot.info
        colors = annot.colors or {}
        border = annot.border or {}
        shift = fitz.Point(dx, dy) * fitz.Matrix(page.derotation_matrix.a, page.derotation_matrix.b, page.derotation_matrix.c, page.derotation_matrix.d, 0, 0)
        if kind == "Ink":
            strokes = [[(p[0] + shift.x, p[1] + shift.y) for p in stroke] for stroke in (annot.vertices or [])]
            page.delete_annot(annot)
            new = page.add_ink_annot(strokes)
        else:
            vertices = annot.vertices or []
            if len(vertices) < 2:
                raise DocumentError("Flèche illisible.", "bad_annot")
            line_ends = annot.line_ends
            page.delete_annot(annot)
            new = page.add_line_annot(
                fitz.Point(vertices[0]) + shift, fitz.Point(vertices[1]) + shift
            )
            if line_ends:
                new.set_line_ends(*line_ends)
        new.set_border(width=border.get("width", 1.5))
        new.set_colors(stroke=colors.get("stroke"), fill=colors.get("fill"))
        new.set_info(title=info.get("title", ""), content=info.get("content", ""))
        return new

    def delete_annotation(self, index: int, annot_id: int) -> dict:
        def apply():
            page = self.page(index)
            page.delete_annot(self._annot(page, annot_id))

        self._mutate("Suppression d'une annotation", apply, [index])
        return self.summary()

    # -- effacer une zone (caviardage réel) --

    def erase(self, index: int, rect_disp) -> dict:
        def apply():
            page = self.page(index)
            if self._pending_redactions(page):
                raise DocumentError("Cette page contient des caviardages en attente : appliquez-les ou retirez-les d'abord.", "pending_redactions")
            rect = _to_unrot(page, rect_disp)
            if rect.width < 1 or rect.height < 1:
                raise DocumentError("Zone trop petite.", "bad_rect")
            page.add_redact_annot(rect, fill=(1, 1, 1))
            page.apply_redactions(
                images=fitz.PDF_REDACT_IMAGE_PIXELS,
                graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
                text=fitz.PDF_REDACT_TEXT_REMOVE,
            )

        self._mutate("Effacement d'une zone", apply, [index])
        return self.summary()

    # -- formulaires --

    def form_fields(self, index: int) -> list[dict]:
        with FITZ_LOCK:
            page = self.page(index)
            out = []
            for widget in page.widgets():
                kind = widget.field_type
                if kind == fitz.PDF_WIDGET_TYPE_SIGNATURE:
                    continue
                item = {
                    "id": widget.xref,
                    "name": widget.field_name or "",
                    "label": widget.field_label or widget.field_name or "",
                    "type": widget.field_type_string,
                    "rect": _rect_list(_to_display(page, widget.rect)),
                    "value": widget.field_value if not isinstance(widget.field_value, bool) else bool(widget.field_value),
                    "readonly": bool(widget.field_flags & 1),
                    "multiline": bool(widget.field_flags & 4096) if kind == fitz.PDF_WIDGET_TYPE_TEXT else False,
                    "fontsize": widget.text_fontsize or 0,
                }
                if kind in (fitz.PDF_WIDGET_TYPE_CHECKBOX, fitz.PDF_WIDGET_TYPE_RADIOBUTTON):
                    item["on_state"] = widget.on_state()
                    item["checked"] = widget.field_value not in (False, "Off", "", None)
                if kind in (fitz.PDF_WIDGET_TYPE_COMBOBOX, fitz.PDF_WIDGET_TYPE_LISTBOX):
                    item["choices"] = [c if isinstance(c, str) else c[1] for c in (widget.choice_values or [])]
                out.append(item)
            return out

    def set_field(self, index: int, field_id: int, value) -> dict:
        def apply():
            page = self.page(index)
            for widget in page.widgets():
                if widget.xref == int(field_id):
                    if widget.field_flags & 1:
                        raise DocumentError("Ce champ est en lecture seule.", "readonly")
                    kind = widget.field_type
                    if kind in (fitz.PDF_WIDGET_TYPE_CHECKBOX, fitz.PDF_WIDGET_TYPE_RADIOBUTTON):
                        widget.field_value = widget.on_state() if value else "Off"
                    else:
                        widget.field_value = str(value)[:10000]
                    widget.update()
                    return
            raise DocumentError("Ce champ n'existe plus.", "stale")

        self._mutate("Saisie d'un champ", apply, [index])
        return self.summary()

    # -- pages --

    def rotate_pages(self, indexes: list[int], angle: int) -> dict:
        if angle % 90:
            raise DocumentError("Rotation par quart de tour uniquement.", "bad_angle")

        def apply():
            for index in indexes:
                page = self.page(index)
                page.set_rotation((page.rotation + angle) % 360)

        self._mutate("Rotation de page", apply, structure=True)
        return self.summary()

    def delete_pages(self, indexes: list[int]) -> dict:
        unique = sorted(set(int(i) for i in indexes))
        if not unique:
            raise DocumentError("Aucune page sélectionnée.", "empty")

        def apply():
            if len(unique) >= self.doc.page_count:
                raise DocumentError("Un PDF garde au moins une page.", "last_page")
            for index in unique:
                self.page(index)
            self.doc.delete_pages(unique)

        self._mutate("Suppression de page" if len(unique) == 1 else "Suppression de pages", apply, structure=True)
        return self.summary()

    def move_page(self, source: int, target: int) -> dict:
        def apply():
            count = self.doc.page_count
            if not (0 <= source < count and 0 <= target < count) or source == target:
                raise DocumentError("Déplacement impossible.", "bad_page")
            # move_page insère avant `to` : -1 = en fin de document
            to = target + 1 if target > source else target
            self.doc.move_page(source, to if to < count else -1)

        self._mutate("Déplacement de page", apply, structure=True)
        return self.summary()

    def insert_pdf(self, data: bytes, at: int | None = None, password: str | None = None) -> dict:
        """Insère un PDF avant la page `at` (en fin de document si `at` est absent)."""
        with FITZ_LOCK:  # MuPDF n'est pas sûr entre fils d'exécution, y compris pour la source
            try:
                source = fitz.open("pdf", data)
            except Exception as exc:  # noqa: BLE001
                raise DocumentError("Le fichier à insérer n'est pas un PDF lisible.", "not_pdf") from exc
            try:
                if source.needs_pass and not (password and source.authenticate(password)):
                    raise DocumentError("Le PDF à insérer est protégé par un mot de passe.", "password")

                def apply():
                    count = self.doc.page_count
                    start = count if at is None else max(0, min(int(at), count))
                    self.doc.insert_pdf(source, start_at=start)

                self._mutate("Insertion de pages", apply, structure=True)
            finally:
                source.close()
        return self.summary()

    @property
    def page_count(self) -> int:
        with FITZ_LOCK:
            return self.doc.page_count

    # -- enregistrement --

    def _incremental_bytes(self) -> bytes:
        """Original + une seule mise à jour incrémentale (signatures préservées)."""
        fd, tmp = tempfile.mkstemp(prefix="destripdf-base-", suffix=".pdf")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(self.original)
            base = fitz.open(tmp)
            if base.needs_pass:
                base.authenticate(self.password or "")
            try:
                if base.is_repaired or not base.can_save_incrementally():
                    raise DocumentError(
                        "Ce PDF signé a une structure endommagée, réparée à l'ouverture : il ne peut pas recevoir "
                        "de modification sans être réécrit, ce qui invaliderait ses signatures.",
                        "repaired_signed",
                    )
                cur = self.doc
                base_len = base.xref_length()
                changed = 0
                for xref in range(1, cur.xref_length()):
                    try:
                        cur_obj = cur.xref_object(xref, compressed=False)
                    except Exception:  # noqa: BLE001 - objet libre
                        continue
                    if cur_obj in ("null", ""):
                        continue
                    is_stream = cur.xref_is_stream(xref)
                    if xref >= base_len:
                        while base.xref_length() <= xref:
                            base.get_new_xref()
                        same = False
                    else:
                        try:
                            same = base.xref_object(xref, compressed=False) == cur_obj
                        except Exception:  # noqa: BLE001
                            same = False
                        if same and is_stream:
                            same = base.xref_stream_raw(xref) == cur.xref_stream_raw(xref)
                    if same:
                        continue
                    base.update_object(xref, cur_obj)
                    if is_stream:
                        _put_raw_stream(base, xref, cur.xref_stream_raw(xref))
                    changed += 1
                if not changed:
                    return self.original
                base.save(tmp, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
            finally:
                base.close()
            with open(tmp, "rb") as handle:
                return handle.read()
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def export_bytes(self, *, force_full: bool = False) -> bytes:
        """PDF à écrire sur disque ou à signer, dans son état courant.

        Un document signé reçoit une seule mise à jour incrémentale ; `force_full`
        (confirmé par l'utilisateur) le réécrit entièrement, signatures invalidées.
        """
        with FITZ_LOCK:
            if self.history.state_id == self.saved_state and self.history.current is self.original:
                return self.original
            if self.signed_original and not force_full:
                return self._incremental_bytes()
            return self.doc.tobytes(garbage=3, deflate=True, encryption=fitz.PDF_ENCRYPT_KEEP)

    def save(self, path: str | None = None, *, force_full: bool = False) -> dict:
        target = path or self.path
        if not target:
            raise DocumentError("Choisissez où enregistrer ce document.", "no_path")
        with FITZ_LOCK:
            data = self.export_bytes(force_full=force_full)
            atomic_write(target, data)
            if self.signed_original and force_full:
                # Réécriture complète : objets renumérotés, le fichier écrit devient la base.
                return self.replace_with(data, path=target)
            self.path = str(target)
            self.name = Path(target).name
            self.saved_state = self.history.state_id
            if self.signed_original:
                # La nouvelle base des mises à jour incrémentales est le fichier écrit.
                self.original = data
            return self.summary()

    def replace_with(self, data: bytes, *, path: str | None) -> dict:
        """Remplace le document (après signature) : nouvelle base, historique remis à zéro."""
        with FITZ_LOCK:
            self._reload(data)
            self.original = data
            self.history.reset(data)
            self.saved_state = self.history.state_id
            self.signed_original = has_signatures(self.doc)
            if path:
                self.path = str(path)
                self.name = Path(path).name
            return self.summary()


def _put_raw_stream(doc: fitz.Document, xref: int, raw: bytes) -> None:
    """Remplace un flux par ses octets bruts, filtres conservés."""
    pdf = fitz._as_pdf_document(doc)
    obj = fitz.mupdf.pdf_new_indirect(pdf, xref, 0)
    buf = fitz.JM_BufferFromBytes(raw)
    fitz.mupdf.pdf_update_stream(pdf, obj, buf, 1)


def _pdf_date(value: str) -> str:
    match = re.match(r"D:(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?(\d{2})?", value or "")
    if not match:
        return ""
    y, mo, d, h, mi, s = (int(g) if g else 0 for g in match.groups())
    try:
        return datetime(y, mo, d, h, mi, s).isoformat()
    except ValueError:
        return ""


def _rotated_png(png: bytes, angle: int) -> bytes:
    """Image tournée de `angle` degrés dans le sens antihoraire (transparence conservée)."""
    source = fitz.Pixmap(png)
    width, height = (source.height, source.width) if angle % 180 else (source.width, source.height)
    scratch = fitz.open()
    try:
        page = scratch.new_page(width=width, height=height)
        page.insert_image(page.rect, stream=png, rotate=angle)
        return page.get_pixmap(alpha=True).tobytes("png")
    finally:
        scratch.close()


_HELV: fitz.Font | None = None


def _helv() -> fitz.Font:
    global _HELV
    if _HELV is None:
        _HELV = fitz.Font("helv")
    return _HELV


def _freetext_box(rect_disp, content: str, size: float) -> fitz.Rect:
    """Cadre affiché d'un texte libre, élargi pour qu'aucune ligne ne soit coupée.

    MuPDF compose le texte libre en Helvetica dans le cadre : un cadre mesuré par
    l'interface avec une autre police peut être trop étroit de quelques points.
    """
    box = fitz.Rect(rect_disp)
    lines = (content or "").split("\n") or [""]
    helv = _helv()
    width = 0.0
    for line in lines:
        try:
            # Même mesure que la mise en page de MuPDF (« — » et « € » compris).
            width = max(width, helv.text_length(line, fontsize=size))
        except Exception:  # noqa: BLE001 - estimation prudente
            width = max(width, len(line) * size * 0.65)
    box.x1 = max(box.x1, box.x0 + width + 6)
    box.y1 = max(box.y1, box.y0 + len(lines) * size * 1.25 + 4)
    return box


def _default_appearance(annot: fitz.Annot) -> str:
    """Chaîne /DA d'une annotation de texte libre (« 0 0 0 rg /Helv 12 Tf »)."""
    try:
        kind, value = annot.parent.parent.xref_get_key(annot.xref, "DA")
    except Exception:  # noqa: BLE001
        return ""
    return value if kind == "string" else ""


def _freetext_size(annot: fitz.Annot) -> float:
    match = re.search(r"([\d.]+)\s+Tf", _default_appearance(annot))
    return float(match.group(1)) if match else 12.0


def _freetext_color(annot: fitz.Annot) -> str:
    da = _default_appearance(annot)
    match = re.search(r"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+rg", da or "")
    if match:
        return _color_hex(tuple(float(g) for g in match.groups()))
    match = re.search(r"([\d.]+)\s+g\b", da or "")
    if match:
        v = float(match.group(1))
        return _color_hex((v, v, v))
    return "#000000"


def read_file(path: str) -> bytes:
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except FileNotFoundError as exc:
        raise DocumentError("Ce fichier n'existe plus.", "not_found") from exc
    except PermissionError as exc:
        raise DocumentError("Accès refusé à ce fichier.", "denied") from exc


def file_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
