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
SEGOE_UI = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "segoeui.ttf"
BLACK = (0.0, 0.0, 0.0)
EMBLEM_TINT = (0.94, 0.86, 0.80)  # emblème DestriPDF pâle, là où Acrobat met son logo
SIGNED_BY = "Signature numérique de"  # libellé d'Acrobat en français
LINE_GAP = 1.2
INSET = 1.0  # Acrobat dessine à 1 pt du bord du champ
REVOCATION_TIMEOUT = 8  # secondes par requête OCSP ou CRL auprès de l'autorité
LTV_UNAVAILABLE = (
    "État de révocation du certificat non intégré : l'autorité de certification n'a pas pu être "
    "interrogée (connexion Internet ?). La signature est valide, mais Acrobat ne la dira pas "
    "« compatible LTV »."
)
LTV_INCOMPLETE_CHAIN = "État de révocation du certificat non intégré : chaîne de certification incomplète sur ce poste."
LTV_TSA_CHAIN = (
    "État de révocation non intégré : la chaîne du service d'horodatage n'a pas pu être vérifiée. "
    "La signature est valide et horodatée, mais Acrobat ne la dira pas « compatible LTV »."
)
LTV_NOT_RECORDED = (
    "État de révocation obtenu mais non enregistré dans le document : la signature est valide, "
    "sans validation à long terme."
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


def _appearance_font(text: str) -> fitz.Font:
    """Segoe UI, la police de Windows la plus proche de Myriad Pro (police d'Acrobat,
    propriété d'Adobe), sinon Roboto ; réduite au texte (table Unicode sans ambiguïté)."""
    from .. import fonts

    if SEGOE_UI.exists():
        choice = fonts.FontChoice(str(SEGOE_UI), 0, "Segoe UI", False, False, True)
    else:
        choice = fonts.FontChoice(str(FONT_DIR / "Roboto-Regular.ttf"), 0, "Roboto", False, False, True)
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


def _fit_block(paragraphs: list[str], font: fitz.Font, box: fitz.Rect, min_size: float = 1.0) -> tuple[float, list[str]]:
    """Plus grande taille où les paragraphes remplissent la boîte, comme Acrobat :
    retour à la ligne aux espaces, et dans un mot plus large que la boîte
    (« DESTRIB / OIS »). Un petit cadre réduit le texte au lieu de le tronquer."""

    def layout(size: float) -> list[str] | None:
        lines = [line for p in paragraphs for line in (_wrap(p, font, size, box.width, force=True) or [])]
        return lines if len(lines) * size * LINE_GAP <= box.height else None

    low, high = min_size, max(min_size, box.height / LINE_GAP)
    best = layout(high)
    if best is not None:
        return high, best
    best = layout(low) or [line for p in paragraphs for line in (_wrap(p, font, low, box.width, force=True) or [])]
    while high - low > 0.05:
        middle = (low + high) / 2
        lines = layout(middle)
        if lines is None:
            high = middle
        else:
            low, best = middle, lines
    return low, best


def _draw_block(page: fitz.Page, lines: list[str], font: fitz.Font, size: float, box: fitz.Rect) -> None:
    """Lignes alignées à gauche, en noir, bloc centré verticalement dans la boîte."""
    y = box.y0 + max(0.0, (box.height - len(lines) * size * LINE_GAP) / 2)
    writer = fitz.TextWriter(page.rect, color=BLACK)
    for line in lines:
        y += size * LINE_GAP
        writer.append((box.x0, y - size * 0.25), line, font=font, fontsize=size)
    writer.write_text(page)


def _draw_emblem(page: fitz.Page, box: fitz.Rect) -> None:
    """Emblème de DestriPDF (feuille, plume, trait) en filigrane pâle, centré, à la
    place qu'occupe le logo d'Acrobat (marque d'Adobe, jamais reproduite)."""
    side = min(box.width, box.height)
    if side < 6:
        return
    x0 = box.x0 + (box.width - side) / 2
    y0 = box.y0 + (box.height - side) / 2
    k = side / 32  # dessin de static/icon.svg (32 × 32)

    def at(x: float, y: float) -> fitz.Point:
        return fitz.Point(x0 + x * k, y0 + y * k)

    shape = page.new_shape()
    shape.draw_polyline([at(8, 3), at(19, 3), at(26, 10), at(26, 29), at(8, 29), at(8, 3)])
    shape.finish(color=EMBLEM_TINT, width=k, lineJoin=1, closePath=True)
    shape.draw_polyline([at(19, 3), at(19, 10), at(26, 10)])
    shape.finish(color=EMBLEM_TINT, width=k, lineJoin=1)
    shape.draw_bezier(at(12, 22.5), at(14.2, 21.1), at(15.4, 18.9), at(17, 16.1))
    shape.draw_line(at(17, 16.1), at(19.6, 17.6))
    shape.draw_bezier(at(19.6, 17.6), at(18, 20.5), at(16.3, 22.5), at(13.6, 23.8))
    shape.finish(color=None, fill=EMBLEM_TINT, closePath=True)
    shape.draw_line(at(12, 25), at(22, 25))
    shape.finish(color=EMBLEM_TINT, width=k, lineCap=1)
    shape.commit()


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
    inner = fitz.Rect(INSET, INSET, disp_w - INSET, disp_h - INSET)
    _draw_emblem(page, inner)
    # Deux moitiés, comme Acrobat : le nom (ou l'image manuscrite) à gauche, le détail à droite.
    middle = disp_w / 2
    left = fitz.Rect(inner.x0 + 0.5, inner.y0, max(inner.x0 + 1.5, middle - 1.5), inner.y1)
    right = fitz.Rect(middle + 2.5, inner.y0, max(middle + 3.5, inner.x1 - 0.5), inner.y1)

    if image_png:
        try:
            page.insert_image(left, stream=image_png, keep_proportion=True)
        except Exception:  # noqa: BLE001 - image illisible : nom en toutes lettres
            image_png = None
    if not image_png:
        name_font = _appearance_font(signer_name)
        size, lines = _fit_block([signer_name], name_font, left)
        _draw_block(page, lines, name_font, size, left)

    nbsp = "\u00a0"  # « Date : » reste sur une ligne
    paragraphs = [f"{SIGNED_BY} {signer_name}"]
    if reason:
        paragraphs.append(f"Motif{nbsp}: {reason}")
    if location:
        paragraphs.append(f"Lieu{nbsp}: {location}")
    paragraphs.append(f"Date{nbsp}: {format_signing_time(signed_at)}")
    details_font = _appearance_font(" ".join(paragraphs))
    size, lines = _fit_block(paragraphs, details_font, right)
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


def _chain_roots(signer: signers.Signer) -> tuple[list, list]:
    """Racines et intermédiaires de la chaîne du signataire (construite par Windows)."""
    certs = [signer.signing_cert, *(signer.cert_registry or [])]
    return [c for c in certs if c.self_issued], [c for c in certs[1:] if not c.self_issued]


def _revocation_context(roots: list, intermediates: list, backend, *, strict: bool) -> ValidationContext:
    """Contexte qui interroge l'autorité (OCSP, CRL). Strict : toute source déclarée
    doit répondre, pour un état intégré complet. Souple : les sources injoignables
    sont tolérées, seule une révocation établie compte."""
    return ValidationContext(
        trust_roots=roots,
        other_certs=intermediates,
        allow_fetching=True,
        revocation_mode="hard-fail" if strict else "soft-fail",
        # Une réponse datée de quelques secondes « dans le futur » (horloge du poste en
        # retard sur celle de l'autorité) reste valable.
        retroactive_revinfo=True,
        fetcher_backend=backend,
    )


async def _timestamper_roots(timestamper) -> list:
    """Racine de la chaîne du service d'horodatage, construite par Windows (qui
    télécharge au besoin l'autorité manquante) : sans elle, pas d'état de révocation
    pour cette chaîne. La réponse d'essai reste en cache pour la signature."""
    try:
        await timestamper.async_dummy_response("sha256")
        certs = list(timestamper.cert_registry)
    except Exception:  # noqa: BLE001 - service injoignable : la signature le dira
        return []

    def stamps(cert) -> bool:
        usage = cert.extended_key_usage_value
        return usage is not None and "time_stamping" in usage.native

    leaves = [c for c in certs if stamps(c)]
    if not leaves:
        return []
    helpers = [c.dump() for c in certs if c is not leaves[0]]
    try:
        chain = wincert.chain_for_certificates([leaves[0].dump(), *helpers], allow_network=True)
    except wincert.WinCertError:
        return []
    return [c for c in (asn1_x509.Certificate.load(der) for der in chain.ders) if c.self_issued]


async def _signer_revocation(signer: signers.Signer, roots: list, intermediates: list, backend) -> RevokedError | None:
    """Révocation de la chaîne du signataire, en mode souple : décelée même quand une
    autre source de la chaîne (liste de la racine…) ne répond pas."""
    from pyhanko_certvalidator import CertificateValidator

    context = _revocation_context(roots, intermediates, backend, strict=False)
    validator = CertificateValidator(signer.signing_cert, intermediate_certs=intermediates, validation_context=context)
    try:
        await validator.async_validate_usage(set())
    except RevokedError as err:
        return err
    except Exception:  # noqa: BLE001 - chaîne ou réseau : rien d'établi
        return None
    return None


def _revoked_message(err: RevokedError, signer_cert: asn1_x509.Certificate) -> str:
    leaf = getattr(getattr(err, "original_path", None), "leaf", None)
    if leaf is None or leaf.dump() == signer_cert.dump():
        if getattr(err, "is_ee_cert", True):
            return (
                "Votre certificat est révoqué : l'autorité de certification l'a déclaré invalide. "
                "Une signature faite avec lui n'aurait aucune valeur."
            )
        return "L'autorité qui a émis votre certificat est révoquée : une signature faite avec ce certificat n'aurait aucune valeur."
    return "Le certificat du service d'horodatage réglé est révoqué : changez d'adresse d'horodatage dans les Réglages, ou videz-la."


async def _sign_once(signer, timestamper, style, spec, meta_kwargs: dict, pdf_bytes: bytes, password, signed_at: datetime, context) -> tuple[bytes, str]:
    """Une signature, étape par étape comme `PdfSigner.async_sign_pdf`, pour deux
    garanties : l'heure de la signature (/M) est celle du cadre visible, et un échec
    de l'écriture de l'état de révocation (DSS), après la signature, n'en fait pas
    perdre la signature. Renvoie (PDF signé, message si le DSS manque)."""
    from pyhanko.sign.signers.pdf_cms import PdfCMSSignedAttributes

    meta = signers.PdfSignatureMetadata(
        **meta_kwargs,
        embed_validation_info=context is not None,
        validation_context=context,
        signer_key_usage=set(),  # l'usage de la clé n'empêche pas de collecter l'état
    )
    pdf_signer = signers.PdfSigner(meta, signer=signer, timestamper=timestamper, stamp_style=style, new_field_spec=spec)
    writer = _open_writer(pdf_bytes, password)
    session = pdf_signer.init_signing_session(writer)
    session.system_time = signed_at
    validation_info = await session.perform_presign_validation(writer)
    reserved = await session.estimate_signature_container_size(validation_info, tight=meta.tight_size_estimates)
    tbs = session.prepare_tbs_document(validation_info=validation_info, bytes_reserved=reserved)
    prepared, output = tbs.digest_tbs_document(output=io.BytesIO())
    post = await tbs.perform_signature(
        document_digest=prepared.document_digest,
        pdf_cms_signed_attrs=PdfCMSSignedAttributes(
            signing_time=session.system_time,
            adobe_revinfo_attr=None if validation_info is None else validation_info.adobe_revinfo_attr,
            cades_signed_attrs=meta.cades_signed_attr_spec,
        ),
    )
    signed = output.getvalue()
    try:
        await post.post_signature_processing(output)
    except Exception as exc:  # noqa: BLE001 - la signature est faite : la garder, sans LTV
        log.warning("état de révocation non enregistré après la signature : %r", exc)
        return signed, LTV_NOT_RECORDED
    return output.getvalue(), ""


async def _sign_flow(signer, timestamper, style, spec, meta_kwargs: dict, pdf_bytes: bytes, password, signed_at: datetime, want_ltv: bool) -> tuple[bytes, bool, str]:
    """Signature avec l'état de révocation intégré si possible, sinon sans ; un
    certificat révoqué est refusé avant le PIN, qui n'est jamais demandé deux fois.
    Renvoie (PDF signé, LTV intégrée, message pour l'utilisateur)."""

    async def once(context):
        return await _sign_once(signer, timestamper, style, spec, meta_kwargs, pdf_bytes, password, signed_at, context)

    note = ""
    if want_ltv:
        from pyhanko_certvalidator.fetchers.aiohttp_fetchers import AIOHttpFetcherBackend

        backend = AIOHttpFetcherBackend(per_request_timeout=REVOCATION_TIMEOUT)
        try:
            roots, intermediates = _chain_roots(signer)
            if not roots:
                note = LTV_INCOMPLETE_CHAIN
            else:
                revoked = None
                tsa_roots = await _timestamper_roots(timestamper) if timestamper is not None else []
                if timestamper is not None and not tsa_roots:
                    note = LTV_TSA_CHAIN
                    revoked = await _signer_revocation(signer, roots, intermediates, backend)
                else:
                    try:
                        signed, missing = await once(_revocation_context(roots + tsa_roots, intermediates, backend, strict=True))
                        return signed, not missing, missing
                    except Exception as exc:  # noqa: BLE001
                        # PIN annulé, ou échec après la signature : jamais de seconde demande de PIN.
                        if getattr(signer, "signatures_made", 0) or _find_cause(exc, wincert.WinCertError) is not None:
                            raise
                        revoked = _find_cause(exc, RevokedError) or await _signer_revocation(signer, roots, intermediates, backend)
                        if revoked is None:
                            log.warning("état de révocation indisponible, signature sans LTV : %r", exc)
                        note = LTV_UNAVAILABLE
                if revoked is not None:
                    raise SigningError(_revoked_message(revoked, signer.signing_cert), "revoked")
        finally:
            await backend.close()
    signed, _missing = await once(None)
    return signed, False, note


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
    # Heure du cadre visible et de la signature (/M) : la même, à la seconde.
    signed_at = datetime.now().astimezone().replace(microsecond=0)
    timestamper = None
    if options.timestamp_url:
        from pyhanko.sign.timestamps import HTTPTimeStamper

        timestamper = HTTPTimeStamper(options.timestamp_url, timeout=15)
    want_ltv = False
    if options.ltv and signer.signing_cert is not None:
        try:
            want_ltv = _declares_revocation(signer.signing_cert)
        except Exception:  # noqa: BLE001 - extension illisible : signature sans LTV
            log.warning("sources de révocation du certificat illisibles", exc_info=True)
    meta_kwargs = {
        "field_name": field_name,
        "md_algorithm": "sha256",
        "reason": options.reason or None,
        "location": options.location or None,
        "contact_info": options.contact or None,
        "name": signer_name,
        "subfilter": fields.SigSeedSubFilter.PADES,
    }

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
        signed, ltv, ltv_note = asyncio.run(
            _sign_flow(signer, timestamper, style, spec, meta_kwargs, pdf_bytes, options.password, signed_at, want_ltv)
        )
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
        "ltv": ltv,
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
    # Horodatage : "trusted" (jeton intact, autorité approuvée par Windows),
    # "unverified" (jeton présent, non vérifié), "" (heure de l'ordinateur du signataire).
    timestamp: str = ""
    timestamp_at: str = ""
    changes_allowed: bool = False  # modifications ultérieures admises (Acrobat : signature valide)
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
    "FORM_FILLING": "d'autres signatures ou des valeurs de formulaire ont été ajoutées ensuite (modifications autorisées)",
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
        chain_roots: list = []
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
            chain_roots = [c for c in (asn1_x509.Certificate.load(der) for der in chain.ders) if c.self_issued]
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"Certificat illisible : {exc}")
        try:
            status = validate_pdf_signature(embedded, ValidationContext(trust_roots=[], allow_fetching=False))
            report.intact = bool(status.intact)
            report.valid = bool(status.valid)
            report.covers_whole_file = status.coverage == SignatureCoverageLevel.ENTIRE_FILE
            level = status.modification_level.name if status.modification_level is not None else "OTHER"
            report.modification = _MODIFICATIONS.get(level, "")
            # Comme Acrobat : contresignature et remplissage de formulaire ne remettent pas
            # en cause une signature d'approbation, sauf interdiction du signataire (DocMDP).
            report.changes_allowed = level in ("NONE", "LTA_UPDATES", "FORM_FILLING") and status.docmdp_ok is not False
            if status.docmdp_ok is False and level in ("LTA_UPDATES", "FORM_FILLING"):
                report.modification = "modifications interdites par la signature de certification du document"
            if report.changes_allowed and not report.covers_whole_file:
                # pyHanko range au même niveau une valeur de champ modifiée qu'une
                # contresignature, et des métadonnées modifiées que l'ajout du DSS.
                later = _later_changes(reader, embedded)
                if later:
                    report.modification, report.changes_allowed = later, False
            report.timestamp, report.timestamp_at = _timestamp_state(embedded, status.timestamp_validity, trust_check)
            if status.signer_reported_dt is not None:
                moment = status.signer_reported_dt
                if moment.tzinfo is None:  # /M sans fuseau (permis par la norme) : heure locale
                    moment = moment.astimezone()
                report.signed_at = moment.astimezone().isoformat()
                report.ltv = _ltv_complete(embedded, dss, moment, chain_roots)
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


def _archived_revocation(embedded) -> tuple[list, list]:
    """État de révocation archivé dans la signature elle-même (format PKCS#7
    d'Acrobat, attribut adbe-revocationInfoArchival) : (CRL, réponses OCSP)."""
    crls: list = []
    ocsps: list = []
    try:
        for attr in embedded.signer_info["signed_attrs"] or []:
            if attr["type"].native != "adobe_revocation_info_archival":
                continue
            for archive in attr["values"]:
                if archive["crl"].native:
                    crls.extend(archive["crl"])
                if archive["ocsp"].native:
                    ocsps.extend(archive["ocsp"])
    except Exception:  # noqa: BLE001 - attribut illisible : rien d'archivé
        return [], []
    return crls, ocsps


def _ltv_complete(embedded, dss, moment: datetime, extra_roots: list | None = None) -> bool:
    """L'état de révocation intégré suffit-il à vérifier le certificat du signataire
    hors ligne, à la date de signature ? C'est ce qu'Acrobat appelle une signature
    « compatible LTV ». État lu dans le DSS (PAdES) ou dans la signature (PKCS#7
    d'Acrobat). Comme Acrobat avec la liste de confiance européenne, l'autorité
    émettrice sert d'ancre : Acrobat n'archive que l'état du certificat du
    signataire. Racines aussi prises dans la chaîne construite par Windows (autres
    logiciels de signature, qui n'intègrent pas toujours la racine)."""
    from asn1crypto import crl as asn1_crl
    from asn1crypto import ocsp as asn1_ocsp
    from pyhanko_certvalidator import CertificateValidator

    try:
        crls, ocsps = _archived_revocation(embedded)
        others = list(embedded.other_embedded_certs)
        certs = list(others)
        if dss is not None:
            certs += list(dss.load_certs())
            ocsps += [asn1_ocsp.OCSPResponse.load(ref.get_object().data) for ref in dss.ocsps]
            crls += [asn1_crl.CertificateList.load(ref.get_object().data) for ref in dss.crls]
        if not (crls or ocsps):
            return False
        signer_der = embedded.signer_cert.dump()
        roots = [c for c in certs if c.self_issued] + list(extra_roots or [])
        issuers = [c for c in certs if not c.self_issued and c.dump() != signer_der]
    except Exception:  # noqa: BLE001 - état illisible
        return False
    # Chaîne complète jusqu'à la racine, sinon l'autorité émettrice pour ancre.
    for anchors in (roots, issuers):
        if not anchors:
            continue
        try:
            # État obtenu juste avant la signature, ou daté par une autorité à l'horloge
            # en avance : `retroactive_revinfo` l'accepte à la date de signature.
            context = ValidationContext(
                trust_roots=anchors, other_certs=certs, crls=crls, ocsps=ocsps, allow_fetching=False,
                revocation_mode="hard-fail", moment=moment, retroactive_revinfo=True,
            )
            validator = CertificateValidator(embedded.signer_cert, intermediate_certs=others, validation_context=context)
            asyncio.run(validator.async_validate_usage(set()))
            return True
        except Exception:  # noqa: BLE001 - état absent, incomplet ou invalide pour cette ancre
            continue
    return False


def _timestamp_state(embedded, tv, trust_check) -> tuple[str, str]:
    """(« trusted » | « unverified » | « », heure du jeton). « trusted » : jeton
    intact et valide, autorité d'horodatage approuvée par Windows."""
    if tv is None:
        return "", ""
    at = tv.timestamp.astimezone().isoformat() if getattr(tv, "timestamp", None) else ""
    if not (tv.intact and tv.valid):
        return "unverified", at
    try:
        from pyhanko.sign.general import extract_certificate_info
        from pyhanko.sign.validation.generic_cms import extract_tst_data_iter

        for token in extract_tst_data_iter(embedded.signer_info, signed=False):
            certs = extract_certificate_info(token)
            if trust_check([certs.signer_cert.dump(), *(c.dump() for c in certs.other_certs)]).trusted:
                return "trusted", at
    except Exception:  # noqa: BLE001 - jeton illisible : non vérifié
        pass
    return "unverified", at


_INFO_REWRITTEN = {"/ModDate", "/Producer"}  # réécrits à chaque enregistrement (DSS compris)
_XMP_CONTENT = ("{http://purl.org/dc/elements/1.1/}", "{http://ns.adobe.com/pdf/1.3/}Keywords")


def _metadata(handler) -> dict[str, str]:
    """Titre, auteur, sujet, mots-clés… (/Info et XMP), sans les dates et le
    producteur que tout enregistrement réécrit."""
    from pyhanko.pdf_utils import generic

    found: dict[str, str] = {}
    try:
        trailer = handler.trailer_view
        raw = trailer.raw_get("/Info") if "/Info" in trailer else None
        # Les références de la vue historique du trailer pointent vers la dernière
        # révision : résoudre /Info dans la révision de `handler`.
        info = handler.get_object(raw.reference) if isinstance(raw, generic.IndirectObject) else (raw or {})
        for key in info:
            if key not in _INFO_REWRITTEN:
                found[str(key)] = str(info[key])
    except Exception:  # noqa: BLE001
        found["/Info"] = "illisible"
    try:
        stream = handler.root.get("/Metadata")
        if stream is not None:
            import xml.etree.ElementTree as ElementTree

            for node in ElementTree.fromstring(stream.get_object().data).iter():
                if isinstance(node.tag, str) and node.tag.startswith(_XMP_CONTENT):
                    found["xmp " + node.tag] = found.get("xmp " + node.tag, "") + "".join(node.itertext()).strip()
    except Exception:  # noqa: BLE001
        found["xmp"] = "illisible"
    return found


def _form_values(handler) -> dict[str, str]:
    """Valeurs des champs de formulaire hors signatures (nom complet -> valeur)."""
    values: dict[str, str] = {}
    try:
        form = handler.root.get("/AcroForm")
        roots = form.get_object().get("/Fields") if form is not None else None
        stack = [(ref, "", None, 0) for ref in (roots.get_object() if roots is not None else [])]
    except Exception:  # noqa: BLE001
        return {"/AcroForm": "illisible"}
    while stack:
        ref, prefix, inherited, depth = stack.pop()
        if depth > 32:  # arborescence anormale : on s'arrête
            continue
        try:
            node = ref.get_object()
            part = str(node.get("/T", ""))
            name = f"{prefix}.{part}" if prefix and part else (part or prefix)
            kind = str(node.get("/FT", inherited) or "")
            if "/V" in node and kind != "/Sig":
                values[name] = str(node["/V"])
            stack.extend((kid, name, kind, depth + 1) for kid in (node.get("/Kids") or []))
        except Exception:  # noqa: BLE001
            values[f"{prefix}?{depth}"] = "illisible"
    return values


def _later_changes(reader: PdfFileReader, embedded) -> str:
    """Changement non admis après la signature, sous un niveau pyHanko admis :
    valeur d'un champ (autre que signature) ou métadonnées. Vide sinon."""
    try:
        signed = reader.get_historical_resolver(embedded.signed_revision)
    except Exception:  # noqa: BLE001
        return ""
    before, after = _form_values(signed), _form_values(reader)
    changed = sorted(name for name in set(before) | set(after) if before.get(name) != after.get(name))
    if changed:
        names = ", ".join(f"« {name} »" for name in changed[:3]) + (" …" if len(changed) > 3 else "")
        return f"valeur de champ modifiée après la signature : {names}"
    if _metadata(signed) != _metadata(reader):
        return "métadonnées du document (titre, auteur…) modifiées après la signature"
    return ""


def _summarise(report: SignatureReport) -> None:
    if not (report.intact and report.valid):
        report.status = "invalid"
        report.summary = "Signature invalide : le document a été altéré ou la signature est corrompue."
        return
    altered = not report.changes_allowed
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
