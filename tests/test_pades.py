"""Signature PAdES par la clé Windows (PFX en mémoire) et vérification."""

import contextlib
import hashlib
import threading

import pymupdf as fitz
import pytest

from destripdf.signing import pades, wincert
from tests.pki import PFX_PASSWORD, make_test_pki, ocsp_good_response


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
    assert "d'autres signatures" in first.modification
    # Comme Acrobat : une contresignature ne remet pas en cause la première signature.
    assert first.status == "valid", first.summary
    assert second.status == "valid"


def test_annotation_after_signature_needs_review(identity, store_factory, tmp_path):
    """Une annotation ajoutée après la signature reste signalée « à vérifier »."""
    thumb = hashlib.sha1(identity.der).hexdigest()
    signed, _ = pades.sign_pdf(_sample_pdf(), pades.SignOptions(thumbprint=thumb), store_factory=store_factory)
    path = tmp_path / "signe.pdf"
    path.write_bytes(signed)
    doc = fitz.open(path)
    doc[0].add_text_annot((100, 100), "Remarque ajoutée après signature")
    doc.saveIncr()
    doc.close()
    report = pades.validate_signatures(path.read_bytes(), trust_check=_trusted)[0]
    assert report.intact and report.valid
    assert not report.changes_allowed
    assert report.status == "warning", report.summary


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


@contextlib.contextmanager
def _local_tsa():
    """Autorité d'horodatage simulée (certificat auto-signé) sur un serveur local."""
    import datetime as dt
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from asn1crypto import keys, tsp
    from asn1crypto import x509 as asn1_x509
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
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
    calls: list[str] = []

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

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/tsa", calls
    finally:
        server.shutdown()
        server.server_close()


def test_timestamp_from_local_tsa(identity, store_factory):
    """Horodatage (PAdES B-T) par une autorité d'horodatage locale simulée."""
    import io

    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation import validate_pdf_signature
    from pyhanko_certvalidator import ValidationContext

    thumb = hashlib.sha1(identity.der).hexdigest()
    with _local_tsa() as (url, calls):
        signed, info = pades.sign_pdf(_sample_pdf(), pades.SignOptions(thumbprint=thumb, timestamp_url=url), store_factory=store_factory)
    # pyHanko interroge l'autorité une première fois pour estimer la taille du jeton.
    assert calls and all(c == "application/timestamp-query" for c in calls)
    assert info["timestamp"]
    embedded = PdfFileReader(io.BytesIO(signed)).embedded_signatures[0]
    status = validate_pdf_signature(embedded, ValidationContext(trust_roots=[], allow_fetching=False))
    assert status.timestamp_validity is not None and status.timestamp_validity.intact
    report = pades.validate_signatures(signed, trust_check=_trusted)[0]
    assert report.intact and report.timestamp == "trusted" and report.timestamp_at

    # Autorité d'horodatage inconnue de Windows : jeton présent, heure non attestée.
    def signer_only(ders):
        trusted = ders[0] == identity.der
        return wincert.ChainResult(ders=ders, error_status=0 if trusted else wincert.CERT_TRUST_IS_UNTRUSTED_ROOT)

    report = pades.validate_signatures(signed, trust_check=signer_only)[0]
    assert report.status == "valid" and report.timestamp == "unverified"


def test_ltv_with_timestamp_authority():
    """LTV et horodatage ensemble : la racine de l'autorité d'horodatage vient de la
    chaîne construite par Windows à partir de son jeton."""
    crls: dict[str, bytes] = {}
    with _authority(crls) as (base, _hits), _local_tsa() as (url, _calls):
        ident = make_test_pki(crl_base=base)
        crls.update(ident.crls)
        factory, pins = _counting_factory(ident)
        signed, info = pades.sign_pdf(_sample_pdf(), pades.SignOptions(thumbprint=hashlib.sha1(ident.der).hexdigest(), timestamp_url=url), store_factory=factory)
    assert len(pins) == 1
    assert info["ltv"] and info["timestamp"], info
    report = pades.validate_signatures(signed, trust_check=_trusted)[0]
    assert report.status == "valid" and report.ltv and report.timestamp == "trusted", report.summary


def _form_with_amount() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Acte d'engagement", fontsize=14)
    widget = fitz.Widget()
    widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    widget.field_name = "montant"
    widget.field_value = "120 000,00 EUR"
    widget.rect = fitz.Rect(100, 100, 300, 120)
    page.add_widget(widget)
    return doc.tobytes()


def _third_party_update(pdf: bytes, change) -> bytes:
    """Mise à jour incrémentale minimale par un tiers (pyHanko), après la signature."""
    import io

    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter

    writer = IncrementalPdfFileWriter(io.BytesIO(pdf))
    change(writer)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def test_form_value_changed_after_signature_needs_review(identity, store_factory):
    """Un montant changé après la signature n'est pas une modification admise."""
    from pyhanko.pdf_utils import generic

    thumb = hashlib.sha1(identity.der).hexdigest()
    signed, _ = pades.sign_pdf(_form_with_amount(), pades.SignOptions(thumbprint=thumb), store_factory=store_factory)

    def change_amount(writer):
        for ref in writer.root["/AcroForm"]["/Fields"]:
            field = ref.get_object()
            if field.get("/T") == "montant":
                field["/V"] = generic.TextStringObject("98 000,00 EUR")
                writer.update_container(field)

    report = pades.validate_signatures(_third_party_update(signed, change_amount), trust_check=_trusted)[0]
    assert report.intact and report.valid
    assert report.status == "warning" and "montant" in report.summary, report.summary

    # Témoin : une contresignature seule laisse la première signature valide.
    twice, _ = pades.sign_pdf(signed, pades.SignOptions(thumbprint=thumb, appearance=pades.Appearance(0, (300, 600, 500, 680))), store_factory=store_factory)
    assert pades.validate_signatures(twice, trust_check=_trusted)[0].status == "valid"


def test_metadata_change_after_signature_needs_review(identity, store_factory):
    signed, _ = pades.sign_pdf(_sample_pdf(), pades.SignOptions(thumbprint=hashlib.sha1(identity.der).hexdigest()), store_factory=store_factory)

    def retitle(writer):
        writer.document_meta.title = "Titre modifié"
        writer.mark_update(writer._info)  # sans objet modifié, pyHanko n'écrit aucune révision

    changed = _third_party_update(signed, retitle)
    assert fitz.open("pdf", changed).metadata["title"] == "Titre modifié"
    report = pades.validate_signatures(changed, trust_check=_trusted)[0]
    assert report.status == "warning" and "métadonnées" in report.summary, report.summary


def test_ltv_on_document_with_xmp_metadata_stays_valid():
    """pyHanko réécrit dates et producteur (/Info, XMP) en ajoutant le DSS : ce n'est
    pas une modification du document."""
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Acte d'engagement", fontsize=14)
    doc.set_metadata({"title": "Acte d'engagement", "author": "Menuiserie Destribois"})
    doc.set_xml_metadata(
        '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:xmp="http://ns.adobe.com/xap/1.0/">'
        '<dc:title><rdf:Alt><rdf:li xml:lang="x-default">Acte d\'engagement</rdf:li></rdf:Alt></dc:title>'
        "<xmp:ModifyDate>2026-10-01T10:00:00+02:00</xmp:ModifyDate></rdf:Description></rdf:RDF></x:xmpmeta>"
    )
    crls: dict[str, bytes] = {}
    with _authority(crls) as (base, _hits):
        ident = make_test_pki(crl_base=base)
        crls.update(ident.crls)
        signed, info = pades.sign_pdf(doc.tobytes(), pades.SignOptions(thumbprint=hashlib.sha1(ident.der).hexdigest()),
                                      store_factory=lambda: wincert.CertStore.from_pfx(ident.pfx, PFX_PASSWORD))
    assert info["ltv"]
    report = pades.validate_signatures(signed, trust_check=_trusted)[0]
    assert report.status == "valid" and report.ltv, report.summary


def test_revoked_certificate_refused_even_without_root_list():
    """Liste de révocation de la racine absente : la révocation du signataire est
    quand même décelée avant le PIN (contrôle souple du seul signataire)."""
    crls: dict[str, bytes] = {}
    with _authority(crls) as (base, hits):
        ident = make_test_pki(crl_base=base, revoked=True)
        crls["intermediaire.crl"] = ident.crls["intermediaire.crl"]
        factory, pins = _counting_factory(ident)
        with pytest.raises(pades.SigningError) as err:
            pades.sign_pdf(_sample_pdf(), pades.SignOptions(thumbprint=hashlib.sha1(ident.der).hexdigest()), store_factory=factory)
    assert err.value.code == "revoked" and "Votre certificat est révoqué" in str(err.value)
    assert not pins and "racine.crl" in hits


def test_unreadable_existing_dss_keeps_the_signature():
    """L'écriture de l'état de révocation échoue après le PIN : la signature est gardée."""
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Acte d'engagement", fontsize=14)
    xref = doc.get_new_xref()
    doc.update_object(xref, "<<>>")
    doc.update_stream(xref, b"\x00 certificat illisible")
    doc.xref_set_key(doc.pdf_catalog(), "DSS", f"<</Certs [{xref} 0 R]>>")
    crls: dict[str, bytes] = {}
    with _authority(crls) as (base, _hits):
        ident = make_test_pki(crl_base=base)
        crls.update(ident.crls)
        factory, pins = _counting_factory(ident)
        signed, info = pades.sign_pdf(doc.tobytes(), pades.SignOptions(thumbprint=hashlib.sha1(ident.der).hexdigest()), store_factory=factory)
    assert len(pins) == 1
    assert not info["ltv"] and info["ltv_note"] == pades.LTV_NOT_RECORDED
    report = pades.validate_signatures(signed, trust_check=_trusted)[0]
    assert report.intact and report.valid and report.covers_whole_file


def test_appearance_shows_the_signature_time(identity, store_factory):
    """La date du cadre visible est celle de la signature (/M), à la seconde."""
    import re
    from datetime import datetime

    box = (300, 650, 540, 730)
    signed, _ = pades.sign_pdf(
        _sample_pdf(), pades.SignOptions(thumbprint=hashlib.sha1(identity.der).hexdigest(), appearance=pades.Appearance(1, box)),
        store_factory=store_factory,
    )
    words = fitz.open("pdf", signed)[1].get_text("words", clip=fitz.Rect(box))
    shown = re.search(r"(\d{4})\.(\d{2})\.(\d{2}) (\d{2}):(\d{2}):(\d{2})", " ".join(w[4] for w in words)).groups()
    signed_at = datetime.fromisoformat(pades.validate_signatures(signed, trust_check=_trusted)[0].signed_at)
    assert tuple(int(v) for v in shown) == signed_at.timetuple()[:6]


@pytest.mark.parametrize("anchor", ["racine", "intermediaire"])
def test_acrobat_pkcs7_revocation_archive_counts_as_ltv(anchor):
    """Format PKCS#7 d'Acrobat : l'état de révocation est archivé dans la signature
    (adbe-revocationInfoArchival), sans DSS ; DestriPDF la reconnaît « LTV ». Avec
    l'autorité émettrice pour ancre (liste de confiance européenne), Acrobat
    n'archive que l'état du certificat du signataire : c'est encore « LTV »."""
    import io

    from asn1crypto import keys
    from asn1crypto import x509 as asn1_x509
    from cryptography.hazmat.primitives import serialization
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign import fields, signers
    from pyhanko_certvalidator import ValidationContext
    from pyhanko_certvalidator.registry import SimpleCertificateStore

    crls: dict[str, bytes] = {}
    responder: dict = {}
    with _authority(crls, responder) as (base, _hits):
        # Comme CertEurope : état du signataire par OCSP, signé par l'autorité émettrice.
        ident = make_test_pki(crl_base=base, ocsp=anchor == "intermediaire")
        crls.update(ident.crls)
        responder["identite"] = ident
        chain = [asn1_x509.Certificate.load(der) for der in ident.chain_ders]
        key = keys.PrivateKeyInfo.load(ident.key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        acrobat_like = signers.SimpleSigner(signing_cert=chain[0], signing_key=key, cert_registry=SimpleCertificateStore.from_certs(chain[1:]))
        trust_anchor = chain[-1] if anchor == "racine" else chain[1]
        meta = signers.PdfSignatureMetadata(
            field_name="Signature1", subfilter=fields.SigSeedSubFilter.ADOBE_PKCS7_DETACHED, embed_validation_info=True,
            validation_context=ValidationContext(trust_roots=[trust_anchor], allow_fetching=True, revocation_mode="hard-fail"),
        )
        signed = signers.sign_pdf(IncrementalPdfFileWriter(io.BytesIO(_sample_pdf())), meta, signer=acrobat_like).getvalue()
    assert b"/DSS" not in signed
    archived_crls, archived_ocsps = pades._archived_revocation(PdfFileReader(io.BytesIO(signed)).embedded_signatures[0])
    if anchor == "racine":
        assert len(archived_crls) == 2  # chaîne complète
    else:
        assert not archived_crls and len(archived_ocsps) == 1  # signataire seul, comme Acrobat
    report = pades.validate_signatures(signed, trust_check=_trusted)[0]
    assert report.status == "valid" and report.ltv, report.summary


def test_revoked_message_names_the_right_certificate(identity):
    from types import SimpleNamespace

    from asn1crypto import x509 as asn1_x509

    signer = asn1_x509.Certificate.load(identity.der)
    root = asn1_x509.Certificate.load(identity.chain_ders[-1])

    def revoked(leaf, ee):
        return SimpleNamespace(original_path=SimpleNamespace(leaf=leaf), is_ee_cert=ee)

    assert "Votre certificat est révoqué" in pades._revoked_message(revoked(signer, True), signer)
    assert "autorité qui a émis" in pades._revoked_message(revoked(signer, False), signer)
    assert "horodatage" in pades._revoked_message(revoked(root, True), signer)


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
def _authority(crls: dict[str, bytes], responder: dict | None = None):
    """Autorité simulée : publie ses listes de révocation sur un serveur local, et
    répond en OCSP pour l'identité placée dans `responder["identite"]`."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    hits: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            hits.append("ocsp")
            if responder is None or "identite" not in responder:
                self.send_error(404)
                return
            answer = ocsp_good_response(responder["identite"], body)
            self.send_response(200)
            self.send_header("Content-Type", "application/ocsp-response")
            self.send_header("Content-Length", str(len(answer)))
            self.end_headers()
            self.wfile.write(answer)

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
