"""PKI de test : autorité racine, intermédiaire et certificats de signataire (RSA, EC)."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID, ObjectIdentifier

PFX_PASSWORD = "test-destripdf"

# qcStatements : QcCompliance (0.4.0.1862.1.1) et QcSSCD (0.4.0.1862.1.4)
_QC_STATEMENTS_DER = bytes.fromhex("3014" "3008" "060604008e460101" "3008" "060604008e460104")


@dataclass
class TestIdentity:
    cert: x509.Certificate
    key: object
    chain: list[x509.Certificate]
    pfx: bytes

    @property
    def der(self) -> bytes:
        return self.cert.public_bytes(serialization.Encoding.DER)

    @property
    def chain_ders(self) -> list[bytes]:
        return [c.public_bytes(serialization.Encoding.DER) for c in self.chain]


def _name(cn: str, org: str = "Menuiserie Destribois (test)") -> x509.Name:
    return x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "FR"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, org),
        x509.NameAttribute(NameOID.COMMON_NAME, cn),
    ])


def _builder(subject, issuer, public_key, *, days=365, ca=False):
    now = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)
    return (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(public_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + dt.timedelta(days=days))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(public_key), critical=False)
    )


def make_test_pki(*, ec_key: bool = False, qualified: bool = True) -> TestIdentity:
    root_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    root_name = _name("Racine de test DestriPDF", "Autorité de test")
    root = (
        _builder(root_name, root_name, root_key.public_key(), days=3650, ca=True)
        .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
        .sign(root_key, hashes.SHA256())
    )
    inter_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    inter_name = _name("Intermédiaire de test DestriPDF", "Autorité de test")
    inter = (
        _builder(inter_name, root_name, inter_key.public_key(), days=1825, ca=True)
        .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(root_key.public_key()), critical=False)
        .sign(root_key, hashes.SHA256())
    )
    if ec_key:
        key = ec.generate_private_key(ec.SECP256R1())
    else:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    builder = (
        _builder(_name("Florent TEST"), inter_name, key.public_key(), days=365)
        .add_extension(x509.KeyUsage(True, True, False, False, False, False, False, False, False), critical=True)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(inter_key.public_key()), critical=False)
    )
    if qualified:
        builder = builder.add_extension(
            x509.UnrecognizedExtension(ObjectIdentifier("1.3.6.1.5.5.7.1.3"), _QC_STATEMENTS_DER), critical=False
        )
    cert = builder.sign(inter_key, hashes.SHA256())
    pfx = pkcs12.serialize_key_and_certificates(
        b"destripdf-test",
        key,
        cert,
        [inter, root],
        serialization.BestAvailableEncryption(PFX_PASSWORD.encode()),
    )
    return TestIdentity(cert=cert, key=key, chain=[cert, inter, root], pfx=pfx)
