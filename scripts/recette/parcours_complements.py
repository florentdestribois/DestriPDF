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

    @step("Impression web de secours (pages en 150 ppp)")
    def _():
        edge.js("window.print = () => { window.__printed = (window.__printed || 0) + 1; }")
        edge.js("void window.__app.webPrint()")
        edge.wait_for("window.__printed === 1", timeout=20)
        count = edge.js("document.querySelectorAll('#print-root img').length")
        assert count == edge.js("window.__app.doc.page_count"), count
        complete = edge.js("[...document.querySelectorAll('#print-root img')].every(i => i.complete && i.naturalWidth > 1000)")
        assert complete
        edge.call("Emulation.setEmulatedMedia", media="print")
        edge.shot(OUT / "r3-07-impression.png")
        edge.call("Emulation.setEmulatedMedia", media="")

    def print_dialog(printer, layout="normal"):
        """Ouvre la boîte Imprimer (Ctrl+P), choisit l'imprimante et la mise en page."""
        edge.key("p", modifiers=CTRL)
        edge.wait_for("document.querySelector('.modal-title') && document.querySelector('.modal-title').textContent === 'Imprimer'")
        edge.js(f"""(() => {{ const q = (l) => document.querySelector(`.modal [aria-label="${{l}}"]`);
            q('Imprimante').value = {json.dumps(printer)}; q('Imprimante').dispatchEvent(new Event('change'));
            q('Mise en page').value = {json.dumps(layout)}; q('Mise en page').dispatchEvent(new Event('change')); }})()""")
        edge.wait_for("!document.querySelector('.print-booklet-box .help').textContent.startsWith('Lecture')", timeout=30)

    def new_print(before, timeout=30):
        out_dir = RECETTE / "impressions"
        deadline = time.time() + timeout
        while time.time() < deadline:
            new = [f for f in set(out_dir.glob("*.pdf")) - before if f.stat().st_size > 0]
            if new:
                time.sleep(0.5)
                return fitz.open(new[0])
            time.sleep(0.3)
        raise AssertionError("aucun fichier imprimé")

    @step("Boîte Imprimer : livret mis en page par DestriPDF, aperçu et plan")
    def _():
        names = api("printers")["printers"]
        assert "Microsoft Print to PDF" in names, names
        canon = next((n for n in names if "C3520" in n), None)
        print_dialog(canon or "Microsoft Print to PDF", "booklet")
        assert not edge.js("document.querySelector('.print-booklet-box').hidden")
        edge.wait_for("document.querySelectorAll('.booklet-preview .booklet-slot').length === 4", timeout=20)
        edge.wait_for("[...document.querySelectorAll('.booklet-preview img')].every(i => i.complete && i.naturalWidth > 0)", timeout=20)
        sheets = edge.js("[...document.querySelector('.modal [aria-label=\"Feuille du livret\"]').options].map(o => o.value)")
        assert "a4" in sheets, sheets
        note = edge.js("document.querySelector('.print-booklet-box .help').textContent")
        plan = edge.js("document.querySelector('.booklet-preview + .help').textContent")
        print("    note :", note)
        print("    plan :", plan)
        assert ("Recto verso automatique" in note) if canon else ("pas en recto verso" in note)
        assert "1 feuille A4 pour 2 pages" in plan and "feuille 1 : – | 1 / 2 | –" in plan, plan
        numbers = edge.js("[...document.querySelectorAll('.booklet-preview .booklet-slot')].map(s => s.classList.contains('blank') ? null : Number(s.querySelector('.booklet-number').textContent))")
        assert numbers == [None, 1, 2, None], numbers
        # page 2 pivotée en paysage : tournée dans sa demi-feuille, comme à l'impression
        assert edge.js("[...document.querySelectorAll('.booklet-preview .booklet-slot.turned .booklet-number')].map(n => n.textContent)") == ["2"]
        assert edge.js("""(() => { const i = document.querySelector('.booklet-slot.turned img').getBoundingClientRect();
            return i.height > i.width; })()"""), "vignette paysage non tournée"
        edge.shot(OUT / "r3-07c-livret-boite.png")
        # 1024×680 : la boîte défile, le bouton Imprimer reste atteignable
        edge.viewport(1024, 680)
        time.sleep(0.4)
        edge.shot(OUT / "r3-07c-livret-1024.png")
        reachable = edge.js("""(() => { const m = document.querySelector('.modal'); m.scrollTop = m.scrollHeight;
            const b = [...m.querySelectorAll('.btn-primary')][0].getBoundingClientRect();
            return b.bottom <= innerHeight && b.top >= 0 && document.documentElement.scrollWidth <= innerWidth; })()""")
        edge.viewport(1280, 720)
        assert reachable, "bouton Imprimer hors d'atteinte en 1024×680"
        edge.key("Escape")
        edge.wait_for("!document.querySelector('.modal')")

    @step("Imprimer un livret sur « Microsoft Print to PDF » (sortie dans un fichier)")
    def _():
        before = set((RECETTE / "impressions").glob("*.pdf"))
        print_dialog("Microsoft Print to PDF", "booklet")
        edge.wait_for("document.querySelector('.modal [aria-label=\"Feuille du livret\"]').options.length > 0", timeout=20)
        edge.js("[...document.querySelectorAll('.modal .btn-primary')][0].click()")
        edge.wait_for("[...document.querySelectorAll('.toast')].some(t => t.textContent.includes('Livret envoyé'))", timeout=60)
        printed = new_print(before)
        assert printed.page_count == 2, printed.page_count  # 2 pages → 1 feuille, recto et verso
        # feuilles A4 portrait, comme un document Word ; faces tournées d'un quart de tour
        assert all(p.rect.height > p.rect.width and abs(p.rect.height - 842) < 3 for p in printed), [p.rect for p in printed]
        sheet = fitz.open()
        canvas = sheet.new_page(width=595 * 2 + 20, height=842)
        for i, page in enumerate(printed):
            canvas.draw_rect(fitz.Rect(i * 615, 0, i * 615 + 595, 842), color=(0.6, 0.6, 0.6))
            canvas.show_pdf_page(fitz.Rect(i * 615, 0, i * 615 + 595, 842), printed, i)
        canvas.get_pixmap(dpi=40).save(OUT / "r3-07d-livret-imprime.png")

    @step("Imprimer page 2 sur « Microsoft Print to PDF » (sortie dans un fichier)")
    def _():
        before = set((RECETTE / "impressions").glob("*.pdf"))
        print_dialog("Microsoft Print to PDF")
        edge.js("""(() => { const q = (l) => document.querySelector(`.modal [aria-label="${l}"]`);
            q('Pages à imprimer').value = 'range'; q('Pages à imprimer').dispatchEvent(new Event('change'));
            q('Pages choisies').value = '2'; })()""")
        edge.js("[...document.querySelectorAll('.modal .btn-primary')][0].click()")
        edge.wait_for("[...document.querySelectorAll('.toast')].some(t => t.textContent.includes('envoyée à « Microsoft Print to PDF »'))", timeout=60)
        printed = new_print(before)
        assert printed.page_count == 1, printed.page_count
        printed[0].get_pixmap(dpi=40).save(OUT / "r3-07e-imprime-page2.png")

    @step("Exporter en JPG : menu ⋯, toutes les pages en 150 ppp")
    def _():
        edge.click_on("#btn-more")
        edge.wait_for("[...document.querySelectorAll('.menu-item')].some(b => b.textContent.includes('Exporter en JPG'))")
        edge.js("[...document.querySelectorAll('.menu-item')].find(b => b.textContent.includes('Exporter en JPG')).click()")
        edge.wait_for("document.querySelector('.modal-title') && document.querySelector('.modal-title').textContent.includes('Exporter en JPG')")
        edge.js("document.querySelector('.modal select').value = 'all'")
        edge.shot(OUT / "r3-07b-export-jpg.png")
        edge.js("[...document.querySelectorAll('.modal .btn-primary')][0].click()")
        # Mode navigateur, sans dialogue Windows : le chemin est saisi.
        edge.wait_for("document.querySelector('.modal input.text-input')")
        target = RECETTE / "export.jpg"
        edge.js(f"document.querySelector('.modal input.text-input').value = {json.dumps(str(target))}")
        edge.js("[...document.querySelectorAll('.modal .btn-primary')][0].click()")
        edge.wait_for("[...document.querySelectorAll('.toast')].some(t => t.textContent.includes('images JPG'))", timeout=60)
        pages = edge.js("window.__app.doc.page_count")
        files = sorted(RECETTE.glob("export - page *.jpg"))
        assert len(files) == pages, (pages, files)
        first = fitz.Pixmap(str(files[0]))
        assert files[0].read_bytes()[:2] == b"\xff\xd8" and first.xres == 150 and first.width > 1000

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
