"""Signature PAdES par la clé Windows (PFX en mémoire) et vérification."""

import contextlib
import hashlib
import threading

import pymupdf as fitz
import pytest

from destripdf.signing import pades, wincert
from tests.pki import PFX_PASSWORD, make_test_pki


@pytest.fixture(scope="module")
def identity():
    return make_test_pki()


@pytest.fixture()
def store_factory(identity):
    return lambda: wincert.CertStore.from_pfx(identity.pfx, PFX_PASSWORD)


def _sample_pdf(rotation: int = 0, pages: int = 2) -> bytes:
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Acte d'engagement - page {i + 1}", fontsize=14)
        if rotation:
            page.set_rotation(rotation)
    return doc.tobytes()


def _trusted(ders):
    return wincert.ChainResult(ders=ders, error_status=0)


def test_visible_signature_is_valid_and_covers_file(identity, store_factory):
    thumb = hashlib.sha1(identity.der).hexdigest()
    options = pades.SignOptions(
        thumbprint=thumb,
        reason="Bon pour accord",
        location="Zellwiller",
        appearance=pades.Appearance(page_index=1, rect=(300, 650, 540, 730)),
    )
    signed, info = pades.sign_pdf(_sample_pdf(), options, store_factory=store_factory)
    assert info["field_name"] == "Signature1"
    assert info["signer"] == "Florent TEST"

    reports = pades.validate_signatures(signed, trust_check=_trusted)
    assert len(reports) == 1
    report = reports[0]
    assert report.intact and report.valid and report.covers_whole_file
    assert report.status == "valid", report.summary
    assert report.signer == "Florent TEST"
    assert report.reason == "Bon pour accord" and report.location == "Zellwiller"
    assert report.qualified
    assert report.page_index == 1
    x0, y0, x1, y1 = report.rect
    assert abs(x0 - 300) < 0.5 and abs(y0 - 650) < 0.5 and abs(x1 - 540) < 0.5 and abs(y1 - 730) < 0.5

    doc = fitz.open("pdf", signed)
    from destripdf.document import has_signatures

    assert has_signatures(doc)
    text = doc[1].get_text()  # l'apparence fait partie de l'affichage
    pix = doc[1].get_pixmap(clip=fitz.Rect(300, 650, 540, 730), annots=True)
    assert pix.color_count() > 1, "apparence visible vide"
    assert "Acte d'engagement" in text


def test_untrusted_root_gives_warning(identity, store_factory):
    thumb = hashlib.sha1(identity.der).hexdigest()
    signed, _ = pades.sign_pdf(_sample_pdf(), pades.SignOptions(thumbprint=thumb), store_factory=store_factory)
    report = pades.validate_signatures(signed)[0]
    assert report.intact and report.valid
    assert not report.trusted
    assert report.status == "warning"
    assert "racine non approuvée" in report.summary


def test_second_signature_keeps_first_valid(identity, store_factory):
    thumb = hashlib.sha1(identity.der).hexdigest()
    once, _ = pades.sign_pdf(
        _sample_pdf(), pades.SignOptions(thumbprint=thumb, appearance=pades.Appearance(0, (60, 600, 260, 680))),
        store_factory=store_factory,
    )
    twice, info = pades.sign_pdf(
        once, pades.SignOptions(thumbprint=thumb, appearance=pades.Appearance(0, (300, 600, 500, 680))),
        store_factory=store_factory,
    )
    assert info["field_name"] == "Signature2"
    assert twice.startswith(once)  # mise à jour incrémentale
    first, second = pades.validate_signatures(twice, trust_check=_trusted)
    assert first.intact and first.valid and not first.covers_whole_file
    assert "signatures ont été ajoutés" in first.modification
    assert first.status == "warning"
    assert second.status == "valid"


def test_rotated_page_signature(identity, store_factory):
    thumb = hashlib.sha1(identity.der).hexdigest()
    pdf = _sample_pdf(rotation=90, pages=1)
    doc = fitz.open("pdf", pdf)
    page = doc[0]
    # cadre saisi dans l'affichage (page pivotée), converti en coordonnées non pivotées
    shown = fitz.Rect(500, 300, 700, 380)
    unrotated = shown * page.derotation_matrix
    unrotated.normalize()
    signed, _ = pades.sign_pdf(
        pdf,
        pades.SignOptions(thumbprint=thumb, appearance=pades.Appearance(0, tuple(unrotated))),
        store_factory=store_factory,
    )
    report = pades.validate_signatures(signed, trust_check=_trusted)[0]
    assert report.status == "valid"
    x0, y0, x1, y1 = report.rect
    assert abs(x0 - 500) < 0.5 and abs(y1 - 380) < 0.5


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_visible_signature_reads_upright_on_rotated_page(identity, store_factory, rotation):
    """Le texte de l'apparence s'affiche horizontal, quelle que soit la rotation de la page."""
    import math

    pdf = _sample_pdf(rotation=rotation, pages=1)
    page = fitz.open("pdf", pdf)[0]
    unrotated = fitz.Rect(320, 300, 540, 380) * page.derotation_matrix
    unrotated.normalize()
    signed, _ = pades.sign_pdf(
        pdf, pades.SignOptions(thumbprint=hashlib.sha1(identity.der).hexdigest(), appearance=pades.Appearance(0, tuple(unrotated))),
        store_factory=store_factory,
    )
    page = fitz.open("pdf", signed)[0]
    rot = page.rotation_matrix
    linear = fitz.Matrix(rot.a, rot.b, rot.c, rot.d, 0, 0)
    found = False
    for block in page.get_text("dict")["blocks"]:  # inclut l'apparence du champ de signature
        for line in block.get("lines", []):
            text = "".join(s["text"] for s in line["spans"])
            if "numérique" in text:
                shown = fitz.Point(line["dir"]) * linear
                assert abs(math.degrees(math.atan2(shown.y, shown.x))) < 1, (rotation, line["dir"])
                found = True
    assert found


def test_sign_password_protected_pdf(identity, store_factory):
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Acte d'engagement protégé", fontsize=14)
    pdf = doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="1234", owner_pw="proprio")
    thumb = hashlib.sha1(identity.der).hexdigest()
    with pytest.raises(pades.SigningError) as err:
        pades.sign_pdf(pdf, pades.SignOptions(thumbprint=thumb), store_factory=store_factory)
    assert err.value.code == "password"
    for appearance in (None, pades.Appearance(0, (300, 650, 540, 730))):
        signed, _ = pades.sign_pdf(
            pdf, pades.SignOptions(thumbprint=thumb, appearance=appearance, password="1234"), store_factory=store_factory
        )
        assert fitz.open("pdf", signed).needs_pass  # le chiffrement est conservé
        report = pades.validate_signatures(signed, trust_check=_trusted, password="1234")[0]
        assert report.intact and report.valid and report.status == "valid"


def test_sign_restricted_pdf_without_user_password(identity, store_factory):
    """PDF « restreint » (mot de passe propriétaire seul) : s'ouvre et se signe sans saisie."""
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Règlement de consultation", fontsize=14)
    pdf = doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_128, owner_pw="proprio", permissions=fitz.PDF_PERM_PRINT)
    assert not fitz.open("pdf", pdf).needs_pass
    thumb = hashlib.sha1(identity.der).hexdigest()
    signed, _ = pades.sign_pdf(pdf, pades.SignOptions(thumbprint=thumb, appearance=pades.Appearance(0, (300, 650, 540, 730))), store_factory=store_factory)
    report = pades.validate_signatures(signed, trust_check=_trusted)[0]
    assert report.intact and report.valid


def test_cancelled_pin_raises_clear_error(identity):
    class CancellingStore(wincert.CertStore):
        def sign_digest(self, *args, **kwargs):
            raise wincert.WinCertError("Signature annulée : la saisie du code PIN a été interrompue.", code="cancelled")

    def factory():
        store = wincert.CertStore.from_pfx(identity.pfx, PFX_PASSWORD)
        store.__class__ = CancellingStore
        return store

    thumb = hashlib.sha1(identity.der).hexdigest()
    with pytest.raises(pades.SigningError) as err:
        pades.sign_pdf(_sample_pdf(), pades.SignOptions(thumbprint=thumb), store_factory=factory)
    assert err.value.code == "cancelled"
    assert "PIN" in str(err.value)


def test_expired_or_unknown_certificate(identity, store_factory):
    with pytest.raises(pades.SigningError) as err:
        pades.sign_pdf(_sample_pdf(), pades.SignOptions(thumbprint="AB" * 20), store_factory=store_factory)
    assert err.value.code == "not_found"


def test_appearance_with_image_renders(identity, store_factory):
    sig_img = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 120, 40), False)
    sig_img.clear_with(255)
    for x in range(10, 110):
        sig_img.set_pixel(x, 20 + (x % 7) - 3, (20, 30, 90))
    png = sig_img.tobytes("png")
    thumb = hashlib.sha1(identity.der).hexdigest()
    signed, _ = pades.sign_pdf(
        _sample_pdf(),
        pades.SignOptions(thumbprint=thumb, appearance=pades.Appearance(0, (72, 500, 330, 580), image_png=png)),
        store_factory=store_factory,
    )
    assert pades.validate_signatures(signed, trust_check=_trusted)[0].status == "valid"


def test_timestamp_from_local_tsa(identity, store_factory):
    """Horodatage (PAdES B-T) par une autorité d'horodatage locale simulée."""
    import datetime as dt
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from asn1crypto import keys, tsp
    from asn1crypto import x509 as asn1_x509
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.timestamps import DummyTimeStamper

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Horodatage de test")])
    now = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now).not_valid_after(now + dt.timedelta(days=30))
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.TIME_STAMPING]), critical=True)
        .sign(key, hashes.SHA256())
    )
    tsa = DummyTimeStamper(
        tsa_cert=asn1_x509.Certificate.load(cert.public_bytes(serialization.Encoding.DER)),
        tsa_key=keys.PrivateKeyInfo.load(key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())),
    )
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            calls.append(self.headers.get("Content-Type"))
            answer = tsa.request_tsa_response(tsp.TimeStampReq.load(body)).dump()
            self.send_response(200)
            self.send_header("Content-Type", "application/timestamp-reply")
            self.send_header("Content-Length", str(len(answer)))
            self.end_headers()
            self.wfile.write(answer)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        thumb = hashlib.sha1(identity.der).hexdigest()
        options = pades.SignOptions(thumbprint=thumb, timestamp_url=f"http://127.0.0.1:{server.server_address[1]}/tsa")
        signed, _ = pades.sign_pdf(_sample_pdf(), options, store_factory=store_factory)
    finally:
        server.shutdown()
    # pyHanko interroge l'autorité une première fois pour estimer la taille du jeton.
    assert calls and all(c == "application/timestamp-query" for c in calls)
    from pyhanko.sign.validation import validate_pdf_signature
    from pyhanko_certvalidator import ValidationContext

    embedded = PdfFileReader(__import__("io").BytesIO(signed)).embedded_signatures[0]
    status = validate_pdf_signature(embedded, ValidationContext(trust_roots=[], allow_fetching=False))
    assert status.timestamp_validity is not None and status.timestamp_validity.intact
    assert pades.validate_signatures(signed, trust_check=_trusted)[0].intact


def test_format_signing_time():
    """Format de date d'Acrobat."""
    from datetime import datetime, timedelta, timezone

    moment = datetime(2026, 10, 12, 14, 32, 5, tzinfo=timezone(timedelta(hours=2)))
    assert pades.format_signing_time(moment) == "2026.10.12 14:32:05 +02'00'"
    west = moment.replace(tzinfo=timezone(-timedelta(hours=3, minutes=30)))
    assert pades.format_signing_time(west) == "2026.10.12 14:32:05 -03'30'"


@pytest.mark.parametrize("box", [(300, 650, 540, 730), (60, 600, 150, 618)])
def test_appearance_reads_like_acrobat(identity, store_factory, box):
    """Nom en grand à gauche ; « Signature numérique de … », motif et date à droite."""
    import re

    rect = fitz.Rect(box)
    signed, _ = pades.sign_pdf(
        _sample_pdf(),
        pades.SignOptions(thumbprint=hashlib.sha1(identity.der).hexdigest(), reason="Bon pour accord", appearance=pades.Appearance(1, box)),
        store_factory=store_factory,
    )
    assert pades.validate_signatures(signed, trust_check=_trusted)[0].status == "valid"
    page = fitz.open("pdf", signed)[1]
    middle = rect.x0 + rect.width / 2
    words = [w for w in page.get_text("words") if fitz.Rect(w[:4]).intersects(rect)]
    left = [w for w in words if w[2] <= middle + 0.5]
    right = [w for w in words if w[0] >= middle - 0.5]
    assert " ".join(w[4] for w in left) == "Florent TEST"
    details = " ".join(w[4] for w in right).replace("\xa0", " ")
    assert "Signature numérique de Florent TEST" in details
    assert "Motif : Bon pour accord" in details
    assert re.search(r"Date : \d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2} [+-]\d{2}'\d{2}'", details), details
    name_height = max(w[3] - w[1] for w in left)
    assert all(w[3] - w[1] < name_height for w in right), "le détail doit rester plus petit que le nom"


# --- État de révocation intégré (LTV) -------------------------------------------


@contextlib.contextmanager
def _authority(crls: dict[str, bytes]):
    """Autorité simulée : publie ses listes de révocation sur un serveur local."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    hits: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            name = self.path.rsplit("/", 1)[-1]
            hits.append(name)
            data = crls.get(name)
            if data is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/pkix-crl")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", hits
    finally:
        server.shutdown()
        server.server_close()


def _counting_factory(ident):
    """Magasin du PFX de test qui compte les demandes de signature (saisies de PIN)."""
    calls: list[int] = []

    class CountingStore(wincert.CertStore):
        def sign_digest(self, *args, **kwargs):
            calls.append(1)
            return super().sign_digest(*args, **kwargs)

    def factory():
        store = wincert.CertStore.from_pfx(ident.pfx, PFX_PASSWORD)
        store.__class__ = CountingStore
        return store

    return factory, calls


def test_ltv_embeds_revocation_and_verifies_offline():
    import io

    from asn1crypto import x509 as asn1_x509
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation import validate_pdf_signature
    from pyhanko.sign.validation.dss import DocumentSecurityStore

    crls: dict[str, bytes] = {}
    with _authority(crls) as (base, hits):
        ident = make_test_pki(crl_base=base)
        crls.update(ident.crls)
        factory, calls = _counting_factory(ident)
        signed, info = pades.sign_pdf(
            _sample_pdf(),
            pades.SignOptions(thumbprint=hashlib.sha1(ident.der).hexdigest(), appearance=pades.Appearance(0, (300, 650, 540, 730))),
            store_factory=factory,
        )
    assert info["ltv"] and not info["ltv_note"], info
    assert len(calls) == 1
    assert {"racine.crl", "intermediaire.crl"} <= set(hits)

    report = pades.validate_signatures(signed, trust_check=_trusted)[0]
    assert report.intact and report.valid and report.status == "valid", report.summary
    assert report.ltv
    assert report.modification.startswith("aucune modification")

    # Autorité arrêtée : l'état intégré suffit à vérifier la chaîne, sans réseau.
    reader = PdfFileReader(io.BytesIO(signed))
    dss = DocumentSecurityStore.read_dss(reader)
    assert len(dss.crls) == 2
    root = asn1_x509.Certificate.load(ident.chain_ders[-1])
    context = dss.as_validation_context({"trust_roots": [root], "allow_fetching": False, "revocation_mode": "hard-fail"})
    status = validate_pdf_signature(reader.embedded_signatures[0], context)
    assert status.intact and status.valid and status.trusted, status.pretty_print_details()


def test_ltv_tolerates_authority_clock_ahead():
    """Horloge du poste en retard de 2 minutes sur l'autorité : l'état reste intégré."""
    crls: dict[str, bytes] = {}
    with _authority(crls) as (base, _hits):
        ident = make_test_pki(crl_base=base, authority_clock_ahead=7 * 60)  # émis 2 min « dans le futur »
        crls.update(ident.crls)
        signed, info = pades.sign_pdf(
            _sample_pdf(), pades.SignOptions(thumbprint=hashlib.sha1(ident.der).hexdigest()),
            store_factory=lambda: wincert.CertStore.from_pfx(ident.pfx, PFX_PASSWORD),
        )
    assert info["ltv"], info["ltv_note"]
    assert pades.validate_signatures(signed, trust_check=_trusted)[0].ltv


def test_ltv_unreachable_authority_signs_once_without_ltv():
    crls: dict[str, bytes] = {}
    with _authority(crls) as (base, _hits):
        ident = make_test_pki(crl_base=base)
    # Serveur arrêté : l'autorité ne répond plus (poste hors ligne).
    factory, calls = _counting_factory(ident)
    signed, info = pades.sign_pdf(_sample_pdf(), pades.SignOptions(thumbprint=hashlib.sha1(ident.der).hexdigest()), store_factory=factory)
    assert len(calls) == 1, "le code PIN ne doit être demandé qu'une fois"
    assert not info["ltv"] and "non intégré" in info["ltv_note"]
    report = pades.validate_signatures(signed, trust_check=_trusted)[0]
    assert report.status == "valid" and report.covers_whole_file and not report.ltv


def test_revoked_certificate_is_refused_before_pin():
    crls: dict[str, bytes] = {}
    with _authority(crls) as (base, _hits):
        ident = make_test_pki(crl_base=base, revoked=True)
        crls.update(ident.crls)
        factory, calls = _counting_factory(ident)
        with pytest.raises(pades.SigningError) as err:
            pades.sign_pdf(_sample_pdf(), pades.SignOptions(thumbprint=hashlib.sha1(ident.der).hexdigest()), store_factory=factory)
    assert err.value.code == "revoked"
    assert "révoqué" in str(err.value)
    assert not calls, "aucun code PIN pour un certificat révoqué"


def test_ltv_disabled_makes_no_request():
    crls: dict[str, bytes] = {}
    with _authority(crls) as (base, hits):
        ident = make_test_pki(crl_base=base)
        crls.update(ident.crls)
        signed, info = pades.sign_pdf(
            _sample_pdf(), pades.SignOptions(thumbprint=hashlib.sha1(ident.der).hexdigest(), ltv=False),
            store_factory=lambda: wincert.CertStore.from_pfx(ident.pfx, PFX_PASSWORD),
        )
    assert not hits
    assert not info["ltv"] and not info["ltv_note"]
    assert pades.validate_signatures(signed, trust_check=_trusted)[0].covers_whole_file
