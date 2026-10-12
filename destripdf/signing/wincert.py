"""Magasin de certificats Windows et signature par la clé (CryptoAPI et CNG).

Aucune dépendance tierce : ctypes sur crypt32, ncrypt et advapi32. La clé privée
ne quitte jamais son fournisseur (clé USB, carte à puce ou magasin logiciel) :
on lui confie une empreinte, il rend la signature brute. La saisie du code PIN
appartient au fournisseur de la clé, qui affiche sa propre fenêtre.
"""

from __future__ import annotations

import ctypes
import hashlib
import sys
from ctypes import wintypes
from dataclasses import dataclass, field
from datetime import datetime, timezone

if sys.platform != "win32":  # pragma: no cover - l'application cible Windows
    raise ImportError("Le magasin de certificats Windows n'existe que sous Windows.")

from asn1crypto import algos, x509

crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
ncrypt = ctypes.WinDLL("ncrypt", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)

# --- Constantes -------------------------------------------------------------

X509_ASN_ENCODING = 0x00000001
PKCS_7_ASN_ENCODING = 0x00010000
ENCODING = X509_ASN_ENCODING | PKCS_7_ASN_ENCODING

CERT_STORE_PROV_MEMORY = 2
CERT_STORE_PROV_SYSTEM_W = 10
CERT_SYSTEM_STORE_CURRENT_USER = 0x00010000
CERT_STORE_READONLY_FLAG = 0x00008000
CERT_STORE_OPEN_EXISTING_FLAG = 0x00004000
CERT_STORE_ADD_ALWAYS = 4

CERT_KEY_PROV_INFO_PROP_ID = 2
CERT_KEY_CONTEXT_PROP_ID = 5
CERT_FRIENDLY_NAME_PROP_ID = 11
CERT_NCRYPT_KEY_HANDLE_PROP_ID = 78

CRYPT_ACQUIRE_CACHE_FLAG = 0x00000001
CRYPT_ACQUIRE_WINDOW_HANDLE_FLAG = 0x00000080
CRYPT_ACQUIRE_PREFER_NCRYPT_KEY_FLAG = 0x00020000
CERT_NCRYPT_KEY_SPEC = 0xFFFFFFFF

PKCS12_ALWAYS_CNG_KSP = 0x00000200
PKCS12_NO_PERSIST_KEY = 0x00008000

BCRYPT_PAD_PKCS1 = 0x00000002
HP_HASHVAL = 2
CALG = {"sha1": 0x8004, "sha256": 0x800C, "sha384": 0x800D, "sha512": 0x800E}
BCRYPT_ALG = {"sha1": "SHA1", "sha256": "SHA256", "sha384": "SHA384", "sha512": "SHA512"}

CERT_CHAIN_CACHE_ONLY_URL_RETRIEVAL = 0x80000000

CERT_TRUST_IS_NOT_TIME_VALID = 0x00000001
CERT_TRUST_IS_REVOKED = 0x00000004
CERT_TRUST_IS_NOT_SIGNATURE_VALID = 0x00000008
CERT_TRUST_IS_UNTRUSTED_ROOT = 0x00000020
CERT_TRUST_IS_PARTIAL_CHAIN = 0x00010000

# Fournisseurs qui désignent une clé matérielle (clé USB, carte à puce).
_HARDWARE_HINTS = (
    "smart card", "smartcard", "carte", "safenet", "etoken", "idprime", "gemalto",
    "thales", "athena", "oberthur", "idemia", "bit4id", "certinomis", "chambersign",
    "certigna", "certeurope", "keynectis", "opentrust", "token", "minidriver",
    "aladdin", "cryptovision", "nexus", "yubikey", "piv",
)

# OID ETSI (0.4.0.1862.1.1 QcCompliance, 0.4.0.1862.1.4 QcSSCD), encodés en DER.
_QC_COMPLIANCE = bytes.fromhex("060604008e460101")
_QC_SSCD = bytes.fromhex("060604008e460104")

# --- Structures --------------------------------------------------------------


class CRYPT_DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


class CERT_CONTEXT(ctypes.Structure):
    _fields_ = [
        ("dwCertEncodingType", wintypes.DWORD),
        ("pbCertEncoded", ctypes.POINTER(ctypes.c_ubyte)),
        ("cbCertEncoded", wintypes.DWORD),
        ("pCertInfo", ctypes.c_void_p),
        ("hCertStore", ctypes.c_void_p),
    ]


PCCERT_CONTEXT = ctypes.POINTER(CERT_CONTEXT)


class CRYPT_KEY_PROV_INFO(ctypes.Structure):
    _fields_ = [
        ("pwszContainerName", wintypes.LPWSTR),
        ("pwszProvName", wintypes.LPWSTR),
        ("dwProvType", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("cProvParam", wintypes.DWORD),
        ("rgProvParam", ctypes.c_void_p),
        ("dwKeySpec", wintypes.DWORD),
    ]


class BCRYPT_PKCS1_PADDING_INFO(ctypes.Structure):
    _fields_ = [("pszAlgId", wintypes.LPCWSTR)]


class CERT_TRUST_STATUS(ctypes.Structure):
    _fields_ = [("dwErrorStatus", wintypes.DWORD), ("dwInfoStatus", wintypes.DWORD)]


class CERT_CHAIN_ELEMENT(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("pCertContext", PCCERT_CONTEXT),
        ("TrustStatus", CERT_TRUST_STATUS),
        ("pRevocationInfo", ctypes.c_void_p),
        ("pIssuanceUsage", ctypes.c_void_p),
        ("pApplicationUsage", ctypes.c_void_p),
        ("pwszExtendedErrorInfo", wintypes.LPCWSTR),
    ]


class CERT_SIMPLE_CHAIN(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("TrustStatus", CERT_TRUST_STATUS),
        ("cElement", wintypes.DWORD),
        ("rgpElement", ctypes.POINTER(ctypes.POINTER(CERT_CHAIN_ELEMENT))),
        ("pTrustListInfo", ctypes.c_void_p),
        ("fHasRevocationFreshnessTime", wintypes.BOOL),
        ("dwRevocationFreshnessTime", wintypes.DWORD),
    ]


class CERT_CHAIN_CONTEXT(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("TrustStatus", CERT_TRUST_STATUS),
        ("cChain", wintypes.DWORD),
        ("rgpChain", ctypes.POINTER(ctypes.POINTER(CERT_SIMPLE_CHAIN))),
        ("cLowerQualityChainContext", wintypes.DWORD),
        ("rgpLowerQualityChainContext", ctypes.c_void_p),
        ("fHasRevocationFreshnessTime", wintypes.BOOL),
        ("dwRevocationFreshnessTime", wintypes.DWORD),
        ("dwCreateFlags", wintypes.DWORD),
        ("ChainId", ctypes.c_ubyte * 16),
    ]


PCCERT_CHAIN_CONTEXT = ctypes.POINTER(CERT_CHAIN_CONTEXT)


class CTL_USAGE(ctypes.Structure):
    _fields_ = [("cUsageIdentifier", wintypes.DWORD), ("rgpszUsageIdentifier", ctypes.c_void_p)]


class CERT_USAGE_MATCH(ctypes.Structure):
    _fields_ = [("dwType", wintypes.DWORD), ("Usage", CTL_USAGE)]


class CERT_CHAIN_PARA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("RequestedUsage", CERT_USAGE_MATCH),
        ("RequestedIssuancePolicy", CERT_USAGE_MATCH),
        ("dwUrlRetrievalTimeout", wintypes.DWORD),
        ("fCheckRevocationFreshnessTime", wintypes.BOOL),
        ("dwRevocationFreshnessTime", wintypes.DWORD),
        ("pftCacheResync", ctypes.c_void_p),
    ]


# --- Prototypes --------------------------------------------------------------

crypt32.CertOpenStore.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
crypt32.CertOpenStore.restype = ctypes.c_void_p
crypt32.CertCloseStore.argtypes = [ctypes.c_void_p, wintypes.DWORD]
crypt32.CertCloseStore.restype = wintypes.BOOL
crypt32.CertEnumCertificatesInStore.argtypes = [ctypes.c_void_p, PCCERT_CONTEXT]
crypt32.CertEnumCertificatesInStore.restype = PCCERT_CONTEXT
crypt32.CertDuplicateCertificateContext.argtypes = [PCCERT_CONTEXT]
crypt32.CertDuplicateCertificateContext.restype = PCCERT_CONTEXT
crypt32.CertFreeCertificateContext.argtypes = [PCCERT_CONTEXT]
crypt32.CertFreeCertificateContext.restype = wintypes.BOOL
crypt32.CertGetCertificateContextProperty.argtypes = [PCCERT_CONTEXT, wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
crypt32.CertGetCertificateContextProperty.restype = wintypes.BOOL
crypt32.CryptAcquireCertificatePrivateKey.argtypes = [
    PCCERT_CONTEXT, wintypes.DWORD, ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.BOOL),
]
crypt32.CryptAcquireCertificatePrivateKey.restype = wintypes.BOOL
crypt32.PFXImportCertStore.argtypes = [ctypes.POINTER(CRYPT_DATA_BLOB), wintypes.LPCWSTR, wintypes.DWORD]
crypt32.PFXImportCertStore.restype = ctypes.c_void_p
crypt32.CertGetCertificateChain.argtypes = [
    ctypes.c_void_p, PCCERT_CONTEXT, ctypes.c_void_p, ctypes.c_void_p,
    ctypes.POINTER(CERT_CHAIN_PARA), wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(PCCERT_CHAIN_CONTEXT),
]
crypt32.CertGetCertificateChain.restype = wintypes.BOOL
crypt32.CertFreeCertificateChain.argtypes = [PCCERT_CHAIN_CONTEXT]
crypt32.CertFreeCertificateChain.restype = None
crypt32.CertAddEncodedCertificateToStore.argtypes = [
    ctypes.c_void_p, wintypes.DWORD, ctypes.c_char_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(PCCERT_CONTEXT),
]
crypt32.CertAddEncodedCertificateToStore.restype = wintypes.BOOL

ncrypt.NCryptSignHash.argtypes = [
    ctypes.c_size_t, ctypes.c_void_p, ctypes.c_char_p, wintypes.DWORD,
    ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.DWORD,
]
ncrypt.NCryptSignHash.restype = ctypes.c_long
ncrypt.NCryptFreeObject.argtypes = [ctypes.c_size_t]
ncrypt.NCryptFreeObject.restype = ctypes.c_long

advapi32.CryptCreateHash.argtypes = [ctypes.c_size_t, ctypes.c_uint, ctypes.c_size_t, wintypes.DWORD, ctypes.POINTER(ctypes.c_size_t)]
advapi32.CryptCreateHash.restype = wintypes.BOOL
advapi32.CryptSetHashParam.argtypes = [ctypes.c_size_t, wintypes.DWORD, ctypes.c_char_p, wintypes.DWORD]
advapi32.CryptSetHashParam.restype = wintypes.BOOL
advapi32.CryptSignHashW.argtypes = [ctypes.c_size_t, wintypes.DWORD, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
advapi32.CryptSignHashW.restype = wintypes.BOOL
advapi32.CryptDestroyHash.argtypes = [ctypes.c_size_t]
advapi32.CryptDestroyHash.restype = wintypes.BOOL
advapi32.CryptReleaseContext.argtypes = [ctypes.c_size_t, wintypes.DWORD]
advapi32.CryptReleaseContext.restype = wintypes.BOOL

user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD

# --- Erreurs -----------------------------------------------------------------

_MESSAGES = {
    0x8010006E: ("cancelled", "Signature annulée : la saisie du code PIN a été interrompue."),
    0x800704C7: ("cancelled", "Signature annulée."),
    0x80090036: ("cancelled", "Signature annulée."),
    0x8010006B: ("wrong_pin", "Code PIN incorrect. Vérifiez le code de votre clé puis recommencez."),
    0x8010006C: ("pin_blocked", "Code PIN bloqué : débloquez la clé avec le logiciel de votre autorité de certification."),
    0x8010000C: ("no_card", "Aucune clé détectée : branchez votre clé de signature puis recommencez."),
    0x80100069: ("card_removed", "La clé a été retirée pendant la signature : rebranchez-la puis recommencez."),
    0x80100066: ("card_unresponsive", "La clé ne répond pas : débranchez-la, rebranchez-la puis recommencez."),
    0x8010001D: ("no_service", "Le service Windows « Carte à puce » est arrêté."),
    0x8010001E: ("no_service", "Le service Windows « Carte à puce » est arrêté."),
    0x80090016: ("no_key", "Clé privée introuvable : branchez la clé qui porte ce certificat."),
    0x8009000D: ("no_key", "Clé privée introuvable : branchez la clé qui porte ce certificat."),
    0x80092004: ("no_key", "Ce certificat n'a pas de clé privée sur ce poste."),
    0x80090008: ("bad_algorithm", "La clé refuse l'algorithme SHA-256 demandé."),
    0x80090029: ("not_supported", "La clé ne prend pas en charge cette opération."),
    0x80090030: ("device_not_ready", "La clé n'est pas prête : patientez quelques secondes puis recommencez."),
}


class WinCertError(Exception):
    """Erreur du magasin ou du fournisseur de clé, avec un message pour l'utilisateur."""

    def __init__(self, message: str, code: str = "error", status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status


def _error(status: int, action: str) -> WinCertError:
    status &= 0xFFFFFFFF
    code, message = _MESSAGES.get(status, ("error", f"{action} impossible (code 0x{status:08X})."))
    return WinCertError(message, code=code, status=status)


def _last_error_status() -> int:
    err = ctypes.get_last_error()
    if err and not err & 0x80000000:
        err = 0x80070000 | (err & 0xFFFF)  # HRESULT_FROM_WIN32
    return err


# --- Certificats -------------------------------------------------------------


@dataclass
class CertificateEntry:
    """Description d'un certificat, sans aucune donnée secrète."""

    thumbprint: str
    der: bytes = field(repr=False)
    subject_cn: str
    subject_o: str
    email: str
    issuer_cn: str
    issuer_o: str
    not_before: datetime
    not_after: datetime
    key_usage: list[str]
    has_private_key: bool
    provider: str
    hardware: bool
    qualified: bool
    sscd: bool
    self_signed: bool
    key_algorithm: str
    key_size: int

    @property
    def expired(self) -> bool:
        return datetime.now(timezone.utc) > self.not_after

    @property
    def not_yet_valid(self) -> bool:
        return datetime.now(timezone.utc) < self.not_before

    @property
    def can_sign(self) -> bool:
        usage_ok = not self.key_usage or bool({"digital_signature", "non_repudiation"} & set(self.key_usage))
        return self.has_private_key and usage_ok and not self.expired and not self.not_yet_valid

    def score(self) -> tuple:
        """Ordre de préférence : signature qualifiée sur clé matérielle d'abord."""
        return (
            self.can_sign,
            "non_repudiation" in self.key_usage,
            self.qualified,
            self.hardware,
            not self.self_signed,
            self.not_after,
        )

    def to_json(self) -> dict:
        return {
            "id": self.thumbprint,
            "subject": self.subject_cn or self.email or self.thumbprint[:16],
            "organization": self.subject_o,
            "email": self.email,
            "issuer": self.issuer_cn or self.issuer_o,
            "issuer_organization": self.issuer_o,
            "not_before": self.not_before.isoformat(),
            "not_after": self.not_after.isoformat(),
            "expired": self.expired,
            "not_yet_valid": self.not_yet_valid,
            "can_sign": self.can_sign,
            "has_private_key": self.has_private_key,
            "provider": self.provider,
            "hardware": self.hardware,
            "qualified": self.qualified,
            "sscd": self.sscd,
            "self_signed": self.self_signed,
            "non_repudiation": "non_repudiation" in self.key_usage,
            "key_algorithm": self.key_algorithm,
            "key_size": self.key_size,
        }


def _name_part(name: x509.Name, key: str) -> str:
    try:
        value = name.native.get(key, "")
    except Exception:  # noqa: BLE001 - nom mal formé : on l'ignore
        return ""
    if isinstance(value, list):
        value = ", ".join(str(v) for v in value)
    return str(value or "")


def parse_certificate(der: bytes, *, has_private_key: bool = False, provider: str = "") -> CertificateEntry:
    cert = x509.Certificate.load(der)
    tbs = cert["tbs_certificate"]
    subject, issuer = cert.subject, cert.issuer
    try:
        key_usage = sorted(cert.key_usage_value.native) if cert.key_usage_value else []
    except Exception:  # noqa: BLE001
        key_usage = []
    qualified = sscd = False
    for ext in tbs["extensions"]:
        if ext["extn_id"].dotted == "1.3.6.1.5.5.7.1.3":
            raw = ext["extn_value"].contents
            qualified = _QC_COMPLIANCE in raw
            sscd = _QC_SSCD in raw
    try:
        public_key = cert.public_key
        algo = public_key.algorithm
        size = public_key.bit_size
    except Exception:  # noqa: BLE001
        algo, size = "inconnu", 0
    provider_lower = provider.lower()
    return CertificateEntry(
        thumbprint=hashlib.sha1(der).hexdigest().upper(),
        der=der,
        subject_cn=_name_part(subject, "common_name"),
        subject_o=_name_part(subject, "organization_name"),
        email=_name_part(subject, "email_address"),
        issuer_cn=_name_part(issuer, "common_name"),
        issuer_o=_name_part(issuer, "organization_name"),
        not_before=tbs["validity"]["not_before"].native,
        not_after=tbs["validity"]["not_after"].native,
        key_usage=key_usage,
        has_private_key=has_private_key,
        provider=provider,
        hardware=any(hint in provider_lower for hint in _HARDWARE_HINTS),
        qualified=qualified,
        sscd=sscd,
        self_signed=subject == issuer,
        key_algorithm=algo,
        key_size=size,
    )


def _context_der(ctx: PCCERT_CONTEXT) -> bytes:
    c = ctx.contents
    return ctypes.string_at(c.pbCertEncoded, c.cbCertEncoded)


def _property_size(ctx: PCCERT_CONTEXT, prop_id: int) -> int:
    size = wintypes.DWORD(0)
    if crypt32.CertGetCertificateContextProperty(ctx, prop_id, None, ctypes.byref(size)):
        return size.value
    return 0


def _key_provider(ctx: PCCERT_CONTEXT) -> tuple[bool, str]:
    """Indique si une clé privée est associée, et le nom de son fournisseur."""
    size = _property_size(ctx, CERT_KEY_PROV_INFO_PROP_ID)
    if size:
        buf = ctypes.create_string_buffer(size)
        cb = wintypes.DWORD(size)
        if crypt32.CertGetCertificateContextProperty(ctx, CERT_KEY_PROV_INFO_PROP_ID, buf, ctypes.byref(cb)):
            info = ctypes.cast(buf, ctypes.POINTER(CRYPT_KEY_PROV_INFO)).contents
            return True, info.pwszProvName or ""
    if _property_size(ctx, CERT_NCRYPT_KEY_HANDLE_PROP_ID) or _property_size(ctx, CERT_KEY_CONTEXT_PROP_ID):
        return True, "Clé en mémoire"
    return False, ""


def foreground_window_of_this_process() -> int | None:
    """Fenêtre au premier plan si elle appartient à l'application (parent du PIN)."""
    import os

    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(hwnd) if pid.value == os.getpid() else None


@dataclass
class ChainResult:
    ders: list[bytes]
    error_status: int

    @property
    def trusted(self) -> bool:
        return self.error_status == 0

    def describe(self) -> str:
        if self.error_status == 0:
            return "Chaîne de certification approuvée par Windows."
        parts = []
        if self.error_status & CERT_TRUST_IS_UNTRUSTED_ROOT:
            parts.append("autorité racine non approuvée")
        if self.error_status & CERT_TRUST_IS_PARTIAL_CHAIN:
            parts.append("chaîne incomplète")
        if self.error_status & CERT_TRUST_IS_NOT_TIME_VALID:
            parts.append("certificat hors de sa période de validité")
        if self.error_status & CERT_TRUST_IS_REVOKED:
            parts.append("certificat révoqué")
        if self.error_status & CERT_TRUST_IS_NOT_SIGNATURE_VALID:
            parts.append("signature de certificat invalide")
        if not parts:
            parts.append(f"anomalie 0x{self.error_status:08X}")
        return "Chaîne de certification : " + ", ".join(parts) + "."


class CertStore:
    """Magasin de certificats (magasin système « MY » ou magasin mémoire d'un PFX)."""

    def __init__(self, handle: int, label: str):
        if not handle:
            raise WinCertError(f"Ouverture du magasin {label} impossible.", status=_last_error_status())
        self._handle = handle
        self.label = label

    @classmethod
    def system(cls, name: str = "MY") -> "CertStore":
        flags = CERT_SYSTEM_STORE_CURRENT_USER | CERT_STORE_READONLY_FLAG | CERT_STORE_OPEN_EXISTING_FLAG
        handle = crypt32.CertOpenStore(CERT_STORE_PROV_SYSTEM_W, 0, None, flags, ctypes.c_wchar_p(name))
        return cls(handle, f"Windows/{name}")

    @classmethod
    def from_pfx(cls, data: bytes, password: str) -> "CertStore":
        """Importe un PFX en mémoire, clé non persistée : réservé aux tests et aux PFX."""
        buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        blob = CRYPT_DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
        handle = crypt32.PFXImportCertStore(ctypes.byref(blob), password, PKCS12_ALWAYS_CNG_KSP | PKCS12_NO_PERSIST_KEY)
        if not handle:
            raise _error(_last_error_status(), "Import du certificat")
        return cls(handle, "PFX")

    @classmethod
    def from_ders(cls, ders: list[bytes]) -> "CertStore":
        """Magasin mémoire de certificats seuls (chaîne lue dans une signature)."""
        handle = crypt32.CertOpenStore(CERT_STORE_PROV_MEMORY, 0, None, 0, None)
        store = cls(handle, "mémoire")
        for der in ders:
            crypt32.CertAddEncodedCertificateToStore(handle, ENCODING, der, len(der), CERT_STORE_ADD_ALWAYS, None)
        return store

    def close(self) -> None:
        if self._handle:
            crypt32.CertCloseStore(self._handle, 0)
            self._handle = None

    def __enter__(self) -> "CertStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __del__(self):  # pragma: no cover - filet de sécurité
        try:
            self.close()
        except Exception:  # noqa: BLE001
            pass

    def _contexts(self):
        ctx = crypt32.CertEnumCertificatesInStore(self._handle, None)
        try:
            while ctx:
                yield ctx
                ctx = crypt32.CertEnumCertificatesInStore(self._handle, ctx)
        finally:
            if ctx:  # énumération interrompue : libérer le contexte courant
                crypt32.CertFreeCertificateContext(ctx)

    def certificates(self) -> list[CertificateEntry]:
        entries: list[CertificateEntry] = []
        for ctx in self._contexts():
            try:
                has_key, provider = _key_provider(ctx)
                entries.append(parse_certificate(_context_der(ctx), has_private_key=has_key, provider=provider))
            except Exception:  # noqa: BLE001 - un certificat illisible n'empêche pas les autres
                continue
        entries.sort(key=lambda e: e.score(), reverse=True)
        return entries

    def _find(self, thumbprint: str) -> PCCERT_CONTEXT:
        wanted = thumbprint.upper()
        for ctx in self._contexts():
            if hashlib.sha1(_context_der(ctx)).hexdigest().upper() == wanted:
                return crypt32.CertDuplicateCertificateContext(ctx)
        raise WinCertError("Certificat introuvable : la clé a peut-être été débranchée.", code="not_found")

    def entry(self, thumbprint: str) -> CertificateEntry:
        ctx = self._find(thumbprint)
        try:
            has_key, provider = _key_provider(ctx)
            return parse_certificate(_context_der(ctx), has_private_key=has_key, provider=provider)
        finally:
            crypt32.CertFreeCertificateContext(ctx)

    def chain(self, thumbprint: str, *, allow_network: bool = False, timeout_ms: int = 6000) -> ChainResult:
        ctx = self._find(thumbprint)
        try:
            return _build_chain(ctx, ctx.contents.hCertStore, allow_network=allow_network, timeout_ms=timeout_ms)
        finally:
            crypt32.CertFreeCertificateContext(ctx)

    def sign_digest(self, thumbprint: str, digest: bytes, hash_name: str, *, hwnd: int | None = None) -> bytes:
        """Signe une empreinte avec la clé du certificat. Renvoie la signature brute.

        RSA : PKCS#1 v1.5 (octets gros-boutistes). ECDSA : structure DER
        ECDSA-Sig-Value, attendue par CMS.
        """
        hash_name = hash_name.lower()
        if hash_name not in CALG:
            raise WinCertError(f"Algorithme d'empreinte non pris en charge : {hash_name}.", code="bad_algorithm")
        ctx = self._find(thumbprint)
        try:
            entry = parse_certificate(_context_der(ctx))
            return _sign_with_context(ctx, digest, hash_name, entry.key_algorithm, hwnd)
        finally:
            crypt32.CertFreeCertificateContext(ctx)


def _build_chain(ctx: PCCERT_CONTEXT, extra_store, *, allow_network: bool, timeout_ms: int) -> ChainResult:
    para = CERT_CHAIN_PARA()
    para.cbSize = ctypes.sizeof(CERT_CHAIN_PARA)
    para.dwUrlRetrievalTimeout = timeout_ms
    flags = 0 if allow_network else CERT_CHAIN_CACHE_ONLY_URL_RETRIEVAL
    chain = PCCERT_CHAIN_CONTEXT()
    if not crypt32.CertGetCertificateChain(None, ctx, None, extra_store, ctypes.byref(para), flags, None, ctypes.byref(chain)):
        raise _error(_last_error_status(), "Construction de la chaîne de certification")
    try:
        cc = chain.contents
        ders: list[bytes] = []
        if cc.cChain:
            simple = cc.rgpChain[0].contents
            for i in range(simple.cElement):
                element = simple.rgpElement[i].contents
                ders.append(_context_der(element.pCertContext))
        return ChainResult(ders=ders, error_status=cc.TrustStatus.dwErrorStatus)
    finally:
        crypt32.CertFreeCertificateChain(chain)


def chain_for_certificates(ders: list[bytes], *, allow_network: bool = False) -> ChainResult:
    """Construit par Windows la chaîne du premier certificat, les autres servant d'aides."""
    if not ders:
        return ChainResult([], CERT_TRUST_IS_PARTIAL_CHAIN)
    with CertStore.from_ders(ders) as store:
        thumb = hashlib.sha1(ders[0]).hexdigest().upper()
        return store.chain(thumb, allow_network=allow_network)


def trusted_root_ders() -> list[bytes]:
    """Autorités racines approuvées par Windows (magasin « ROOT » de l'utilisateur,
    qui inclut celles de l'ordinateur) : certificats publics, aucune clé."""
    try:
        with CertStore.system("ROOT") as store:
            return [_context_der(ctx) for ctx in store._contexts()]
    except WinCertError:
        return []


def _sign_with_context(ctx: PCCERT_CONTEXT, digest: bytes, hash_name: str, key_algorithm: str, hwnd: int | None) -> bytes:
    handle = ctypes.c_size_t(0)
    key_spec = wintypes.DWORD(0)
    must_free = wintypes.BOOL(False)
    # Le cache rattache la clé au contexte du certificat : indispensable pour une
    # clé importée en mémoire, sans effet de bord pour une clé de magasin (le
    # magasin est refermé après chaque signature).
    flags = CRYPT_ACQUIRE_PREFER_NCRYPT_KEY_FLAG | CRYPT_ACQUIRE_CACHE_FLAG
    hwnd_param = None
    if hwnd:
        hwnd_value = wintypes.HWND(hwnd)
        hwnd_param = ctypes.byref(hwnd_value)
        flags |= CRYPT_ACQUIRE_WINDOW_HANDLE_FLAG
    if not crypt32.CryptAcquireCertificatePrivateKey(
        ctx, flags, hwnd_param, ctypes.byref(handle), ctypes.byref(key_spec), ctypes.byref(must_free)
    ):
        raise _error(_last_error_status(), "Accès à la clé privée")
    try:
        if key_spec.value == CERT_NCRYPT_KEY_SPEC:
            return _ncrypt_sign(handle.value, digest, hash_name, key_algorithm)
        return _capi_sign(handle.value, key_spec.value, digest, hash_name)
    finally:
        if must_free.value:
            if key_spec.value == CERT_NCRYPT_KEY_SPEC:
                ncrypt.NCryptFreeObject(handle.value)
            else:
                advapi32.CryptReleaseContext(handle.value, 0)


def _ncrypt_sign(key: int, digest: bytes, hash_name: str, key_algorithm: str) -> bytes:
    rsa = key_algorithm == "rsa"
    padding = None
    flags = 0
    if rsa:
        info = BCRYPT_PKCS1_PADDING_INFO(BCRYPT_ALG[hash_name])
        padding = ctypes.byref(info)
        flags = BCRYPT_PAD_PKCS1
    size = wintypes.DWORD(0)
    status = ncrypt.NCryptSignHash(key, padding, digest, len(digest), None, 0, ctypes.byref(size), flags)
    if status:
        raise _error(status, "Signature")
    out = (ctypes.c_ubyte * size.value)()
    status = ncrypt.NCryptSignHash(key, padding, digest, len(digest), out, size.value, ctypes.byref(size), flags)
    if status:
        raise _error(status, "Signature")
    signature = bytes(out[: size.value])
    if not rsa:
        # CNG rend r || s (IEEE P1363) ; CMS attend la structure DER.
        signature = algos.DSASignature.from_p1363(signature).dump()
    return signature


def _capi_sign(prov: int, key_spec: int, digest: bytes, hash_name: str) -> bytes:
    hhash = ctypes.c_size_t(0)
    if not advapi32.CryptCreateHash(prov, CALG[hash_name], 0, 0, ctypes.byref(hhash)):
        raise _error(_last_error_status(), "Préparation de la signature")
    try:
        if not advapi32.CryptSetHashParam(hhash.value, HP_HASHVAL, digest, 0):
            raise _error(_last_error_status(), "Préparation de la signature")
        size = wintypes.DWORD(0)
        if not advapi32.CryptSignHashW(hhash.value, key_spec, None, 0, None, ctypes.byref(size)):
            raise _error(_last_error_status(), "Signature")
        out = (ctypes.c_ubyte * size.value)()
        if not advapi32.CryptSignHashW(hhash.value, key_spec, None, 0, out, ctypes.byref(size)):
            raise _error(_last_error_status(), "Signature")
        # CryptoAPI rend les octets en ordre petit-boutiste.
        return bytes(reversed(bytes(out[: size.value])))
    finally:
        advapi32.CryptDestroyHash(hhash.value)
