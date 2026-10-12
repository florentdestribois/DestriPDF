"""Signature par le fournisseur de clés Windows (CNG), clé importée en mémoire."""

import hashlib

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding

from destripdf.signing import wincert
from tests.pki import PFX_PASSWORD, make_test_pki


@pytest.fixture(scope="module")
def rsa_identity():
    return make_test_pki()


def test_pfx_store_lists_signing_certificate_with_qualified_flags(rsa_identity):
    with wincert.CertStore.from_pfx(rsa_identity.pfx, PFX_PASSWORD) as store:
        entries = store.certificates()
    signer = [e for e in entries if e.has_private_key]
    assert len(signer) == 1
    entry = signer[0]
    assert entry.subject_cn == "Florent TEST"
    assert entry.issuer_cn == "Intermédiaire de test DestriPDF"
    assert entry.can_sign
    assert entry.qualified and entry.sscd
    assert "non_repudiation" in entry.key_usage
    assert entry.thumbprint == hashlib.sha1(rsa_identity.der).hexdigest().upper()
    assert entries[0].thumbprint == entry.thumbprint  # trié en premier
    data = entry.to_json()
    assert data["subject"] == "Florent TEST" and data["can_sign"] is True


def test_cng_rsa_signature_verifies(rsa_identity):
    digest = hashlib.sha256(b"DestriPDF").digest()
    thumb = hashlib.sha1(rsa_identity.der).hexdigest()
    with wincert.CertStore.from_pfx(rsa_identity.pfx, PFX_PASSWORD) as store:
        signature = store.sign_digest(thumb, digest, "sha256")
    rsa_identity.cert.public_key().verify(signature, b"DestriPDF", padding.PKCS1v15(), hashes.SHA256())


def test_cng_ecdsa_signature_is_der_and_verifies():
    identity = make_test_pki(ec_key=True)
    digest = hashlib.sha256(b"DestriPDF EC").digest()
    thumb = hashlib.sha1(identity.der).hexdigest()
    with wincert.CertStore.from_pfx(identity.pfx, PFX_PASSWORD) as store:
        signature = store.sign_digest(thumb, digest, "sha256")
    assert signature[0] == 0x30  # SEQUENCE DER
    identity.cert.public_key().verify(signature, b"DestriPDF EC", ec.ECDSA(hashes.SHA256()))


def test_chain_is_built_with_untrusted_test_root(rsa_identity):
    thumb = hashlib.sha1(rsa_identity.der).hexdigest()
    with wincert.CertStore.from_pfx(rsa_identity.pfx, PFX_PASSWORD) as store:
        result = store.chain(thumb)
    assert result.ders == rsa_identity.chain_ders
    assert not result.trusted
    assert result.error_status & wincert.CERT_TRUST_IS_UNTRUSTED_ROOT
    assert "racine non approuvée" in result.describe()


def test_chain_for_certificates_from_signature_material(rsa_identity):
    leaf, inter, root = rsa_identity.chain_ders
    result = wincert.chain_for_certificates([leaf, root, inter])
    assert result.ders == [leaf, inter, root]


def test_unknown_thumbprint_raises_clear_error(rsa_identity):
    with wincert.CertStore.from_pfx(rsa_identity.pfx, PFX_PASSWORD) as store:
        with pytest.raises(wincert.WinCertError) as err:
            store.sign_digest("00" * 20, b"\0" * 32, "sha256")
    assert err.value.code == "not_found"


def test_error_mapping_for_cancelled_pin():
    err = wincert._error(0x8010006E, "Signature")
    assert err.code == "cancelled" and "annulée" in str(err)
    err = wincert._error(-2146434962, "Signature")  # même code, signé
    assert err.code == "cancelled"
    err = wincert._error(0x80001234, "Signature")
    assert err.code == "error" and "0x80001234" in str(err)


def test_system_store_opens_read_only():
    with wincert.CertStore.system("MY") as store:
        assert isinstance(store.certificates(), list)
