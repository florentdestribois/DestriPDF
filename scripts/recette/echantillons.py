"""Matériel de recette : PDF d'essai, PFX de test, dossier de réglages isolé.

Usage : python scripts/recette/echantillons.py <dossier> [--crl-port N]
Avec --crl-port, le certificat de test déclare des listes de révocation publiées
sur http://127.0.0.1:N/ (fichiers écrits dans <dossier>/crl, servis par smoke.py).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pymupdf as fitz
from tests import samples
from tests.pki import PFX_PASSWORD, make_test_pki

root = Path(sys.argv[1])
root.mkdir(parents=True, exist_ok=True)
(root / "reglages").mkdir(exist_ok=True)
(root / "devis.pdf").write_bytes(samples.quote_pdf())
(root / "formulaire.pdf").write_bytes(samples.form_pdf())
(root / "plan.pdf").write_bytes(samples.rotated_pdf())

# Document de 12 pages avec un vrai paragraphe et des signets
doc = fitz.open(stream=samples.quote_pdf(), filetype="pdf")
for i in range(10):
    page = doc.new_page(width=595, height=842)
    samples.write(page, (56, 80), f"Chapitre {i + 1} — Conditions d'exécution", size=14, bold=True)
    y = 110
    for k in range(30):
        samples.write(page, (56, y), f"Ligne {k + 1} du chapitre {i + 1} : la menuiserie est posée selon le DTU 36.5 et les règles de l'art.", size=10)
        y += 14
doc.set_toc([[1, "Devis", 1], [1, "Conditions générales", 2], [1, "Chapitres", 3], [2, "Chapitre 1", 3], [2, "Chapitre 10", 12]])
(root / "dossier.pdf").write_bytes(doc.tobytes(garbage=3, deflate=True))

crl_port = int(sys.argv[sys.argv.index("--crl-port") + 1]) if "--crl-port" in sys.argv else None
identity = make_test_pki(crl_base=f"http://127.0.0.1:{crl_port}" if crl_port else None)
(root / "test.pfx").write_bytes(identity.pfx)
if crl_port:
    crl_dir = root / "crl"
    crl_dir.mkdir(exist_ok=True)
    (crl_dir / "port").write_text(str(crl_port), encoding="ascii")
    for name, data in identity.crls.items():
        (crl_dir / name).write_bytes(data)
print(root)
print("password", PFX_PASSWORD)
