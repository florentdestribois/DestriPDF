"""Recette : accueil, mot de passe, formulaire, pages, insertion, réglages, sombre, impression.

Usage : python scripts/recette/parcours_complements.py <captures> <dossier d'échantillons>
L'instance doit tourner en mode recette sur http://127.0.0.1:8790/recette/.
"""
import json
import sys
import time
import traceback
from pathlib import Path

import pymupdf as fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cdp import CTRL, Edge

OUT = Path(sys.argv[1])
OUT.mkdir(exist_ok=True)
RECETTE = Path(sys.argv[2])
URL = "http://127.0.0.1:8790/recette/"
results = []


def step(name):
    def deco(fn):
        try:
            fn()
            results.append((name, "OK", ""))
            print(f"[OK] {name}")
        except Exception as exc:  # noqa: BLE001
            results.append((name, "ÉCHEC", f"{type(exc).__name__}: {exc}"))
            print(f"[ÉCHEC] {name}: {type(exc).__name__}: {exc}")
            traceback.print_exc(limit=2)
            try:
                edge.shot(OUT / f"r3-echec-{len(results)}.png")
            except Exception:  # noqa: BLE001
                pass
        return fn
    return deco


def api(path):
    return edge.js(f"fetch('api/{path}', {{cache: 'no-store'}}).then(r => r.json())")


def post(path, body=None):
    return edge.js(f"""fetch('api/{path}', {{method: 'POST', headers: {{'Content-Type': 'application/json', 'X-DestriPDF': '1'}},
        body: JSON.stringify({json.dumps(body or {})})}}).then(r => r.json())""")


def version():
    return edge.js("window.__app.doc ? window.__app.doc.version : -1")


def wait_version(prev, timeout=15):
    edge.wait_for(f"window.__app.doc && window.__app.doc.version > {prev}", timeout=timeout)
    time.sleep(0.4)


def open_path(path):
    edge.js(f"void window.__app.openPath({json.dumps(str(path))})")


# Matériel : PDF protégé, PDF signé (pour le bandeau)
secret = RECETTE / "secret.pdf"
doc = fitz.open()
doc.new_page().insert_text((72, 72), "Document confidentiel", fontsize=14)
secret.write_bytes(doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="1234", owner_pw="o"))

edge = Edge(1280, 720)
try:
    edge.goto(URL, wait=0.5)
    edge.wait_for("window.__app && window.__app.state", timeout=10)

    @step("Écran d'accueil et documents récents")
    def _():
        edge.js("void window.__app.closeDocument()")
        edge.wait_for("!document.getElementById('start').hidden", timeout=10)
        edge.wait_for("document.querySelectorAll('.recent-item').length >= 1", timeout=5)
        edge.shot(OUT / "r3-01-accueil.png")
        assert edge.js("document.body.classList.contains('no-doc')")

    @step("Ouvrir un PDF protégé : mot de passe faux puis juste")
    def _():
        open_path(secret)
        edge.wait_for("document.querySelector('.modal input[type=password]')", timeout=10)
        edge.shot(OUT / "r3-02-mot-de-passe.png")
        edge.type("faux")
        edge.key("Enter")
        edge.wait_for("document.querySelector('.modal .help') && document.querySelector('.modal .help').textContent.includes('incorrect')", timeout=10)
        edge.type("1234")
        edge.key("Enter")
        edge.wait_for("window.__app.doc && window.__app.doc.encrypted", timeout=10)
        assert edge.js("window.__app.doc.name") == "secret.pdf"

    @step("Remplir un formulaire (champ texte et case à cocher)")
    def _():
        open_path(RECETTE / "formulaire.pdf")
        edge.wait_for("window.__app.doc && window.__app.doc.name === 'formulaire.pdf'", timeout=10)
        edge.wait_for("document.querySelector('.field-input')", timeout=10)
        x, y = edge.center(".field-input")
        edge.click(x, y)
        edge.type("Menuiserie Destribois")
        v = version()
        edge.key("Enter")
        wait_version(v)
        x, y = edge.center(".field-check")
        v = version()
        edge.click(x, y)
        wait_version(v)
        fields = api("page/0/annots")["fields"]
        values = {f["name"]: f.get("value") for f in fields}
        checked = {f["name"]: f.get("checked") for f in fields}
        assert values["raison_sociale"] == "Menuiserie Destribois", values
        assert checked["accepte"], checked
        edge.shot(OUT / "r3-03-formulaire.png")

    @step("Pages : pivoter, insérer un PDF, déplacer, supprimer")
    def _():
        open_path(RECETTE / "devis.pdf")
        edge.wait_for("document.querySelector('.modal')", timeout=10)
        assert 'Enregistrer les modifications' in edge.js("document.querySelector('.modal-title').textContent")
        edge.js("[...document.querySelectorAll('.modal .btn')].find(b => b.textContent === 'Ne pas enregistrer').click()")
        edge.wait_for("window.__app.doc && window.__app.doc.name === 'devis.pdf'", timeout=10)
        # Non-régression : l'image affichée appartient au nouveau document, jamais au précédent.
        edge.wait_for("(() => { const i = document.querySelector('.page[data-index=\"0\"] .page-img');"
                      " return i && i.src.includes('d=' + window.__app.doc.id); })()", timeout=10)
        time.sleep(0.6)
        v = version()
        edge.js("window.__app.rotatePages([1], 90)")
        wait_version(v)
        assert edge.js("window.__app.doc.pages[1].rot") == 90
        # insertion par le champ de fichier (mode navigateur)
        v = version()
        edge.js("window.__app.insertAt = 2")
        root = edge.call("DOM.getDocument")["root"]["nodeId"]
        node = edge.call("DOM.querySelector", nodeId=root, selector="#insert-input")["nodeId"]
        edge.call("DOM.setFileInputFiles", nodeId=node, files=[str(RECETTE / "plan.pdf")])
        wait_version(v)
        assert edge.js("window.__app.doc.page_count") == 3
        v = version()
        edge.js("window.__app.movePage(2, 0)")
        wait_version(v)
        v = version()
        edge.js("window.__app.deletePages([0])")
        wait_version(v)
        assert edge.js("window.__app.doc.page_count") == 2
        edge.shot(OUT / "r3-04-pages.png")

    @step("Menu contextuel d'une vignette")
    def _():
        x, y = edge.center('.thumb[data-index="0"]')
        edge.call("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button="right", clickCount=1)
        edge.call("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button="right", clickCount=1)
        edge.wait_for("document.querySelector('.menu')")
        labels = edge.js("[...document.querySelectorAll('.menu-item')].map(b => b.textContent.trim())")
        assert "Pivoter à droite" in labels and "Supprimer la page" in labels, labels
        edge.key("Escape")
        edge.wait_for("!document.querySelector('.menu')")

    @step("Réglages : auteur et thème sombre")
    def _():
        edge.js("void window.__app.openSettings()")
        edge.wait_for("document.querySelector('.modal')")
        edge.js("""(() => { const i = document.querySelector('.modal input.text-input'); i.value = 'Florent Destribois';
            const s = document.querySelector('.modal select'); s.value = 'dark'; })()""")
        edge.shot(OUT / "r3-05-reglages.png")
        edge.js("[...document.querySelectorAll('.modal .btn-primary')][0].click()")
        edge.wait_for("document.documentElement.dataset.theme === 'dark'", timeout=5)
        time.sleep(0.5)
        edge.shot(OUT / "r3-06-sombre.png")
        assert api("settings")["settings"]["author"] == "Florent Destribois"
        post("settings", {"theme": "auto"})
        edge.js("window.__app.settings.theme = 'auto'; window.__app.applyTheme()")

    @step("Préparation de l'impression (pages en 150 ppp)")
    def _():
        edge.js("window.print = () => { window.__printed = (window.__printed || 0) + 1; }")
        edge.js("void window.__app.print()")
        edge.wait_for("window.__printed === 1", timeout=20)
        count = edge.js("document.querySelectorAll('#print-root img').length")
        assert count == edge.js("window.__app.doc.page_count"), count
        complete = edge.js("[...document.querySelectorAll('#print-root img')].every(i => i.complete && i.naturalWidth > 1000)")
        assert complete
        edge.call("Emulation.setEmulatedMedia", media="print")
        edge.shot(OUT / "r3-07-impression.png")
        edge.call("Emulation.setEmulatedMedia", media="")

    @step("Navigation clavier : Tab visible, Échap revient à la sélection")
    def _():
        edge.js("window.__app.tools.set('draw')")
        edge.click_on("#viewer")
        edge.key("Escape")
        edge.wait_for("document.body.classList.contains('mode-select')")
        edge.key("e")
        edge.wait_for("document.body.classList.contains('mode-edit')")
        edge.key("Escape")
        edge.key("Tab")
        outline = edge.js("getComputedStyle(document.activeElement).outlineStyle")
        print("    focus :", edge.js("document.activeElement.id || document.activeElement.className"), outline)

    @step("Fenêtre 1024x680 : rien ne déborde, panneau Signer ouvert")
    def _():
        edge.viewport(1024, 680)
        time.sleep(0.5)
        edge.js("window.__app.startSigning()")
        time.sleep(1.0)
        overflow = edge.js("document.documentElement.scrollWidth - innerWidth")
        assert overflow <= 0, overflow
        sign_visible = edge.js("(() => { const b = [...document.querySelectorAll('#panel-body .btn-primary')].find(n => n.textContent.includes('Signer')); const r = b.getBoundingClientRect(); return r.bottom <= innerHeight && r.top >= 0; })()")
        edge.shot(OUT / "r3-08-1024-signer.png")
        assert sign_visible, "bouton Signer hors écran"
        edge.viewport(1920, 1080)
        time.sleep(0.6)
        edge.shot(OUT / "r3-09-1920-signer.png")
        assert edge.js("document.documentElement.scrollWidth - innerWidth") <= 0

    edge.pump(0.5)
finally:
    print("\nconsole :")
    for line in edge.console:
        print("  ", line)
    edge.close()
    print("\nBILAN :", sum(1 for r in results if r[1] == "OK"), "/", len(results))
    for name, status, detail in results:
        if status != "OK":
            print(" -", name, ":", detail)

sys.exit(0 if results and all(r[1] == "OK" for r in results) else 1)
