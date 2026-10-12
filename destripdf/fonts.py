"""Choix et préparation des polices pour réécrire une ligne de texte.

Ordre de préférence : police d'origine intégrée complète (rare), police Windows
du même nom, puis police de base selon les attributs (sans empattement,
empattement, chasse fixe). La police retenue est réduite aux seuls glyphes
utiles (fontTools) pour que chaque modification reste légère.
"""

from __future__ import annotations

import io
import logging
import os
import re
import threading
import winreg
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pymupdf as fitz

logging.getLogger("fontTools").setLevel(logging.ERROR)

WINDOWS_FONTS = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
USER_FONTS = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts"

# Polices de base (PDF standard 14) -> équivalent Windows à métrique compatible.
BASE14_EQUIVALENTS = {
    "helvetica": "arial",
    "arialmt": "arial",
    "timesnewromanpsmt": "times new roman",
    "times": "times new roman",
    "timesroman": "times new roman",
    "courier": "courier new",
    "couriernewpsmt": "courier new",
    "symbol": "symbol",
}

# Familles de repli selon les attributs du texte.
FALLBACK = {"sans": "arial", "serif": "times new roman", "mono": "courier new"}

_STYLE_WORDS = re.compile(
    r"(?i)[-,_ ]?(bold|bd|black|heavy|semibold|demibold|demi|medium|light|thin|book|regular|roman|normal|"
    r"italic|it|oblique|condensed|cond|narrow|mt|ps|psmt)\b"
)


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


@dataclass(frozen=True)
class FontChoice:
    """Police retenue pour un fragment : fichier, nom affichable et attributs."""

    path: str
    index: int
    family: str  # nom CSS pour l'aperçu dans l'interface
    bold: bool
    italic: bool
    exact: bool  # même famille que l'original


class FontIndex:
    """Index des polices installées (registre Windows), construit une fois."""

    def __init__(self):
        self._lock = threading.Lock()
        self._faces: dict[str, dict[tuple[bool, bool], tuple[str, int]]] | None = None
        self._display: dict[str, str] = {}

    def _build(self):
        faces: dict[str, dict[tuple[bool, bool], tuple[str, int]]] = {}
        display: dict[str, str] = {}
        for root, base in ((winreg.HKEY_LOCAL_MACHINE, WINDOWS_FONTS), (winreg.HKEY_CURRENT_USER, USER_FONTS)):
            try:
                key = winreg.OpenKey(root, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts")
            except OSError:
                continue
            with key:
                i = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, i)
                    except OSError:
                        break
                    i += 1
                    if not isinstance(value, str):
                        continue
                    path = Path(value) if os.path.isabs(value) else base / value
                    if path.suffix.lower() not in (".ttf", ".otf", ".ttc"):
                        continue
                    label = re.sub(r"\s*\((TrueType|OpenType)\)\s*$", "", name, flags=re.I)
                    # « Cambria & Cambria Math » : une entrée par famille de la collection
                    for idx, part in enumerate(label.split(" & ")):
                        bold = bool(re.search(r"(?i)\b(bold|black|heavy)\b", part))
                        italic = bool(re.search(r"(?i)\b(italic|oblique)\b", part))
                        family = re.sub(r"(?i)\s+(bold|italic|oblique|black|heavy)\b", "", part).strip()
                        key_name = _norm(family)
                        if not key_name:
                            continue
                        display.setdefault(key_name, family)
                        faces.setdefault(key_name, {}).setdefault((bold, italic), (str(path), idx if path.suffix.lower() == ".ttc" else 0))
        self._faces, self._display = faces, display

    def faces(self):
        with self._lock:
            if self._faces is None:
                self._build()
            return self._faces

    def find(self, family: str, bold: bool, italic: bool) -> tuple[str, int, str] | None:
        faces = self.faces()
        key = _norm(family)
        entry = faces.get(key)
        if entry is None:
            return None
        for wanted in ((bold, italic), (bold, False), (False, italic), (False, False)):
            if wanted in entry:
                path, idx = entry[wanted]
                if os.path.exists(path):
                    return path, idx, self._display.get(key, family)
        return None

    def families(self) -> list[str]:
        faces = self.faces()
        return sorted(self._display[k] for k in faces if (False, False) in faces[k])


FONT_INDEX = FontIndex()


def split_font_name(raw: str) -> tuple[str, bool, bool]:
    """« ABCDEF+Arial-BoldItalicMT » -> (« Arial », gras, italique)."""
    name = raw.split("+", 1)[1] if re.match(r"^[A-Z]{6}\+", raw) else raw
    bold = bool(re.search(r"(?i)(bold|black|heavy|semibold|demi|,bd|-bd)", name))
    italic = bool(re.search(r"(?i)(italic|oblique|,it|-it$)", name))
    family = re.split(r"[-,]", name, maxsplit=1)[0]
    family = _STYLE_WORDS.sub("", family)
    # « TimesNewRomanPS » -> « Times New Roman »
    family = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", family).strip()
    return family or name, bold, italic


def choose_font(raw_name: str, *, bold: bool, italic: bool, serif: bool, mono: bool) -> FontChoice:
    family, name_bold, name_italic = split_font_name(raw_name or "")
    bold = bold or name_bold
    italic = italic or name_italic
    candidates = [family]
    equivalent = BASE14_EQUIVALENTS.get(_norm(family))
    if equivalent:
        candidates.append(equivalent)
    for candidate in candidates:
        found = FONT_INDEX.find(candidate, bold, italic)
        if found:
            path, idx, display = found
            return FontChoice(path, idx, display, bold, italic, exact=True)
    fallback = FALLBACK["mono" if mono else "serif" if serif else "sans"]
    found = FONT_INDEX.find(fallback, bold, italic)
    if found:
        path, idx, display = found
        return FontChoice(path, idx, display, bold, italic, exact=False)
    return FontChoice("", 0, "Helvetica", bold, italic, exact=False)


def font_for_family(family: str, *, bold: bool, italic: bool) -> FontChoice:
    """Police choisie explicitement dans l'interface."""
    found = FONT_INDEX.find(family, bold, italic)
    if found:
        path, idx, display = found
        return FontChoice(path, idx, display, bold, italic, exact=True)
    return choose_font(family, bold=bold, italic=italic, serif=False, mono=False)


_SUBSET_LOCK = threading.Lock()


@lru_cache(maxsize=8)
def _file_bytes(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


def _open_ttfont(path: str, index: int):
    from fontTools.ttLib import TTFont

    data = io.BytesIO(_file_bytes(path))
    if path.lower().endswith(".ttc"):
        return TTFont(data, fontNumber=index, lazy=False)
    return TTFont(data, lazy=False)


def font_bytes(choice: FontChoice) -> bytes:
    """Police complète (membre extrait d'une collection .ttc si besoin)."""
    if not choice.path.lower().endswith(".ttc"):
        return _file_bytes(choice.path)
    with _SUBSET_LOCK:
        font = _open_ttfont(choice.path, choice.index)
        out = io.BytesIO()
        font.save(out)
    return out.getvalue()


def subset_font(choice: FontChoice, text: str) -> fitz.Font:
    """Police réduite aux glyphes de `text` (repli : police complète, puis Helvetica)."""
    if not choice.path:
        return _base14(choice)
    chars = "".join(sorted(set(text + " ")))
    try:
        data = _subset_bytes(choice.path, choice.index, chars)
        font = fitz.Font(fontbuffer=data)
        if all(font.has_glyph(ord(c)) or c.isspace() for c in text):
            return font
    except Exception:  # noqa: BLE001 - police non réductible : on garde la complète
        pass
    try:
        return fitz.Font(fontbuffer=font_bytes(choice))
    except Exception:  # noqa: BLE001
        return _base14(choice)


@lru_cache(maxsize=256)
def _subset_bytes(path: str, index: int, chars: str) -> bytes:
    from fontTools import subset

    options = subset.Options()
    options.layout_features = ["kern", "liga", "clig", "calt", "ccmp", "locl", "mark", "mkmk"]
    options.name_IDs = ["*"]
    options.name_languages = ["*"]
    options.notdef_outline = True
    options.glyph_names = False
    options.hinting = False
    options.legacy_kern = True
    options.symbol_cmap = True
    options.recalc_bounds = True
    with _SUBSET_LOCK:
        font = _open_ttfont(path, index)
        subsetter = subset.Subsetter(options=options)
        subsetter.populate(text=chars)
        subsetter.subset(font)
        out = io.BytesIO()
        font.save(out)
    return out.getvalue()


def _base14(choice: FontChoice) -> fitz.Font:
    code = {(False, False): "helv", (True, False): "hebo", (False, True): "heit", (True, True): "hebi"}
    return fitz.Font(code[(choice.bold, choice.italic)])
