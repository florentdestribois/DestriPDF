"""Recette : parcours d'édition et de signature, comme un utilisateur.

Usage : python scripts/recette/parcours_edition.py <captures> <dossier d'échantillons>
L'instance doit tourner en mode recette sur http://127.0.0.1:8790/recette/.
"""
import json
import sys
import time
import traceback
from pathlib import Path

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
                edge.shot(OUT / f"echec-{len(results)}.png")
            except Exception:  # noqa: BLE001
                pass
        return fn
    return deco


def api(path):
    return edge.js(f"fetch('api/{path}', {{cache: 'no-store'}}).then(r => r.json())")


def page_texts(page=0):
    return [l["text"] for l in api(f"page/{page}/text")["lines"]]


def annots(page=0):
    return api(f"page/{page}/annots")["annots"]


def show(page, y):
    """Fait défiler pour placer l'ordonnée y (points) de la page au tiers de l'écran."""
    edge.js(f"""(() => {{ const v = window.__app.viewer;
        v.scroller.scrollTop = Math.max(0, v.offsets[{page}] + {y} * v.scale - v.scroller.clientHeight * 0.35); }})()""")
    time.sleep(0.35)


def seg_rect(text):
    found = edge.js(f"""(() => {{
        const segs = [...document.querySelectorAll('.page[data-index="0"] .tl-seg')];
        const s = segs.find(n => n.textContent === {json.dumps(text)});
        if (!s) return false;
        s.scrollIntoView({{block: 'center'}});
        return true;
    }})()""")
    if not found:
        raise LookupError(f"segment absent : {text}")
    time.sleep(0.3)
    return edge.js(f"""(() => {{
        const s = [...document.querySelectorAll('.page[data-index="0"] .tl-seg')].find(n => n.textContent === {json.dumps(text)});
        const r = s.getBoundingClientRect();
        return [r.left, r.top, r.right, r.bottom];
    }})()""")


def page_point(x, y, page=0, scroll=True):
    """Point de la page (en points PDF) -> coordonnées écran (après défilement)."""
    if scroll:
        show(page, y)
    return edge.js(f"""(() => {{
        const v = window.__app.viewer; const view = v.views[{page}];
        const r = view.el.getBoundingClientRect();
        return [r.left + {x} * v.scale, r.top + {y} * v.scale];
    }})()""")


def tool(name):
    edge.click_on(f'#tools .tool[data-tool="{name}"]')
    edge.wait_for(f"document.body.classList.contains('mode-{name}')")


def wait_doc_version(prev):
    edge.wait_for(f"window.__app.doc && window.__app.doc.version > {prev}", timeout=15)
    time.sleep(0.4)


def version():
    return edge.js("window.__app.doc.version")


edge = Edge(1280, 720)
try:
    edge.goto(URL, wait=0.5)
    edge.js("void 0")
    edge.wait_for("document.querySelectorAll('.page[data-index=\"0\"] .tl-seg').length > 5", timeout=15)
    # Accès à l'application pour la recette (lecture d'état seulement).
    edge.wait_for("window.__app && window.__app.doc", timeout=10)

    @step("Affichage 1280x720 avec libellés et pastille de navigation")
    def _():
        m = edge.js("""({labels: getComputedStyle(document.querySelector('.tool-label')).display,
            pill: !!document.getElementById('nav-pill').offsetParent,
            overflow: document.getElementById('toolbar').scrollWidth - document.getElementById('toolbar').clientWidth,
            zoom: document.getElementById('zoom-value').textContent})""")
        print("   ", m)
        assert m["labels"] != "none" and m["pill"] and m["overflow"] <= 0
        edge.shot(OUT / "01-ouverture.png")

    @step("Modifier une ligne (date)")
    def _():
        tool("edit")
        x0, y0, x1, y1 = seg_rect("Date : 12/10/2026")
        edge.click(x1 - 3, (y0 + y1) / 2)
        edge.wait_for("document.querySelector('.te-box')")
        edge.shot(OUT / "02-editeur-ouvert.png")
        # remplacer le jour : effacer les 10 derniers caractères puis saisir
        for _ in range(10):
            edge.key("Backspace")
        edge.type("15/10/2026")
        v = version()
        edge.key("Enter")
        wait_doc_version(v)
        edge.wait_for("!document.querySelector('.te-box')", timeout=10)
        texts = page_texts()
        assert "Date : 15/10/2026" in texts and "Date : 12/10/2026" not in texts, texts
        edge.shot(OUT / "03-ligne-modifiee.png")

    @step("Modifier un montant aligné à droite")
    def _():
        x0, y0, x1, y1 = seg_rect("480,00 €")
        edge.click(x0 + 3, (y0 + y1) / 2)
        edge.wait_for("document.querySelector('.te-box')")
        pressed = edge.js("[...document.querySelectorAll('.te-bar .icon-btn[aria-pressed]')].map(b => b.dataset.tip + '=' + b.getAttribute('aria-pressed'))")
        print("   ", pressed)
        assert "Aligner à droite=true" in pressed
        edge.key("a", modifiers=CTRL)
        edge.type("1 520,00 €")
        v = version()
        edge.key("Enter")
        wait_doc_version(v)
        line = next(l for l in api("page/0/text")["lines"] if l["text"] == "1 520,00 €")
        assert abs(line["bbox"][2] - 540) < 1.5, line["bbox"]
        assert "Pose et ajustage" in page_texts()

    @step("Tabulation : valider puis passer à la ligne suivante")
    def _():
        x0, y0, x1, y1 = seg_rect("Client : Mairie de Zellwiller")
        edge.click(x1 - 2, (y0 + y1) / 2)
        edge.wait_for("document.querySelector('.te-box')")
        edge.type(" (67)")
        v = version()
        edge.key("Tab")
        wait_doc_version(v)
        edge.wait_for("document.querySelector('.te-box') && document.querySelector('.te-content').textContent.startsWith('Objet')", timeout=10)
        edge.key("Escape")
        edge.wait_for("!document.querySelector('.te-box')")
        assert "Client : Mairie de Zellwiller (67)" in page_texts()

    @step("Ajouter du texte libre")
    def _():
        tool("text")
        x, y = page_point(60, 400)
        edge.click(x, y)
        edge.wait_for("document.querySelector('.free-editor')")
        edge.type("Bon pour accord — 1 520,00 €")
        v = version()
        edge.key("Enter", modifiers=CTRL)
        wait_doc_version(v)
        free = [a for a in annots() if a["type"] == "FreeText"]
        assert free and free[0]["content"] == "Bon pour accord — 1 520,00 €", free

    @step("Ajouter une note")
    def _():
        tool("note")
        x, y = page_point(400, 300)
        edge.click(x, y)
        edge.wait_for("document.querySelector('.popover textarea')")
        edge.type("Vérifier la cote 93 sur place")
        v = version()
        edge.click_on(".popover .btn-primary")
        wait_doc_version(v)
        notes = [a for a in annots() if a["type"] == "Text"]
        assert notes and notes[0]["content"] == "Vérifier la cote 93 sur place"
        edge.shot(OUT / "04-annotations.png")

    @step("Surligner un texte")
    def _():
        tool("highlight")
        x0, y0, x1, y1 = seg_rect("Objet : Remplacement des portes du préau")
        v = version()
        edge.drag([(x0 + 1, (y0 + y1) / 2), (x1 - 1, (y0 + y1) / 2)], steps=10)
        wait_doc_version(v)
        assert any(a["type"] == "Highlight" for a in annots())

    @step("Dessiner à main levée")
    def _():
        tool("draw")
        pts = [page_point(300 + i * 10, 600 + (i % 3) * 8, scroll=(i == 0)) for i in range(10)]
        v = version()
        edge.drag([tuple(p) for p in pts], steps=3)
        wait_doc_version(v)
        assert any(a["type"] == "Ink" for a in annots())

    @step("Tracer un rectangle")
    def _():
        tool("shape")
        a = page_point(60, 640)
        b = page_point(220, 700, scroll=False)
        v = version()
        edge.drag([tuple(a), tuple(b)], steps=6)
        wait_doc_version(v)
        assert any(x["type"] == "Square" for x in annots())

    @step("Effacer une zone (image)")
    def _():
        tool("erase")
        before = api("page/0/annots")
        a = page_point(470, 50)
        b = page_point(550, 130, scroll=False)
        v = version()
        edge.drag([tuple(a), tuple(b)], steps=6)
        wait_doc_version(v)
        edge.shot(OUT / "05-effacement.png")

    @step("Annuler et rétablir au clavier")
    def _():
        edge.click_on("#viewer")
        label = edge.js("window.__app.doc.undo_label")
        assert label == "Effacement d'une zone", label
        v = version()
        edge.key("z", modifiers=CTRL)
        wait_doc_version(v)
        assert edge.js("window.__app.doc.redo_label") == "Effacement d'une zone"
        v = version()
        edge.key("y", modifiers=CTRL)
        wait_doc_version(v)
        assert edge.js("window.__app.doc.undo_label") == "Effacement d'une zone"

    @step("Sélectionner, déplacer puis supprimer une annotation")
    def _():
        tool("select")
        edge.wait_for("document.querySelectorAll('.page[data-index=\"0\"] .annot-hit[data-type=\"FreeText\"]').length")
        edge.js("document.querySelector('.page[data-index=\"0\"] .annot-hit[data-type=\"FreeText\"]').scrollIntoView({block: 'center'})")
        time.sleep(0.35)
        x, y = edge.center('.page[data-index="0"] .annot-hit[data-type="FreeText"]')
        before = next(a for a in annots() if a["type"] == "FreeText")["rect"]
        v = version()
        edge.drag([(x, y), (x + 60, y + 30)], steps=8)
        wait_doc_version(v)
        after = next(a for a in annots() if a["type"] == "FreeText")["rect"]
        scale = edge.js("window.__app.viewer.scale")
        assert abs((after[0] - before[0]) - 60 / scale) < 1.5, (before, after)
        edge.wait_for("document.querySelector('.annot-bar')")
        x, y = edge.center('.page[data-index="0"] .annot-hit[data-type="FreeText"]')
        edge.click(x, y)
        edge.wait_for("document.querySelector('.annot-bar')")
        v = version()
        edge.key("Delete")
        wait_doc_version(v)
        assert not any(a["type"] == "FreeText" for a in annots())
        v = version()
        edge.key("z", modifiers=CTRL)
        wait_doc_version(v)
        assert any(a["type"] == "FreeText" for a in annots())

    @step("Rechercher")
    def _():
        edge.key("f", modifiers=CTRL)
        edge.type("Zellwiller")
        edge.wait_for("document.getElementById('search-count').textContent.includes('/')", timeout=5)
        count = edge.js("document.getElementById('search-count').textContent")
        assert count.strip() == "1 / 1", count
        edge.key("Escape")

    @step("Navigation : page suivante, vignette, zoom")
    def _():
        start = int(edge.js("document.getElementById('page-input').value"))
        edge.click_on("#btn-next-page")
        edge.wait_for(f"document.getElementById('page-input').value === '{start + 1}'")
        edge.js("document.querySelector('.thumb[data-index=\"4\"]').scrollIntoView({block: 'center'})")
        time.sleep(0.3)
        edge.click_on('.thumb[data-index="4"]')
        edge.wait_for("document.getElementById('page-input').value === '5'")
        z = edge.js("window.__app.viewer.zoom")
        edge.click_on("#btn-zoom-in")
        assert edge.js("window.__app.viewer.zoom") > z
        edge.click_on("#zoom-value")
        edge.wait_for("document.querySelector('.menu')")
        edge.js("[...document.querySelectorAll('.menu-item')].find(b => b.textContent.includes('Page entière')).click()")
        time.sleep(0.4)
        edge.shot(OUT / "06-page-entiere.png")
        edge.js("window.__app.viewer.scrollToPage(0)")

    @step("Panneau Commentaires")
    def _():
        edge.click_on("#btn-more")
        edge.wait_for("document.querySelector('.menu')")
        edge.js("[...document.querySelectorAll('.menu-item')].find(b => b.textContent.trim() === 'Commentaires').click()")
        edge.wait_for("document.querySelectorAll('#panel-body .comment').length >= 5", timeout=8)
        time.sleep(0.4)
        overflow = edge.js("document.documentElement.scrollWidth - innerWidth")
        assert overflow <= 0, f'débordement horizontal de {overflow} px'
        edge.shot(OUT / "07-commentaires.png")

    @step("Signer avec la clé (cadre visible)")
    def _():
        edge.click_on("#btn-sign")
        edge.wait_for("document.querySelector('#panel-body .cert')", timeout=10)
        cert = edge.js("document.querySelector('#panel-body .cert .cert-name').textContent")
        assert cert == "Florent TEST", cert
        assert edge.js("document.body.classList.contains('mode-sign')")
        edge.shot(OUT / "08-panneau-signer.png")
        a = page_point(330, 720)
        b = page_point(545, 790, scroll=False)
        edge.drag([tuple(a), tuple(b)], steps=6)
        edge.wait_for("document.querySelector('.sig-frame')")
        edge.js("""(() => { const i = [...document.querySelectorAll('#panel-body input.text-input')];
            i[0].value = 'Bon pour accord'; i[0].dispatchEvent(new Event('input'));
            i[1].value = 'Zellwiller'; i[1].dispatchEvent(new Event('input')); })()""")
        edge.shot(OUT / "09-cadre-place.png")
        edge.js("[...document.querySelectorAll('#panel-body .btn-primary')].find(b => b.textContent.includes('Signer')).click()")
        edge.wait_for("document.querySelector('.modal input')")
        target = str(RECETTE / "dossier - signé.pdf")
        edge.js(f"document.querySelector('.modal input').value = {json.dumps(target)}")
        edge.js("[...document.querySelectorAll('.modal .btn-primary')][0].click()")
        edge.wait_for("window.__app.doc && window.__app.doc.signed", timeout=30)
        edge.wait_for("!document.getElementById('sig-banner').hidden && document.getElementById('sig-banner').textContent.includes('Signé par')", timeout=30)
        banner = edge.js("document.getElementById('sig-banner').textContent")
        print("   bandeau :", banner)
        assert Path(target).exists()
        time.sleep(0.8)
        edge.shot(OUT / "10-signe.png")

    @step("Signature manuscrite (image) dessinée puis apposée")
    def _():
        edge.click_on("#btn-more")
        edge.wait_for("document.querySelector('.menu')")
        edge.js("[...document.querySelectorAll('.menu-item')].find(b => b.textContent.includes('signature manuscrite')).click()")
        edge.wait_for("document.querySelector('.sig-pad')")
        x0, y0 = edge.js("(() => { const r = document.querySelector('.sig-pad').getBoundingClientRect(); return [r.left, r.top]; })()")
        edge.drag([(x0 + 40, y0 + 120), (x0 + 120, y0 + 60), (x0 + 200, y0 + 130), (x0 + 300, y0 + 70), (x0 + 380, y0 + 110)], steps=8)
        edge.shot(OUT / "11-dessin-signature.png")
        edge.js("[...document.querySelectorAll('.modal .btn-primary')][0].click()")
        edge.wait_for("document.body.classList.contains('mode-stamp')", timeout=8)
        x, y = page_point(100, 760, page=1)
        edge.js("window.__app.viewer.scrollToPage(1)")
        time.sleep(0.5)
        x, y = page_point(150, 300, page=1)
        v = version()
        edge.click(x, y)
        wait_doc_version(v)
        assert any(a["type"] == "Stamp" for a in annots(1))

    @step("Enregistrer sous")
    def _():
        target = RECETTE / "dossier - annoté.pdf"
        edge.key("s", modifiers=CTRL | 8)
        edge.wait_for("document.querySelector('.modal input')")
        edge.js(f"document.querySelector('.modal input').value = {json.dumps(str(target))}")
        edge.js("[...document.querySelectorAll('.modal .btn-primary')][0].click()")
        edge.wait_for(f"window.__app.doc.path && window.__app.doc.path.endsWith('annoté.pdf') && !window.__app.doc.dirty", timeout=15)
        assert target.exists()

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
