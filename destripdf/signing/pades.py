"""Signature PAdES (pyHanko) avec la clé du magasin Windows, et vérification.

Ce module est importé à la demande : pyHanko et ses dépendances ne pèsent pas
sur le démarrage de l'application.
"""

from __future__ import annotations

import hashlib
import io
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import pymupdf as fitz
from asn1crypto import x509 as asn1_x509
from pyhanko.pdf_utils import layout
from pyhanko.pdf_utils.content import ImportedPdfPage
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign import fields, signers
from pyhanko.sign.validation import validate_pdf_signature
from pyhanko.sign.validation.status import SignatureCoverageLevel
from pyhanko.stamp import StaticStampStyle
from pyhanko_certvalidator import ValidationContext
from pyhanko_certvalidator.registry import SimpleCertificateStore

from ..document import FITZ_LOCK
from . import wincert

FONT_DIR = Path(__file__).resolve().parent.parent / "static" / "fonts"
INK = (0x29 / 255, 0x32 / 255, 0x3A / 255)
INK_MUTED = (0x5F / 255, 0x69 / 255, 0x72 / 255)


class SigningError(Exception):
    """Échec de signature présenté tel quel à l'utilisateur."""

    def __init__(self, message: str, code: str = "error"):
        super().__init__(message)
        self.code = code


@dataclass
class Appearance:
    """Signature visible : page et cadre en coordonnées MuPDF non pivotées."""

    page_index: int
    rect: tuple[float, float, float, float]
    image_png: bytes | None = None


@dataclass
class SignOptions:
    thumbprint: str
    reason: str = ""
    location: str = ""
    contact: str = ""
    appearance: Appearance | None = None
    timestamp_url: str = ""
    hwnd: int | None = None
    password: str | None = None  # PDF protégé : mot de passe saisi à l'ouverture


StoreFactory = Callable[[], wincert.CertStore]


class WindowsKeySigner(signers.Signer):
    """Signataire pyHanko qui confie la signature brute au fournisseur de la clé."""

    def __init__(self, store_factory: StoreFactory, entry: wincert.CertificateEntry, chain_ders: list[bytes], hwnd: int | None):
        cert = asn1_x509.Certificate.load(entry.der)
        others = [asn1_x509.Certificate.load(der) for der in chain_ders if der != entry.der]
        super().__init__(
            signing_cert=cert,
            cert_registry=SimpleCertificateStore.from_certs(others),
            embed_roots=True,
        )
        self._store_factory = store_factory
        self._thumbprint = entry.thumbprint
        self._hwnd = hwnd
        self._key_bytes = max(1, (entry.key_size + 7) // 8)
        self._rsa = entry.key_algorithm == "rsa"
        self.signatures_made = 0

    async def async_sign_raw(self, data: bytes, digest_algorithm: str, dry_run: bool = False) -> bytes:
        if dry_run:
            # Réservation de place : aucune sollicitation de la clé.
            return bytes(self._key_bytes if self._rsa else 2 * self._key_bytes + 9)
        digest = hashlib.new(digest_algorithm, data).digest()
        with self._store_factory() as store:
            signature = store.sign_digest(self._thumbprint, digest, digest_algorithm, hwnd=self._hwnd)
        self.signatures_made += 1
        return signature


def _find_cause(exc: BaseException, kind):
    seen = set()
    while exc is not None and id(exc) not in seen:
        if isinstance(exc, kind):
            return exc
        seen.add(id(exc))
        exc = exc.__cause__ or exc.__context__
    return None


def prepare_signer(options: SignOptions, store_factory: StoreFactory) -> tuple[WindowsKeySigner, wincert.CertificateEntry]:
    with store_factory() as store:
        entry = store.entry(options.thumbprint)
        if not entry.has_private_key:
            raise SigningError("Ce certificat n'a pas de clé privée sur ce poste : branchez la clé qui le porte.", "no_key")
        if entry.expired:
            raise SigningError(f"Ce certificat a expiré le {entry.not_after.astimezone():%d/%m/%Y}.", "expired")
        if entry.not_yet_valid:
            raise SigningError(f"Ce certificat n'est valable qu'à partir du {entry.not_before.astimezone():%d/%m/%Y}.", "not_yet_valid")
        chain = store.chain(options.thumbprint)
        if chain.error_status & wincert.CERT_TRUST_IS_PARTIAL_CHAIN:
            # Intermédiaire absent du poste : Windows peut le télécharger (AIA).
            try:
                chain = store.chain(options.thumbprint, allow_network=True)
            except wincert.WinCertError:
                pass
    return WindowsKeySigner(store_factory, entry, chain.ders or [entry.der], options.hwnd), entry


def _font(name: str, text: str) -> fitz.Font:
    """Police de la charte réduite au texte (table Unicode sans ambiguïté)."""
    from .. import fonts

    choice = fonts.FontChoice(str(FONT_DIR / name), 0, "Roboto", "Medium" in name, False, True)
    return fonts.subset_font(choice, text)


def format_signing_time(moment: datetime) -> str:
    offset = moment.utcoffset()
    minutes = int(offset.total_seconds() // 60) if offset is not None else 0
    sign = "+" if minutes >= 0 else "-"
    minutes = abs(minutes)
    return f"Le {moment:%d/%m/%Y à %H:%M} (UTC{sign}{minutes // 60:02d}:{minutes % 60:02d})"


def _fit_lines(lines: list[tuple[str, fitz.Font, float]], width: float, height: float) -> float:
    """Taille de base qui fait tenir toutes les lignes (facteur relatif par ligne)."""
    line_gap = 1.28
    total_units = sum(factor for _, _, factor in lines) * line_gap
    size = height / max(total_units, 1)
    for text, font, factor in lines:
        units = font.text_length(text, fontsize=1) * factor
        if units > 0:
            size = min(size, width / units)
    return max(3.5, min(size, 14))


def build_appearance_pdf(
    *,
    width: float,
    height: float,
    rotation: int,
    signer_name: str,
    signed_at: datetime,
    reason: str,
    location: str,
    image_png: bytes | None,
) -> bytes:
    """Dessine le cadre visible (orientation affichée) dans un PDF d'une page.

    `width`/`height` sont les dimensions du champ dans l'espace non pivoté de la
    page ; le dessin est tourné pour apparaître droit une fois la page pivotée.
    """
    disp_w, disp_h = (height, width) if rotation % 180 else (width, height)
    src = fitz.open()
    page = src.new_page(width=disp_w, height=disp_h)
    pad = max(2.0, min(disp_w, disp_h) * 0.06)
    text_x0 = pad
    if image_png:
        img_box = fitz.Rect(pad, pad, pad + (disp_w - 2 * pad) * 0.42, disp_h - pad)
        try:
            page.insert_image(img_box, stream=image_png, keep_proportion=True)
            text_x0 = img_box.x1 + pad
        except Exception:  # noqa: BLE001 - image illisible : signature texte seule
            text_x0 = pad
    texts: list[tuple[str, str, float, tuple]] = [
        ("Signé numériquement par", "Roboto-Regular.ttf", 0.82, INK_MUTED),
        (signer_name, "Roboto-Medium.ttf", 1.18, INK),
        (format_signing_time(signed_at), "Roboto-Regular.ttf", 0.82, INK_MUTED),
    ]
    if reason:
        texts.append((f"Motif : {reason}", "Roboto-Regular.ttf", 0.82, INK_MUTED))
    if location:
        texts.append((f"Lieu : {location}", "Roboto-Regular.ttf", 0.82, INK_MUTED))
    lines = [(text, _font(font_name, text), factor, color) for text, font_name, factor, color in texts]
    area_w = max(10.0, disp_w - text_x0 - pad)
    area_h = max(10.0, disp_h - 2 * pad)
    size = _fit_lines([(t, f, k) for t, f, k, _ in lines], area_w, area_h)
    block_h = sum(k for _, _, k, _ in lines) * size * 1.28
    y = pad + max(0.0, (area_h - block_h) / 2)
    for text, font, factor, color in lines:
        fs = size * factor
        y += fs * 1.28
        writer = fitz.TextWriter(page.rect, color=color)
        writer.append((text_x0, y - fs * 0.28), text, font=font, fontsize=fs)
        writer.write_text(page)
    if rotation % 360 == 0:
        return src.tobytes(garbage=3, deflate=True)
    out = fitz.open()
    target = out.new_page(width=width, height=height)
    # La page s'affiche tournée de `rotation` degrés (sens horaire) : le dessin est
    # pré-tourné d'autant dans le sens antihoraire (`rotate` positif de PyMuPDF).
    target.show_pdf_page(target.rect, src, 0, rotate=rotation)
    return out.tobytes(garbage=3, deflate=True)


def _unique_field_name(writer: IncrementalPdfFileWriter) -> str:
    existing = {name for name, _value, _ref in fields.enumerate_sig_fields(writer)}
    index = 1
    while f"Signature{index}" in existing:
        index += 1
    return f"Signature{index}"


def _open_fitz(pdf_bytes: bytes, password: str | None) -> fitz.Document:
    doc = fitz.open("pdf", pdf_bytes)
    if doc.needs_pass and not doc.authenticate(password or ""):
        doc.close()
        raise SigningError("Ce PDF est protégé par un mot de passe : rouvrez-le avec son mot de passe.", "password")
    return doc


def _widget_box(pdf_bytes: bytes, appearance: Appearance, password: str | None = None) -> tuple[tuple[float, float, float, float], int, float, float]:
    doc = _open_fitz(pdf_bytes, password)
    try:
        if not 0 <= appearance.page_index < doc.page_count:
            raise SigningError("Page de signature introuvable.", "bad_page")
        page = doc[appearance.page_index]
        rect = fitz.Rect(appearance.rect)
        if rect.is_empty or rect.width < 8 or rect.height < 8:
            raise SigningError("Le cadre de signature est trop petit.", "bad_rect")
        pdf_rect = rect * ~page.transformation_matrix
        pdf_rect.normalize()
        return (pdf_rect.x0, pdf_rect.y0, pdf_rect.x1, pdf_rect.y1), page.rotation, rect.width, rect.height
    finally:
        doc.close()


def sign_pdf(
    pdf_bytes: bytes,
    options: SignOptions,
    *,
    store_factory: StoreFactory = wincert.CertStore.system,
    signer_override: signers.Signer | None = None,
) -> tuple[bytes, dict]:
    """Ajoute une signature PAdES (mise à jour incrémentale) et renvoie le PDF signé."""
    if signer_override is not None:
        signer, signer_name = signer_override, signer_override.subject_name or "Signataire"
    else:
        try:
            signer, entry = prepare_signer(options, store_factory)
        except wincert.WinCertError as err:
            raise SigningError(str(err), err.code) from err
        signer_name = entry.subject_cn or entry.email or "Signataire"

    writer = IncrementalPdfFileWriter(io.BytesIO(pdf_bytes), strict=False)
    if writer.prev.encrypted:
        # Une mise à jour d'un PDF chiffré garde son chiffrement : il faut le mot de passe.
        from pyhanko.pdf_utils.crypt.api import AuthStatus

        try:
            auth = writer.encrypt(options.password or "")
        except Exception as exc:  # noqa: BLE001
            raise SigningError("Ce PDF est protégé par un mot de passe : rouvrez-le avec son mot de passe.", "password") from exc
        if getattr(auth, "status", AuthStatus.FAILED) == AuthStatus.FAILED:
            raise SigningError("Ce PDF est protégé par un mot de passe : rouvrez-le avec son mot de passe.", "password")
        # MuPDF écrit /Encrypt en dictionnaire direct ; pyHanko le veut indirect (il le
        # repère par son numéro pour ne pas le chiffrer). Copie indirecte, même contenu,
        # dans la mise à jour de signature elle-même.
        from pyhanko.pdf_utils import generic

        if isinstance(writer._encrypt, generic.DictionaryObject):
            writer._encrypt = writer.add_object(writer._encrypt)
    field_name = _unique_field_name(writer)
    signed_at = datetime.now().astimezone()
    meta = signers.PdfSignatureMetadata(
        field_name=field_name,
        md_algorithm="sha256",
        reason=options.reason or None,
        location=options.location or None,
        contact_info=options.contact or None,
        name=signer_name,
        subfilter=fields.SigSeedSubFilter.PADES,
    )
    timestamper = None
    if options.timestamp_url:
        from pyhanko.sign.timestamps import HTTPTimeStamper

        timestamper = HTTPTimeStamper(options.timestamp_url, timeout=15)

    tmp_path = None
    try:
        if options.appearance is not None:
            with FITZ_LOCK:  # MuPDF n'est pas sûr entre fils d'exécution
                box, rotation, width, height = _widget_box(pdf_bytes, options.appearance, options.password)
                appearance_pdf = build_appearance_pdf(
                    width=box[2] - box[0],
                    height=box[3] - box[1],
                    rotation=rotation,
                    signer_name=signer_name,
                    signed_at=signed_at,
                    reason=options.reason,
                    location=options.location,
                    image_png=options.appearance.image_png,
                )
            fd, tmp_path = tempfile.mkstemp(prefix="destripdf-apparence-", suffix=".pdf")
            with os.fdopen(fd, "wb") as handle:
                handle.write(appearance_pdf)
            style = StaticStampStyle(
                background=ImportedPdfPage(tmp_path),
                border_width=0,
                background_opacity=1.0,
                background_layout=layout.SimpleBoxLayoutRule(
                    x_align=layout.AxisAlignment.ALIGN_MID,
                    y_align=layout.AxisAlignment.ALIGN_MID,
                    margins=layout.Margins.uniform(0),
                ),
            )
            spec = fields.SigFieldSpec(sig_field_name=field_name, on_page=options.appearance.page_index, box=box)
        else:
            style = None
            spec = fields.SigFieldSpec(sig_field_name=field_name)
        pdf_signer = signers.PdfSigner(meta, signer=signer, timestamper=timestamper, stamp_style=style, new_field_spec=spec)
        output = pdf_signer.sign_pdf(writer, output=io.BytesIO())
        signed = output.getvalue()
    except SigningError:
        raise
    except Exception as exc:  # noqa: BLE001 - message clair, jamais de trace brute
        cause = _find_cause(exc, wincert.WinCertError)
        if cause is not None:
            raise SigningError(str(cause), cause.code) from exc
        raise SigningError(f"La signature a échoué : {exc}", "error") from exc
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    return signed, {"field_name": field_name, "signer": signer_name, "signed_at": signed_at.isoformat()}


# --- Vérification ------------------------------------------------------------


@dataclass
class SignatureReport:
    field_name: str
    signer: str = ""
    issuer: str = ""
    signed_at: str = ""
    reason: str = ""
    location: str = ""
    intact: bool = False
    valid: bool = False
    covers_whole_file: bool = False
    modification: str = ""
    trusted: bool = False
    trust_detail: str = ""
    qualified: bool = False
    status: str = "invalid"  # valid, warning, invalid
    summary: str = ""
    page_index: int | None = None
    rect: list[float] | None = None
    errors: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return dict(self.__dict__)


_MODIFICATIONS = {
    "NONE": "aucune modification depuis la signature",
    "LTA_UPDATES": "seules des données de validation ont été ajoutées",
    "FORM_FILLING": "des champs de formulaire ou d'autres signatures ont été ajoutés",
    "ANNOTATIONS": "des annotations ont été ajoutées après la signature",
    "OTHER": "le document a été modifié après la signature",
}


def validate_signatures(
    pdf_bytes: bytes,
    *,
    trust_check: Callable[[list[bytes]], wincert.ChainResult] | None = None,
    password: str | None = None,
) -> list[SignatureReport]:
    """Vérifie chaque signature : intégrité, couverture, modifications, confiance Windows."""
    trust_check = trust_check or wincert.chain_for_certificates
    reader = PdfFileReader(io.BytesIO(pdf_bytes), strict=False)
    if reader.encrypted:
        reader.decrypt(password or "")
    reports: list[SignatureReport] = []
    for embedded in reader.embedded_signatures:
        report = SignatureReport(field_name=embedded.field_name or "")
        sig_obj = embedded.sig_object
        report.reason = str(sig_obj.get("/Reason", "") or "")
        report.location = str(sig_obj.get("/Location", "") or "")
        try:
            cert = embedded.signer_cert
            entry = wincert.parse_certificate(cert.dump())
            report.signer = entry.subject_cn or entry.email
            report.issuer = entry.issuer_cn or entry.issuer_o
            report.qualified = entry.qualified
            others = [c.dump() for c in embedded.other_embedded_certs]
            chain = trust_check([cert.dump()] + others)
            report.trusted = chain.trusted
            report.trust_detail = chain.describe()
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"Certificat illisible : {exc}")
        try:
            status = validate_pdf_signature(embedded, ValidationContext(trust_roots=[], allow_fetching=False))
            report.intact = bool(status.intact)
            report.valid = bool(status.valid)
            report.covers_whole_file = status.coverage == SignatureCoverageLevel.ENTIRE_FILE
            level = status.modification_level
            report.modification = _MODIFICATIONS.get(level.name if level is not None else "OTHER", "")
            if status.signer_reported_dt is not None:
                report.signed_at = status.signer_reported_dt.astimezone().isoformat()
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"Vérification impossible : {exc}")
        _summarise(report)
        reports.append(report)
    with FITZ_LOCK:
        _locate_widgets(pdf_bytes, reports, password)
    return reports


def _summarise(report: SignatureReport) -> None:
    if not (report.intact and report.valid):
        report.status = "invalid"
        report.summary = "Signature invalide : le document a été altéré ou la signature est corrompue."
        return
    altered = report.modification and not report.modification.startswith("aucune")
    if report.trusted and not altered:
        report.status = "valid"
        report.summary = "Signature valide ; " + (report.modification or "document intact") + "."
    else:
        report.status = "warning"
        parts = []
        if not report.trusted:
            parts.append(report.trust_detail.rstrip(".") or "certificat non approuvé")
        if altered:
            parts.append(report.modification)
        report.summary = "Signature intègre, à vérifier : " + " ; ".join(p[0].lower() + p[1:] for p in parts if p) + "."


def _locate_widgets(pdf_bytes: bytes, reports: list[SignatureReport], password: str | None = None) -> None:
    by_name = {r.field_name: r for r in reports}
    if not by_name:
        return
    try:
        doc = _open_fitz(pdf_bytes, password)
    except SigningError:
        return
    try:
        for page in doc:
            for widget in page.widgets(types=[fitz.PDF_WIDGET_TYPE_SIGNATURE]):
                report = by_name.get(widget.field_name)
                if report is not None and report.page_index is None:
                    rect = widget.rect * page.rotation_matrix
                    rect.normalize()
                    report.page_index = page.number
                    report.rect = [round(v, 2) for v in rect]
    finally:
        doc.close()
