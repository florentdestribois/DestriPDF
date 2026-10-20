"""Impression par le pilote de l'imprimante, comme Acrobat.

DestriPDF a sa propre boîte Imprimer (imprimante, pages, copies, livret) ; son
bouton « Préférences de l'imprimante » ouvre la fenêtre de réglages du pilote
(`DocumentProperties`) : recto verso, bac, couleur… La boîte d'impression de
Windows n'est pas utilisée : sur Windows 11 elle est remplacée par une boîte
moderne qui ne donne pas toujours accès au pilote.

Pages normales : chaque page est rendue par MuPDF (annotations, champs et
signatures visibles compris) à la résolution de l'imprimante, plafonnée à
300 ppp, ajustée à la zone imprimable, centrée, et tournée d'un quart de tour
vers la gauche si son orientation diffère de celle de la feuille.

Livret : DestriPDF compose les faces des feuilles (`booklet.py`) et n'utilise
jamais la fonction Livret de l'imprimante (sur la Canon de l'atelier, elle
réclame du papier « A4R » absent des bacs). Le travail envoyé est celui d'un
document Word recto verso ordinaire : format A4 (ou A3) ordinaire en portrait,
recto verso bord long, une page par feuille, livret et agrafage de
l'imprimante désactivés — la Canon n'appliquait pas le recto verso d'un
travail en paysage bord court. Seuls les réglages qui diffèrent sont changés,
par le schéma d'impression de Windows, puis relus dans le pilote avant
l'envoi : un réglage refusé arrête l'impression avec un message, plutôt qu'un
livret faux. Chaque face est posée à taille réelle sur la feuille, tournée
d'un quart de tour, le pli au milieu exact du papier ; les versos font un
demi-tour de plus (voir `backs_half_turn`).

Les copies passent par les réglages du pilote (assemblées) : un livret en deux
exemplaires donne deux livrets, et non un seul livret deux fois plus épais.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import re
import struct
import threading
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Callable

MAX_PRINT_DPI = 300
MAX_COPIES = 99

# GetDeviceCaps
HORZRES, VERTRES = 8, 10
LOGPIXELSX, LOGPIXELSY = 88, 90
PHYSICALWIDTH, PHYSICALHEIGHT = 110, 111
PHYSICALOFFSETX, PHYSICALOFFSETY = 112, 113

# DocumentProperties
DM_OUT_BUFFER, DM_IN_PROMPT, DM_IN_BUFFER = 2, 4, 8
IDOK = 1
# DEVMODEW : dmFields, dmCopies et dmCollate (décalages de la structure publique)
DEVMODE_FIELDS, DEVMODE_COPIES, DEVMODE_COLLATE = 72, 86, 100
DM_COPIES, DM_COLLATE = 0x100, 0x8000

PRINTER_ENUM_LOCAL, PRINTER_ENUM_CONNECTIONS = 0x2, 0x4

# Schéma d'impression de Windows
PSF = "http://schemas.microsoft.com/windows/2003/08/printing/printschemaframework"
PSK = "http://schemas.microsoft.com/windows/2003/08/printing/printschemakeywords"
MEDIA = "psk:PageMediaSize"
ORIENTATION = "psk:PageOrientation"
DUPLEX_FEATURES = ("psk:JobDuplexAllDocumentsContiguously", "psk:DocumentDuplex")
DUPLEX_LONG, DUPLEX_SHORT = "psk:TwoSidedLongEdge", "psk:TwoSidedShortEdge"
BIND_FEATURES = ("psk:JobBindAllDocuments", "psk:DocumentBinding")
STAPLE_FEATURES = ("psk:JobStapleAllDocuments", "psk:DocumentStaple")
NUP_FEATURES = ("psk:JobNUpAllDocumentsContiguously", "psk:DocumentNUp")
# Formats des feuilles de livret, définis en portrait comme dans le schéma (microns).
SHEET_MEDIA = {"a4": (210000, 297000), "a3": (297000, 420000)}
SHEET_LABELS = {"a4": "A4", "a3": "A3"}
FEATURE_LABELS = {
    MEDIA: "format du papier",
    ORIENTATION: "orientation portrait",
    "psk:JobDuplexAllDocumentsContiguously": "recto verso",
    "psk:DocumentDuplex": "recto verso",
    "psk:JobBindAllDocuments": "livret de l'imprimante désactivé",
    "psk:DocumentBinding": "reliure de l'imprimante désactivée",
    "psk:JobStapleAllDocuments": "agrafage désactivé",
    "psk:DocumentStaple": "agrafage désactivé",
    "psk:JobNUpAllDocumentsContiguously": "une page par feuille",
    "psk:DocumentNUp": "une page par feuille",
}
NET_ASSEMBLIES = (
    "System.Printing, Version=4.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35",
    "ReachFramework, Version=4.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35",
)


class PrintError(Exception):
    pass


class DOCINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_int),
        ("lpszDocName", wt.LPCWSTR),
        ("lpszOutput", wt.LPCWSTR),
        ("lpszDatatype", wt.LPCWSTR),
        ("fwType", wt.DWORD),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD),
        ("biWidth", wt.LONG),
        ("biHeight", wt.LONG),
        ("biPlanes", wt.WORD),
        ("biBitCount", wt.WORD),
        ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD),
        ("biXPelsPerMeter", wt.LONG),
        ("biYPelsPerMeter", wt.LONG),
        ("biClrUsed", wt.DWORD),
        ("biClrImportant", wt.DWORD),
    ]


class PRINTER_INFO_4W(ctypes.Structure):
    _fields_ = [("pPrinterName", wt.LPWSTR), ("pServerName", wt.LPWSTR), ("Attributes", wt.DWORD)]


# --- Placement sur la feuille ---


@dataclass
class Placement:
    """Image posée sur la feuille, en pixels de l'imprimante, à partir de l'origine
    de la zone imprimable (négatif : dans la marge non imprimable, rogné)."""

    rotate: int
    scale: float  # points PDF → pixels de l'imprimante
    x: int
    y: int
    width: int
    height: int


@dataclass
class Device:
    """Mesures de la feuille données par le pilote, en pixels de l'imprimante."""

    dpi_x: int
    dpi_y: int
    area_w: int
    area_h: int
    phys_w: int
    phys_h: int
    off_x: int
    off_y: int

    def margin_pt(self) -> float:
        """Plus grande marge non imprimable de la feuille, en points."""
        right = self.phys_w - self.area_w - self.off_x
        bottom = self.phys_h - self.area_h - self.off_y
        return max(max(self.off_x, right, 0) * 72 / self.dpi_x, max(self.off_y, bottom, 0) * 72 / self.dpi_y)


def place(page_w: float, page_h: float, area_w: int, area_h: int, dpi_x: float, dpi_y: float) -> Placement:
    """Ajuste la page (en points) à la zone imprimable : quart de tour vers la gauche
    si les orientations diffèrent (comme Acrobat : le haut d'une page paysage
    passe à gauche, une page pivotée d'un quart de tour à droite revient droite),
    réduction ou agrandissement sans déformation, centrage."""
    rotate = 270 if (page_w > page_h) != (area_w > area_h) and page_w != page_h else 0
    if rotate:
        page_w, page_h = page_h, page_w
    # Résolutions horizontale et verticale peuvent différer (600×1200 ppp).
    natural_w, natural_h = page_w / 72 * dpi_x, page_h / 72 * dpi_y
    factor = min(area_w / natural_w, area_h / natural_h)
    width, height = max(1, round(natural_w * factor)), max(1, round(natural_h * factor))
    return Placement(rotate, factor * dpi_x / 72, (area_w - width) // 2, (area_h - height) // 2, width, height)


def place_sheet(sheet_w: float, sheet_h: float, device: Device, upside_down: bool = False) -> Placement:
    """Face de livret posée sur tout le papier (et non sur la zone imprimable) :
    taille réelle quand le papier est celui demandé, pli au milieu exact du
    papier. Quart de tour si le pilote garde le papier dans l'autre sens : les
    deux faces tournent ensemble, le retournement bord court reste juste.
    `upside_down` : face tournée d'un demi-tour (versos inversés)."""
    rotate = 270 if (sheet_w > sheet_h) != (device.phys_w > device.phys_h) else 0
    if rotate:
        sheet_w, sheet_h = sheet_h, sheet_w
    natural_w, natural_h = sheet_w / 72 * device.dpi_x, sheet_h / 72 * device.dpi_y
    factor = min(device.phys_w / natural_w, device.phys_h / natural_h)
    width, height = max(1, round(natural_w * factor)), max(1, round(natural_h * factor))
    x = (device.phys_w - width) // 2 - device.off_x
    y = (device.phys_h - height) // 2 - device.off_y
    if upside_down:
        rotate = (rotate + 180) % 360
    return Placement(rotate, factor * device.dpi_x / 72, x, y, width, height)


def parse_pages(spec: str, count: int) -> list[int]:
    """« 1-3, 5 » → index [0, 1, 2, 4]. Erreur explicite pour une saisie invalide."""
    pages: list[int] = []
    text = (spec or "").replace(" ", "")
    if not text:
        raise PrintError("Indiquez les pages à imprimer, par exemple 1-3, 5.")
    for part in text.split(","):
        match = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not match:
            raise PrintError(f"Pages incomprises : « {part} ». Exemple : 1-3, 5.")
        start = int(match.group(1))
        end = int(match.group(2) or start)
        if start > end:
            start, end = end, start
        if start < 1 or end > count:
            raise PrintError(f"Le document a {count} page{'s' if count > 1 else ''} : « {part} » n'existe pas.")
        pages.extend(range(start - 1, end))
    return pages


def set_copies(devmode: bytes, copies: int) -> bytes:
    """Nombre d'exemplaires assemblés, inscrit dans les réglages du pilote."""
    data = bytearray(devmode)
    fields = struct.unpack_from("<I", data, DEVMODE_FIELDS)[0] | DM_COPIES | DM_COLLATE
    struct.pack_into("<I", data, DEVMODE_FIELDS, fields)
    struct.pack_into("<h", data, DEVMODE_COPIES, copies)
    struct.pack_into("<h", data, DEVMODE_COLLATE, 1)
    return bytes(data)


# --- Windows : imprimantes, pilote, contexte d'impression ---


def _api():
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    winspool = ctypes.WinDLL("winspool.drv", use_last_error=True)
    ole32 = ctypes.WinDLL("ole32")
    gdi32.GetDeviceCaps.argtypes = [wt.HDC, ctypes.c_int]
    gdi32.CreateDCW.argtypes = [wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR, ctypes.c_void_p]
    gdi32.CreateDCW.restype = wt.HDC
    gdi32.StartDocW.argtypes = [wt.HDC, ctypes.POINTER(DOCINFOW)]
    for name in ("StartPage", "EndPage", "EndDoc", "AbortDoc", "DeleteDC"):
        getattr(gdi32, name).argtypes = [wt.HDC]
    gdi32.SetStretchBltMode.argtypes = [wt.HDC, ctypes.c_int]
    gdi32.StretchDIBits.argtypes = [
        wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_void_p, ctypes.POINTER(BITMAPINFOHEADER), wt.UINT, wt.DWORD,
    ]
    winspool.OpenPrinterW.argtypes = [wt.LPCWSTR, ctypes.POINTER(wt.HANDLE), ctypes.c_void_p]
    winspool.ClosePrinter.argtypes = [wt.HANDLE]
    winspool.DocumentPropertiesW.argtypes = [wt.HWND, wt.HANDLE, wt.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p, wt.DWORD]
    winspool.DocumentPropertiesW.restype = ctypes.c_long
    winspool.GetDefaultPrinterW.argtypes = [wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
    winspool.EnumPrintersW.argtypes = [wt.DWORD, wt.LPWSTR, wt.DWORD, ctypes.c_void_p, wt.DWORD,
                                       ctypes.POINTER(wt.DWORD), ctypes.POINTER(wt.DWORD)]
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wt.DWORD]
    return gdi32, winspool, ole32


def _sta() -> None:
    """Fil d'exécution en appartement unique : exigé par certains pilotes."""
    _, _, ole32 = _api()
    ole32.CoInitializeEx(None, 0x2)


def list_printers() -> tuple[list[str], str]:
    """Imprimantes du poste (locales et partagées) et imprimante par défaut."""
    _, winspool, _ = _api()
    flags = PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS
    needed, returned = wt.DWORD(), wt.DWORD()
    winspool.EnumPrintersW(flags, None, 4, None, 0, ctypes.byref(needed), ctypes.byref(returned))
    names: list[str] = []
    if needed.value:
        buffer = ctypes.create_string_buffer(needed.value)
        if winspool.EnumPrintersW(flags, None, 4, buffer, needed, ctypes.byref(needed), ctypes.byref(returned)):
            infos = ctypes.cast(buffer, ctypes.POINTER(PRINTER_INFO_4W))
            names = [infos[i].pPrinterName for i in range(returned.value) if infos[i].pPrinterName]
    size = wt.DWORD(0)
    winspool.GetDefaultPrinterW(None, ctypes.byref(size))
    default = ""
    if size.value:
        name = ctypes.create_unicode_buffer(size.value)
        if winspool.GetDefaultPrinterW(name, ctypes.byref(size)):
            default = name.value
    return sorted(set(names), key=str.casefold), default


class _Printer:
    def __init__(self, name: str):
        _, self._winspool, _ = _api()
        self.name = name
        self.handle = wt.HANDLE()
        if not self._winspool.OpenPrinterW(name, ctypes.byref(self.handle), None):
            raise PrintError(f"Imprimante « {name} » introuvable ou inaccessible.")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._winspool.ClosePrinter(self.handle)

    def devmode(self, owner: int = 0, current: bytes | None = None, prompt: bool = False) -> bytes | None:
        """Réglages du pilote ; avec `prompt`, fenêtre de préférences du pilote
        (None si l'utilisateur annule)."""
        size = self._winspool.DocumentPropertiesW(owner, self.handle, self.name, None, None, 0)
        if size <= 0:
            raise PrintError(f"Le pilote de « {self.name} » ne donne pas ses réglages.")
        out = ctypes.create_string_buffer(max(size, len(current or b"")))
        source = ctypes.create_string_buffer(current, len(current)) if current else None
        mode = DM_OUT_BUFFER | (DM_IN_BUFFER if source is not None else 0) | (DM_IN_PROMPT if prompt else 0)
        result = self._winspool.DocumentPropertiesW(owner, self.handle, self.name, out, source, mode)
        if result < 0:
            raise PrintError(f"Le pilote de « {self.name} » refuse ses réglages.")
        if prompt and result != IDOK:
            return None
        return out.raw[:size]


def create_dc(name: str, devmode: bytes) -> int:
    gdi32, _, _ = _api()
    buffer = ctypes.create_string_buffer(devmode, len(devmode))
    hdc = gdi32.CreateDCW("WINSPOOL", name, None, buffer)
    if not hdc:
        raise PrintError(f"L'imprimante « {name} » n'a pas pu être préparée.")
    return hdc


def device_of(hdc: int) -> Device:
    gdi32, _, _ = _api()
    caps = [gdi32.GetDeviceCaps(hdc, index) for index in (
        LOGPIXELSX, LOGPIXELSY, HORZRES, VERTRES, PHYSICALWIDTH, PHYSICALHEIGHT, PHYSICALOFFSETX, PHYSICALOFFSETY)]
    device = Device(*caps)
    if min(device.dpi_x, device.dpi_y, device.area_w, device.area_h) <= 0:
        raise PrintError("L'imprimante ne donne pas la taille de sa feuille.")
    if device.phys_w <= 0 or device.phys_h <= 0:  # pilote sans mesures physiques
        device.phys_w, device.phys_h, device.off_x, device.off_y = device.area_w, device.area_h, 0, 0
    return device


# --- Schéma d'impression de Windows (.NET System.Printing, chargé par pywebview) ---

_NET_LOCK = threading.Lock()
_NET = None


def _net():
    """Chargé une seule fois : deux requêtes simultanées verraient sinon le module
    `clr` à moitié initialisé."""
    global _NET
    with _NET_LOCK:
        if _NET is None:
            import clr

            for assembly in NET_ASSEMBLIES:
                clr.AddReference(assembly)
            import System
            import System.IO
            import System.Printing
            import System.Printing.Interop
            import System.Text

            _NET = (System, System.IO, System.Printing, System.Printing.Interop, System.Text)
        return _NET


def _xml(stream) -> str:
    return bytes(stream.ToArray()).decode("utf-8-sig")


def capabilities_xml(name: str) -> str:
    _, _, printing, _, _ = _net()
    try:
        return _xml(printing.LocalPrintServer().GetPrintQueue(name).GetPrintCapabilitiesAsXml())
    except Exception as exc:  # noqa: BLE001 - exception .NET : imprimante injoignable, pilote absent
        raise PrintError(f"Capacités de « {name} » illisibles (imprimante injoignable ?).") from exc


def feature_options(capabilities: str, feature: str) -> list[str]:
    """Options déclarées par le pilote pour une fonction du schéma d'impression."""
    root = ET.fromstring(capabilities)
    for node in root.iter(f"{{{PSF}}}Feature"):
        if node.get("name") == feature:
            return [option.get("name") or "" for option in node.findall(f"{{{PSF}}}Option")]
    return []


def _features(capabilities: str) -> set[str]:
    return {node.get("name") for node in ET.fromstring(capabilities).iter(f"{{{PSF}}}Feature")}


def _rotated_media(name: str) -> bool:
    """Papier « tourné » (A4R, ISOA4Rotated…), chargé dans l'autre sens dans les bacs."""
    local = name.rsplit(":", 1)[-1].lower()
    return "rotated" in local or re.fullmatch(r".*a\dr", local) is not None


def media_option(capabilities: str, sheet: str) -> str | None:
    """Option du pilote pour le format de feuille ordinaire (A4, A3), décrit en
    portrait : jamais une variante « tournée » (A4R) que les bacs n'ont pas."""
    want_w, want_h = SHEET_MEDIA[sheet]
    root = ET.fromstring(capabilities)
    for node in root.iter(f"{{{PSF}}}Feature"):
        if node.get("name") != MEDIA:
            continue
        candidates = []
        for option in node.findall(f"{{{PSF}}}Option"):
            size = {}
            for prop in option.findall(f"{{{PSF}}}ScoredProperty"):
                value = prop.find(f"{{{PSF}}}Value")
                if value is not None and prop.get("name") in ("psk:MediaSizeWidth", "psk:MediaSizeHeight"):
                    size[prop.get("name")] = int(float(value.text or 0))
            w, h = size.get("psk:MediaSizeWidth"), size.get("psk:MediaSizeHeight")
            name = option.get("name") or ""
            if w and h and abs(w - want_w) <= 1500 and abs(h - want_h) <= 1500 and not _rotated_media(name):
                candidates.append(name)
        standard = f"psk:ISO{sheet.upper()}"
        return standard if standard in candidates else (candidates[0] if candidates else None)
    return None


def duplex_choice(caps: str) -> tuple[str, str] | None:
    """Recto verso demandé pour un livret : (fonction, option). Bord long d'abord :
    c'est le recto verso par défaut des imprimantes et celui des documents Word ;
    la Canon de l'atelier l'applique, mais pas le bord court (essai du 19 octobre)."""
    for wanted in (DUPLEX_LONG, DUPLEX_SHORT):
        for feature in DUPLEX_FEATURES:
            if wanted in feature_options(caps, feature):
                return feature, wanted
    return None


def capabilities(name: str) -> dict:
    """Ce que le livret demande au pilote : formats ordinaires et recto verso."""
    caps = capabilities_xml(name)
    return {"duplex": duplex_choice(caps) is not None, "sheets": [sheet for sheet in SHEET_MEDIA if media_option(caps, sheet)]}


def ticket_summary(name: str, devmode: bytes) -> dict:
    """Réglages relus dans le pilote, comme il les transmettra à l'imprimante :
    {fonction : option} ; pour « pages par feuille », le nombre."""
    system, _, printing, interop, _ = _net()
    converter = interop.PrintTicketConverter(name, interop.PrintTicketConverter.MaxPrintSchemaVersion)
    ticket = converter.ConvertDevModeToPrintTicket(system.Array[system.Byte](devmode), printing.PrintTicketScope.JobScope)
    root = ET.fromstring(_xml(ticket.GetXmlStream()))
    summary: dict = {}
    for node in root.iter(f"{{{PSF}}}Feature"):
        option = node.find(f"{{{PSF}}}Option")
        if option is None:
            continue
        count = option.find(f"{{{PSF}}}ScoredProperty[@name='psk:PagesPerSheet']/{{{PSF}}}Value")
        summary[node.get("name")] = int(count.text) if count is not None else option.get("name")
    return summary


def _delta_ticket(settings: dict) -> str:
    features = []
    for feature, value in settings.items():
        if isinstance(value, int):
            option = (
                '<psf:Option><psf:ScoredProperty name="psk:PagesPerSheet">'
                f'<psf:Value xsi:type="xsd:integer">{value}</psf:Value></psf:ScoredProperty></psf:Option>'
            )
        else:
            option = f'<psf:Option name="{value}"/>'
        features.append(f'<psf:Feature name="{feature}">{option}</psf:Feature>')
    return (
        f'<?xml version="1.0" encoding="UTF-8"?><psf:PrintTicket xmlns:psf="{PSF}" xmlns:psk="{PSK}" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
        f'version="1">{"".join(features)}</psf:PrintTicket>'
    )


def apply_ticket(name: str, devmode: bytes, settings: dict) -> bytes:
    """Réglages du pilote modifiés par le schéma d'impression, validés par le pilote."""
    system, io, printing, interop, text = _net()
    try:
        queue = printing.LocalPrintServer().GetPrintQueue(name)
        converter = interop.PrintTicketConverter(name, interop.PrintTicketConverter.MaxPrintSchemaVersion)
        base = converter.ConvertDevModeToPrintTicket(system.Array[system.Byte](devmode), printing.PrintTicketScope.JobScope)
        delta = printing.PrintTicket(io.MemoryStream(text.Encoding.UTF8.GetBytes(_delta_ticket(settings))))
        merged = queue.MergeAndValidatePrintTicket(base, delta).ValidatedPrintTicket
        return bytes(converter.ConvertPrintTicketToDevMode(merged, interop.BaseDevModeType.UserDefault))
    except Exception as exc:  # noqa: BLE001 - exception .NET
        raise PrintError(f"Le pilote de « {name} » refuse les réglages du livret.") from exc


def booklet_settings(caps: str, sheet: str) -> dict:
    """Réglages d'un livret, limités à ce que le pilote déclare : ceux d'un document
    Word recto verso ordinaire — format ordinaire en portrait, recto verso bord
    long —, livret et agrafage de l'imprimante désactivés, une page par feuille.
    Les faces du livret sont tournées sur la feuille par DestriPDF."""
    media = media_option(caps, sheet)
    if media is None:
        raise PrintError(f"L'imprimante ne propose pas le format {SHEET_LABELS[sheet]}.")
    settings: dict = {MEDIA: media}
    if "psk:Portrait" in feature_options(caps, ORIENTATION):
        settings[ORIENTATION] = "psk:Portrait"
    duplex = duplex_choice(caps)
    if duplex:
        settings[duplex[0]] = duplex[1]
    for group in (BIND_FEATURES, STAPLE_FEATURES):
        for feature in group:
            if "psk:None" in feature_options(caps, feature):
                settings[feature] = "psk:None"
    present = _features(caps)
    for feature in NUP_FEATURES:
        if feature in present:
            settings[feature] = 1
    return settings


class PrinterSettings:
    """Réglages du pilote choisis pour chaque imprimante (préférences), gardés
    jusqu'à la fermeture de DestriPDF, comme dans Acrobat."""

    def __init__(self):
        self._devmodes: dict[str, bytes] = {}
        self._lock = threading.Lock()

    def preferences(self, owner: int, name: str) -> bool:
        """Fenêtre de préférences du pilote ; True si l'utilisateur a validé."""
        _sta()
        with _Printer(name) as printer:
            current = self._devmodes.get(name) or printer.devmode()
            chosen = printer.devmode(owner, current, prompt=True)
        if chosen is None:
            return False
        with self._lock:
            self._devmodes[name] = chosen
        return True

    def job_devmode(self, name: str, copies: int = 1) -> bytes:
        """Réglages pour des pages normales : préférences choisies, copies assemblées."""
        _sta()
        with _Printer(name) as printer:
            devmode = self._devmodes.get(name) or printer.devmode()
            return printer.devmode(0, set_copies(devmode, copies))  # validé par le pilote

    def booklet_devmode(self, name: str, copies: int, sheet: str) -> tuple[bytes, dict]:
        """Réglages pour les faces d'un livret, relus dans le pilote : une valeur
        refusée arrête l'impression (message) au lieu de donner un livret faux.
        Seuls les réglages qui diffèrent sont changés : avec les réglages par défaut
        de la Canon (A4 portrait, recto verso bord long), le travail est celui d'un
        document Word ordinaire. Renvoie aussi les réglages imposés."""
        _sta()
        caps = capabilities_xml(name)
        settings = booklet_settings(caps, sheet)
        with _Printer(name) as printer:
            devmode = self._devmodes.get(name) or printer.devmode()
            current = ticket_summary(name, devmode)
            delta = {feature: value for feature, value in settings.items() if current.get(feature) != value}
            if delta:
                devmode = apply_ticket(name, devmode, delta)
            devmode = printer.devmode(0, set_copies(devmode, copies))  # validé par le pilote
        obtained = ticket_summary(name, devmode)
        refused = [FEATURE_LABELS.get(feature, feature) for feature, value in settings.items() if obtained.get(feature) != value]
        if refused:
            raise PrintError(f"Le pilote de « {name} » n'accepte pas : {', '.join(refused)}. Livret non imprimé.")
        return devmode, settings


# --- Envoi au pilote ---


def _send(hdc: int, title: str, count: int, placement: Callable[[int], Placement],
          render: Callable[[int, float, int], tuple[bytes, int, int]], device: Device,
          progress: Callable[[int, int], None] | None = None, output: str | None = None) -> None:
    """Envoie `count` images au pilote puis libère le contexte. `render(i, échelle,
    rotation)` rend l'image i en BGRA (lignes de haut en bas). `output` : fichier de
    sortie du pilote (recette, tests)."""
    gdi32, _, _ = _api()
    try:
        info = DOCINFOW(ctypes.sizeof(DOCINFOW), title, output, None, 0)
        if gdi32.StartDocW(hdc, ctypes.byref(info)) <= 0:
            raise PrintError("L'impression n'a pas pu démarrer (imprimante indisponible ou impression annulée).")
        try:
            # Rendu à la résolution de l'imprimante, plafonnée : le pilote agrandit.
            reduce = min(1.0, MAX_PRINT_DPI / max(device.dpi_x, device.dpi_y))
            for index in range(count):
                spot = placement(index)
                data, px_w, px_h = render(index, spot.scale * reduce, spot.rotate)
                if gdi32.StartPage(hdc) <= 0:
                    raise PrintError("Page refusée par l'imprimante.")
                header = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), px_w, -px_h, 1, 32, 0, 0, 0, 0, 0, 0)
                buffer = ctypes.create_string_buffer(data, len(data))
                gdi32.SetStretchBltMode(hdc, 4)  # HALFTONE
                copied = gdi32.StretchDIBits(
                    hdc, spot.x, spot.y, spot.width, spot.height, 0, 0, px_w, px_h,
                    buffer, ctypes.byref(header), 0, 0x00CC0020,  # DIB_RGB_COLORS, SRCCOPY
                )
                if copied == 0 or gdi32.EndPage(hdc) <= 0:
                    raise PrintError("Page refusée par le pilote de l'imprimante.")
                if progress:
                    progress(index + 1, count)
        except BaseException:
            gdi32.AbortDoc(hdc)
            raise
        gdi32.EndDoc(hdc)
    finally:
        gdi32.DeleteDC(hdc)


def print_pages(hdc: int, title: str, pages: list[int], page_size: Callable[[int], tuple[float, float]],
                render: Callable[[int, float, int], tuple[bytes, int, int]],
                progress: Callable[[int, int], None] | None = None, output: str | None = None) -> None:
    """Pages normales : chacune ajustée à la zone imprimable (voir `place`)."""
    try:
        device = device_of(hdc)
    except BaseException:
        _api()[0].DeleteDC(hdc)
        raise

    def placement(i: int) -> Placement:
        return place(*page_size(pages[i]), device.area_w, device.area_h, device.dpi_x, device.dpi_y)

    _send(hdc, title, len(pages), placement, lambda i, scale, rotate: render(pages[i], scale, rotate),
          device, progress, output)


def backs_half_turn(settings: dict, flip_backs: bool = False) -> bool:
    """Versos tournés d'un demi-tour par rapport aux rectos ?

    Le lecteur d'un livret tourne les pages autour du pli. Retournement bord court :
    le papier tourne autour du même axe, les versos gardent le sens des rectos.
    Retournement bord long : il tourne autour de l'axe perpendiculaire, les versos
    doivent faire un demi-tour (vérifié par la feuille simulée des tests, en
    portrait comme en paysage). « Retourner les versos » inverse ce choix, pour une
    imprimante qui retournerait autrement."""
    long_edge = any(settings.get(feature) == DUPLEX_LONG for feature in DUPLEX_FEATURES)
    return long_edge != flip_backs


def print_booklet_faces(hdc: int, title: str, impose: Callable[[float], object], sheet_size: tuple[float, float],
                        render_face: Callable[[object, int, float, int], tuple[bytes, int, int]],
                        upside_down_backs: bool = False, progress: Callable[[int, int], None] | None = None,
                        output: str | None = None) -> int:
    """Faces de livret : la marge de mise en page suit la marge non imprimable du
    pilote (`impose(marge)` rend le document des faces), chaque face est posée
    sur tout le papier (tournée d'un quart de tour sur une feuille portrait) ;
    versos tournés d'un demi-tour de plus si `upside_down_backs`. Renvoie le
    nombre de faces envoyées."""
    try:
        device = device_of(hdc)
        faces = impose(device.margin_pt() + 1)
        count = faces.page_count
    except BaseException:
        _api()[0].DeleteDC(hdc)
        raise
    width, height = sheet_size

    def placement(i: int) -> Placement:
        return place_sheet(width, height, device, upside_down=upside_down_backs and i % 2 == 1)

    _send(hdc, title, count, placement, lambda i, scale, rotate: render_face(faces, i, scale, rotate),
          device, progress, output)
    return count


class WindowsPrinting:
    """Ce dont le serveur a besoin : imprimantes, préférences du pilote, impression."""

    def __init__(self):
        self.settings = PrinterSettings()

    def printers(self) -> tuple[list[str], str]:
        return list_printers()

    def capabilities(self, name: str) -> dict:
        _sta()
        return capabilities(name)

    def preferences(self, owner: int, name: str) -> bool:
        return self.settings.preferences(owner, name)

    def print_document(self, name: str, copies: int, title: str, pages: list[int],
                       page_size, render, output: str | None = None) -> None:
        hdc = create_dc(name, self.settings.job_devmode(name, copies))
        print_pages(hdc, title, pages, page_size, render, output=output)

    def print_booklet(self, name: str, copies: int, title: str, sheet: str, impose, render_face,
                      upside_down_backs: bool = False, output: str | None = None) -> int:
        """`upside_down_backs` : choix « Retourner les versos » de l'utilisateur."""
        from .booklet import SHEETS

        devmode, settings = self.settings.booklet_devmode(name, copies, sheet)
        return print_booklet_faces(create_dc(name, devmode), title, impose, SHEETS[sheet], render_face,
                                   backs_half_turn(settings, upside_down_backs), output=output)
