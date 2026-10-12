"""Signature PAdES (pyHanko) avec la clé du magasin Windows, et vérification.

Ce module est importé à la demande : pyHanko et ses dépendances ne pèsent pas
sur le démarrage de l'application.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
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
from pyhanko_certvalidator.errors import RevokedError
from pyhanko_certvalidator.registry import SimpleCertificateStore

from ..document import FITZ_LOCK
from . import wincert

log = logging.getLogger("destripdf")

FONT_DIR = Path(__file__).resolve().parent.parent / "static" / "fonts"
INK = (0x29 / 255, 0x32 / 255, 0x3A / 255)
SIGNED_BY = "Signature numérique de"  # libellé d'Acrobat en français
LINE_GAP = 1.22
REVOCATION_TIMEOUT = 8  # secondes par requête OCSP ou CRL auprès de l'autorité
LTV_UNAVAILABLE = (
    "État de révocation du certificat non intégré : l'autorité de certification n'a pas pu être "
    "interrogée (connexion Internet ?). La signature est valide, mais Acrobat ne la dira pas "
    "« compatible LTV »."
)


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
    # État de révocation (OCSP/CRL) demandé à l'autorité et intégré au document,
    # comme le fait Acrobat : signature « compatible LTV ».
    ltv: bool = True


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
    """Date de signature au format d'Acrobat : « 2026.10.12 13:14:05 +02'00' »."""
    offset = moment.utcoffset()
    minutes = int(offset.total_seconds() // 60) if offset is not None else 0
    sign = "+" if minutes >= 0 else "-"
    minutes = abs(minutes)
    return f"{moment:%Y.%m.%d %H:%M:%S} {sign}{minutes // 60:02d}'{minutes % 60:02d}'"


def _wrap(text: str, font: fitz.Font, size: float, width: float, *, force: bool = False) -> list[str] | None:
    """Coupe le texte aux espaces (jamais aux espaces insécables) pour tenir dans
    `width`. None si un mot est trop large, sauf `force` : coupure par caractères."""
    lines: list[str] = []
    current = ""
    for word in text.split(" "):
        if not word:
            continue
        candidate = f"{current} {word}" if current else word
        if font.text_length(candidate, fontsize=size) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        if font.text_length(word, fontsize=size) <= width:
            continue
        if not force:
            return None
        current = ""
        for char in word:
            if current and font.text_length(current + char, fontsize=size) > width:
                lines.append(current)
                current = char
            else:
                current += char
    if current:
        lines.append(current)
    return lines


def _fit_block(paragraphs: list[str], font: fitz.Font, box: fitz.Rect, max_size: float, min_size: float = 1.0) -> tuple[float, list[str]]:
    """Plus grande taille (au quart de point) où les paragraphes tiennent dans la
    boîte. Comme Acrobat, un petit cadre réduit le texte au lieu de le tronquer."""
    size = max(min_size, max_size)
    while size >= min_size:
        lines: list[str] = []
        for paragraph in paragraphs:
            wrapped = _wrap(paragraph, font, size, box.width)
            if wrapped is None:
                break
            lines.extend(wrapped)
        else:
            if len(lines) * size * LINE_GAP <= box.height:
                return size, lines
        size -= 0.25
    lines = [line for p in paragraphs for line in (_wrap(p, font, min_size, box.width, force=True) or [])]
    return min_size, lines


def _draw_block(page: fitz.Page, lines: list[str], font: fitz.Font, size: float, box: fitz.Rect) -> None:
    """Lignes alignées à gauche, bloc centré verticalement dans la boîte."""
    y = box.y0 + max(0.0, (box.height - len(lines) * size * LINE_GAP) / 2)
    writer = fitz.TextWriter(page.rect, color=INK)
    for line in lines:
        y += size * LINE_GAP
        writer.append((box.x0, y - size * 0.28), line, font=font, fontsize=size)
    writer.write_text(page)


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

    Présentation d'Acrobat : à gauche le nom du signataire en grand (ou l'image
    de la signature manuscrite), à droite « Signature numérique de … », le motif,
    le lieu et la date. `width`/`height` sont les dimensions du champ dans
    l'espace non pivoté de la page ; le dessin est tourné pour apparaître droit
    une fois la page pivotée.
    """
    disp_w, disp_h = (height, width) if rotation % 180 else (width, height)
    src = fitz.open()
    page = src.new_page(width=disp_w, height=disp_h)
    pad = max(2.0, min(disp_w, disp_h) * 0.06)
    column = max(4.0, (disp_w - 3 * pad) / 2)
    left = fitz.Rect(pad, pad, pad + column, disp_h - pad)
    right = fitz.Rect(left.x1 + pad, pad, disp_w - pad, disp_h - pad)

    name_size = None
    if image_png:
        try:
            page.insert_image(left, stream=image_png, keep_proportion=True)
        except Exception:  # noqa: BLE001 - image illisible : nom en toutes lettres
            image_png = None
    if not image_png:
        name_font = _font("Roboto-Regular.ttf", signer_name)
        name_size, name_lines = _fit_block([signer_name], name_font, left, max_size=36)
        _draw_block(page, name_lines, name_font, name_size, left)

    paragraphs = [f"{SIGNED_BY} {signer_name}"]
    if reason:
        paragraphs.append(f"Motif : {reason}")
    if location:
        paragraphs.append(f"Lieu : {location}")
    paragraphs.append(f"Date : {format_signing_time(signed_at)}")
    details_font = _font("Roboto-Regular.ttf", " ".join(paragraphs))
    # Comme Acrobat : le détail reste nettement plus petit que le nom.
    cap = 11.0 if name_size is None else max(1.0, min(11.0, name_size * 0.62))
    size, lines = _fit_block(paragraphs, details_font, right, max_size=cap)
    _draw_block(page, lines, details_font, size, right)
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


def _open_writer(pdf_bytes: bytes, password: str | None) -> IncrementalPdfFileWriter:
    writer = IncrementalPdfFileWriter(io.BytesIO(pdf_bytes), strict=False)
    if writer.prev.encrypted:
        # Une mise à jour d'un PDF chiffré garde son chiffrement : il faut le mot de passe.
        from pyhanko.pdf_utils.crypt.api import AuthStatus

        try:
            auth = writer.encrypt(password or "")
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
    return writer


def _declares_revocation(cert: asn1_x509.Certificate) -> bool:
    return bool(cert.ocsp_urls or cert.crl_distribution_points)


def _revocation_context(signer: signers.Signer, with_timestamp: bool):
    """Contexte qui interroge l'autorité (OCSP, CRL) pour l'état de révocation.

    Racines : celles de la chaîne construite par Windows, plus, avec un
    horodatage, les autorités racines approuvées par Windows (chaîne de la TSA).
    Renvoie (contexte, connexions à fermer), ou None si la chaîne est incomplète.
    """
    from pyhanko_certvalidator.fetchers.aiohttp_fetchers import AIOHttpFetcherBackend

    certs = [signer.signing_cert, *(signer.cert_registry or [])]
    roots = [c for c in certs if c.self_issued]
    if not roots:
        return None
    if with_timestamp:
        roots += [asn1_x509.Certificate.load(der) for der in wincert.trusted_root_ders()]
    backend = AIOHttpFetcherBackend(per_request_timeout=REVOCATION_TIMEOUT)
    context = ValidationContext(
        trust_roots=roots,
        other_certs=[c for c in certs[1:] if not c.self_issued],
        allow_fetching=True,
        # Toute source déclarée par un certificat doit répondre : l'état intégré est complet.
        revocation_mode="hard-fail",
        # Une réponse datée de quelques secondes « dans le futur » (horloge du poste en
        # retard sur celle de l'autorité) reste valable.
        retroactive_revinfo=True,
        fetcher_backend=backend,
    )
    return context, backend


async def _run_signer(pdf_signer: signers.PdfSigner, writer: IncrementalPdfFileWriter, backend) -> bytes:
    try:
        output = await pdf_signer.async_sign_pdf(writer, output=io.BytesIO())
        return output.getvalue()
    finally:
        if backend is not None:
            await backend.close()


def sign_pdf(
    pdf_bytes: bytes,
    options: SignOptions,
    *,
    store_factory: StoreFactory = wincert.CertStore.system,
    signer_override: signers.Signer | None = None,
) -> tuple[bytes, dict]:
    """Ajoute une signature PAdES (mise à jour incrémentale) et renvoie le PDF signé.

    Avec `options.ltv`, l'état de révocation de la chaîne est demandé à l'autorité
    avant la saisie du PIN (un certificat révoqué est refusé), puis intégré au
    document (DSS) dans une seconde mise à jour, comme le fait Acrobat.
    """
    if signer_override is not None:
        signer, signer_name = signer_override, signer_override.subject_name or "Signataire"
    else:
        try:
            signer, entry = prepare_signer(options, store_factory)
        except wincert.WinCertError as err:
            raise SigningError(str(err), err.code) from err
        signer_name = entry.subject_cn or entry.email or "Signataire"

    field_name = _unique_field_name(_open_writer(pdf_bytes, options.password))
    signed_at = datetime.now().astimezone()
    timestamper = None
    if options.timestamp_url:
        from pyhanko.sign.timestamps import HTTPTimeStamper

        timestamper = HTTPTimeStamper(options.timestamp_url, timeout=15)
    revocation = None
    ltv_note = ""
    if options.ltv and signer.signing_cert is not None and _declares_revocation(signer.signing_cert):
        revocation = _revocation_context(signer, timestamper is not None)
        if revocation is None:
            ltv_note = "État de révocation du certificat non intégré : chaîne de certification incomplète sur ce poste."

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

        def attempt(revocation_ctx) -> bytes:
            context, backend = revocation_ctx or (None, None)
            meta = signers.PdfSignatureMetadata(
                field_name=field_name,
                md_algorithm="sha256",
                reason=options.reason or None,
                location=options.location or None,
                contact_info=options.contact or None,
                name=signer_name,
                subfilter=fields.SigSeedSubFilter.PADES,
                embed_validation_info=context is not None,
                validation_context=context,
                signer_key_usage=set(),  # l'usage de la clé n'empêche pas de collecter l'état
            )
            pdf_signer = signers.PdfSigner(meta, signer=signer, timestamper=timestamper, stamp_style=style, new_field_spec=spec)
            return asyncio.run(_run_signer(pdf_signer, _open_writer(pdf_bytes, options.password), backend))

        try:
            signed = attempt(revocation)
        except Exception as exc:  # noqa: BLE001
            # PIN annulé, ou échec après la signature : jamais de seconde demande de PIN.
            if revocation is None or getattr(signer, "signatures_made", 0) or _find_cause(exc, wincert.WinCertError) is not None:
                raise
            if _find_cause(exc, RevokedError) is not None:
                raise SigningError(
                    "Votre certificat est révoqué : l'autorité de certification l'a déclaré invalide. "
                    "Une signature faite avec lui n'aurait aucune valeur.",
                    "revoked",
                ) from exc
            log.warning("état de révocation indisponible, signature sans LTV : %r", exc)
            revocation, ltv_note = None, LTV_UNAVAILABLE
            signed = attempt(None)
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
    return signed, {
        "field_name": field_name,
        "signer": signer_name,
        "signed_at": signed_at.isoformat(),
        "ltv": revocation is not None,
        "ltv_note": ltv_note,
        "timestamp": timestamper is not None,
    }


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
    ltv: bool = False  # état de révocation intégré, suffisant pour vérifier hors ligne
    timestamp: bool = False  # heure attestée par une autorité d'horodatage
    status: str = "invalid"  # valid, warning, invalid
    summary: str = ""
    page_index: int | None = None
    rect: list[float] | None = None
    errors: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return dict(self.__dict__)


_MODIFICATIONS = {
    "NONE": "aucune modification depuis la signature",
    "LTA_UPDATES": "aucune modification depuis la signature (données de validation ajoutées)",
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
    dss = _read_dss(reader)
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
            report.timestamp = status.timestamp_validity is not None
            if status.signer_reported_dt is not None:
                report.signed_at = status.signer_reported_dt.astimezone().isoformat()
                report.ltv = dss is not None and _ltv_complete(embedded, dss, status.signer_reported_dt)
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"Vérification impossible : {exc}")
        _summarise(report)
        reports.append(report)
    with FITZ_LOCK:
        _locate_widgets(pdf_bytes, reports, password)
    return reports


def _read_dss(reader: PdfFileReader):
    """Magasin de validation du document (DSS), s'il contient un état de révocation."""
    from pyhanko.sign.validation.dss import DocumentSecurityStore

    try:
        dss = DocumentSecurityStore.read_dss(reader)
    except Exception:  # noqa: BLE001 - pas de DSS, ou DSS illisible
        return None
    return dss if (dss.ocsps or dss.crls) else None


def _ltv_complete(embedded, dss, moment: datetime) -> bool:
    """L'état de révocation intégré suffit-il à vérifier la chaîne hors ligne, à la
    date de signature ? C'est ce qu'Acrobat appelle une signature « compatible LTV »."""
    from pyhanko_certvalidator import CertificateValidator

    try:
        others = list(embedded.other_embedded_certs)
        roots = [c for c in [*others, *dss.load_certs()] if c.self_issued]
        if not roots:
            return False
        # État obtenu juste avant la signature, ou daté par une autorité à l'horloge en
        # avance : `retroactive_revinfo` l'accepte à la date de signature.
        context = dss.as_validation_context(
            {"trust_roots": roots, "allow_fetching": False, "revocation_mode": "hard-fail", "moment": moment, "retroactive_revinfo": True}
        )
        validator = CertificateValidator(embedded.signer_cert, intermediate_certs=others, validation_context=context)
        asyncio.run(validator.async_validate_usage(set()))
        return True
    except Exception:  # noqa: BLE001 - état absent, incomplet ou invalide
        return False


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
