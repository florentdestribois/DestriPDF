"""Recette : organiser les pages, assembler des PDF, glisser-déposer, compresser.

Usage : python scripts/recette/parcours_assemblage.py <captures> <dossier d'échantillons>
L'instance doit tourner en mode recette sur http://127.0.0.1:8790/recette/.
Glisser-déposer réel : le geste de la souris démarre le glisser de la page (dragstart),
le dépôt passe par le protocole DevTools ; fichiers « venus de l'Explorateur » compris.
"""
import json
import sys
import time
import traceback
from pathlib import Path

import pymupdf as fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cdp import CTRL, SHIFT, Edge

OUT = Path(sys.argv[1])
OUT.mkdir(exist_ok=True)
RECETTE = Path(sys.argv[2])
LOT = RECETTE / "lot"
IMAGES = RECETTE / "images"
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
            traceback.print_exc(limit=3)
            try:
                edge.shot(OUT / f"r4-echec-{len(results)}.png")
            except Exception:  # noqa: BLE001
                pass
        return fn
    return deco


def api(path):
    return edge.js(f"fetch('api/{path}', {{cache: 'no-store'}}).then(r => r.json())")


def version():
    return edge.js("window.__app.doc ? window.__app.doc.version : -1")


def wait_version(prev, timeout=20):
    edge.wait_for(f"window.__app.doc && window.__app.doc.version > {prev}", timeout=timeout)
    time.sleep(0.4)


def first_lines(count=None):
    count = count or edge.js("window.__app.doc.page_count")
    return [(api(f"page/{i}/text")["lines"] or [{"text": ""}])[0]["text"] for i in range(count)]


def reorder(items, pages, before):
    """Ordre attendu : les pages choisies, dans l'ordre du document, avant `before`."""
    chosen = sorted(set(pages))
    rest = [i for i in range(len(items)) if i not in chosen]
    at = sum(1 for i in rest if i < before)
    return [items[i] for i in rest[:at] + chosen + rest[at:]]


def selection():
    return edge.js("window.__app.pageSelection.list()")


def rect(selector, scroll=True):
    box = edge.js(f"""(() => {{ const n = document.querySelector({json.dumps(selector)}); if (!n) return null;
        if ({json.dumps(scroll)}) n.scrollIntoView({{block: 'nearest'}}); const r = n.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; }})()""")
    if not box:
        raise LookupError(selector)
    return box


def mclick(selector, modifiers=0):
    x0, y0, x1, y1 = rect(selector)
    x, y = (x0 + x1) / 2, y0 + (y1 - y0) * 0.4
    edge.mouse("mouseMoved", x, y, modifiers=modifiers)
    edge.mouse("mousePressed", x, y, buttons=1, click_count=1, modifiers=modifiers)
    edge.mouse("mouseReleased", x, y, click_count=1, modifiers=modifiers)
    time.sleep(0.15)


def card(index):
    return f'.org-card[data-index="{index}"]'


def thumb(index):
    return f'.thumb[data-index="{index}"]'


def discard_if_asked(timeout=2.0):
    end = time.time() + timeout
    while time.time() < end:
        if edge.js("Boolean(document.querySelector('.modal-title') && document.querySelector('.modal-title').textContent.includes('Enregistrer les modifications'))"):
            edge.js("[...document.querySelectorAll('.modal .btn')].find(b => b.textContent === 'Ne pas enregistrer').click()")
            return
        time.sleep(0.1)


def open_doc(path):
    edge.js(f"void window.__app.openPath({json.dumps(str(path))})")
    discard_if_asked()
    edge.wait_for(f"window.__app.doc && window.__app.doc.name === {json.dumps(Path(path).name)}", timeout=15)
    time.sleep(0.5)


def toast_with(text, timeout=20):
    edge.wait_for(f"[...document.querySelectorAll('.toast')].some(t => t.textContent.includes({json.dumps(text)}))", timeout=timeout)
    return edge.js(f"[...document.querySelectorAll('.toast')].find(t => t.textContent.includes({json.dumps(text)})).textContent")


def thumbs_loaded(selector):
    edge.wait_for(f"[...document.querySelectorAll({json.dumps(selector)})].slice(0, 6).every(i => i.complete && i.naturalWidth > 0)", timeout=20)


def set_files(selector, files):
    root = edge.call("DOM.getDocument")["root"]["nodeId"]
    node = edge.call("DOM.querySelector", nodeId=root, selector=selector)["nodeId"]
    edge.call("DOM.setFileInputFiles", nodeId=node, files=[str(f) for f in files])


edge = Edge(1280, 720)
try:
    edge.goto(URL, wait=0.5)
    edge.wait_for("window.__app && window.__app.state", timeout=10)

    @step("Organiser : toutes les pages en grille")
    def _():
        open_doc(RECETTE / "dossier.pdf")
        edge.click_on("#btn-organize")
        edge.wait_for("document.body.classList.contains('organizing') && document.querySelectorAll('.org-card').length === 12", timeout=10)
        thumbs_loaded(".org-card img")
        hidden = edge.js("""[getComputedStyle(document.getElementById('sidebar')).display, getComputedStyle(document.getElementById('nav-pill')).display,
            getComputedStyle(document.getElementById('tools')).display]""")
        assert hidden == ["none", "none", "none"], hidden
        assert edge.js("document.getElementById('btn-organize').getAttribute('aria-pressed')") == "true"
        edge.shot(OUT / "r4-01-organiser.png")

    @step("Sélection : clic, Ctrl+clic, Maj+clic, Ctrl+Maj+clic")
    def _():
        mclick(card(1))
        assert selection() == [1], selection()
        mclick(card(3), CTRL)
        assert selection() == [1, 3], selection()
        mclick(card(5), SHIFT)  # plage depuis la dernière page cliquée (3)
        assert selection() == [3, 4, 5], selection()
        mclick(card(8), CTRL)
        mclick(card(10), CTRL | SHIFT)  # ajoute la plage 8 à 10
        assert selection() == [3, 4, 5, 8, 9, 10], selection()
        status = edge.js("document.querySelector('.org-status').textContent")
        assert status == "6 pages sélectionnées sur 12", status
        assert edge.js("document.querySelectorAll('.org-card.selected').length") == 6
        assert not edge.js("[...document.querySelectorAll('.org-bar [data-needs-selection]')].some(b => b.disabled)")
        edge.shot(OUT / "r4-02-selection.png")

    @step("Glisser les pages choisies : déplacées ensemble, une seule annulation")
    def _():
        before = first_lines()
        x0, y0, x1, y1 = rect(card(0))
        v = version()
        start = rect(card(4))
        edge.html_drag(((start[0] + start[2]) / 2, start[1] + 40), (x0 + 12, (y0 + y1) / 2),
                       hover=lambda: edge.shot(OUT / "r4-03-glisser.png"))
        wait_version(v)
        assert selection() == [0, 1, 2, 3, 4, 5], selection()
        after = first_lines()
        assert after == reorder(before, [3, 4, 5, 8, 9, 10], 0), after
        assert edge.js("window.__app.doc.undo_label") == "Déplacement de pages"
        marker = edge.js("document.querySelectorAll('.drop-before, .drop-after, .dragging').length")
        assert marker == 0, marker
        v = version()
        edge.key("z", modifiers=CTRL)
        wait_version(v)
        assert first_lines() == before
        # l'ordre a changé : la sélection gardée par position viserait d'autres pages
        assert selection() == [], selection()

    @step("Déposer deux PDF de l'Explorateur entre deux pages")
    def _():
        count = edge.js("window.__app.doc.page_count")
        before = first_lines()
        x0, y0, x1, y1 = rect(card(1))
        v = version()
        captured = {}

        def hover():
            captured["overlay"] = edge.js("document.getElementById('drop-overlay').hidden")
            captured["marker"] = edge.js("document.querySelector('.org-card.drop-after') && document.querySelector('.org-card.drop-after').dataset.index")
            edge.shot(OUT / "r4-04-depot-fichiers.png")

        edge.drop_files([LOT / "2 - memoire.pdf", LOT / "1 - lettre.pdf"], (x1 - 12, (y0 + y1) / 2), hover)
        wait_version(v)
        assert captured == {"overlay": True, "marker": "1"}, captured
        assert edge.js("window.__app.doc.page_count") == count + 4
        lines = first_lines()
        # rangés par nom : « 1 - lettre » puis « 2 - memoire », après la page 2
        assert lines[:6] == before[:2] + ["Lettre 1", "Mémoire 1", "Mémoire 2", "Mémoire 3"], lines[:6]
        assert selection() == [2, 3, 4, 5], selection()
        print("    ", toast_with("ajoutées"))
        assert edge.js("document.getElementById('drop-overlay').hidden")
        edge.shot(OUT / "r4-05-pdf-ajoutes.png")

    @step("Clavier : Suppr supprime la sélection, Ctrl+Z la rétablit, Ctrl+A choisit tout")
    def _():
        count = edge.js("window.__app.doc.page_count")
        edge.js(f"document.querySelector({json.dumps(card(2))}).focus()")
        v = version()
        edge.key("Delete")
        wait_version(v)
        assert edge.js("window.__app.doc.page_count") == count - 4
        print("    ", toast_with("pages supprimées"))
        v = version()
        edge.key("z", modifiers=CTRL)
        wait_version(v)
        assert edge.js("window.__app.doc.page_count") == count
        edge.js(f"document.querySelector({json.dumps(card(0))}).focus()")
        edge.key("a", modifiers=CTRL)
        assert selection() == list(range(count)), selection()
        edge.key("ArrowRight")
        assert selection() == [1], selection()
        edge.key("ArrowRight", modifiers=SHIFT)
        edge.key("ArrowRight", modifiers=SHIFT)
        assert selection() == [1, 2, 3], selection()

    @step("Terminé : retour à la lecture sur la page ouverte (double-clic)")
    def _():
        x0, y0, x1, y1 = rect(card(6))
        edge.click((x0 + x1) / 2, (y0 + y1) / 2, count=2)
        edge.wait_for("!document.body.classList.contains('organizing')", timeout=5)
        time.sleep(0.4)
        assert edge.js("window.__app.viewer.current") == 6
        assert edge.js("getComputedStyle(document.getElementById('sidebar')).display") != "none"

    @step("Vignettes : Ctrl+clic puis glisser deux pages")
    def _():
        before = first_lines()
        edge.js("document.querySelector('#thumbs').scrollTop = 0")
        time.sleep(0.3)
        mclick(thumb(0))
        mclick(thumb(1), CTRL)
        assert selection() == [0, 1], selection()
        edge.js(f"document.querySelector({json.dumps(thumb(1))}).scrollIntoView({{block: 'start'}})")
        time.sleep(0.3)
        edge.shot(OUT / "r4-06-vignettes-selection.png")
        # Les deux cadres lus sans défilement entre eux : la vignette 2 sous la 1.
        src = rect(thumb(1), scroll=False)
        x0, y0, x1, y1 = rect(thumb(2), scroll=False)
        assert y1 < 680, (src, y1)
        v = version()
        edge.html_drag(((src[0] + src[2]) / 2, src[1] + 40), ((x0 + x1) / 2, y1 - 12),
                       hover=lambda: edge.shot(OUT / "r4-07-vignettes-glisser.png"))
        wait_version(v)
        assert first_lines() == reorder(before, [0, 1], 3), first_lines()[:4]
        assert selection() == [1, 2], selection()
        edge.key("z", modifiers=CTRL)
        time.sleep(0.6)

    @step("Accueil : « Assembler des fichiers », rangés par nom, à enregistrer")
    def _():
        edge.js("void window.__app.closeDocument()")
        discard_if_asked()
        edge.wait_for("!document.getElementById('start').hidden", timeout=10)
        assert edge.js("document.getElementById('start-assemble').offsetParent !== null")
        edge.shot(OUT / "r4-08-accueil-assembler.png")
        set_files("#assemble-input", [LOT / "10 - annexe.pdf", LOT / "2 - memoire.pdf", LOT / "1 - lettre.pdf"])
        edge.wait_for("window.__app.doc && window.__app.doc.name === '1 - lettre - assemblé.pdf'", timeout=20)
        edge.wait_for("document.body.classList.contains('organizing') && document.querySelectorAll('.org-card').length === 6", timeout=10)
        doc = edge.js("window.__app.doc")
        assert doc["dirty"] and doc["path"] is None, doc
        assert [entry[1] for entry in doc["toc"]] == ["1 - lettre", "2 - memoire", "10 - annexe"], doc["toc"]
        assert first_lines() == ["Lettre 1", "Mémoire 1", "Mémoire 2", "Mémoire 3", "Annexe 1", "Annexe 2"]
        thumbs_loaded(".org-card img")
        print("    ", toast_with("fichiers assemblés"))
        edge.shot(OUT / "r4-09-assemblage.png")
        # Ctrl+S : un document assemblé n'a pas encore de fichier, « Enregistrer sous »
        target = RECETTE / "dossier assemblé.pdf"
        edge.key("s", modifiers=CTRL)
        edge.wait_for("document.querySelector('.modal input.text-input')", timeout=10)
        edge.js(f"document.querySelector('.modal input.text-input').value = {json.dumps(str(target))}")
        edge.js("[...document.querySelectorAll('.modal .btn-primary')][0].click()")
        edge.wait_for("window.__app.doc && !window.__app.doc.dirty", timeout=15)
        assert fitz.open(target).page_count == 6

    @step("Accueil : trois PDF déposés d'un coup sont assemblés")
    def _():
        edge.js("void window.__app.closeDocument()")
        discard_if_asked()
        edge.wait_for("!document.getElementById('start').hidden", timeout=10)
        x0, y0, x1, y1 = rect(".start-card")
        captured = {}

        def hover():
            captured["title"] = edge.js("document.getElementById('drop-title').textContent")
            edge.shot(OUT / "r4-10-accueil-depot.png")

        edge.drop_files([LOT / "2 - memoire.pdf", LOT / "10 - annexe.pdf", LOT / "1 - lettre.pdf"], ((x0 + x1) / 2, y0 + 60), hover)
        assert captured["title"] == "Déposez les 3 fichiers pour les assembler", captured
        edge.wait_for("window.__app.doc && window.__app.doc.name === '1 - lettre - assemblé.pdf'", timeout=20)
        edge.wait_for("document.body.classList.contains('organizing')", timeout=10)
        assert edge.js("window.__app.doc.page_count") == 6

    @step("Accueil : une photo déposée s'ouvre en PDF, à enregistrer")
    def _():
        edge.js("void window.__app.closeDocument()")
        discard_if_asked()
        edge.wait_for("!document.getElementById('start').hidden", timeout=10)
        x0, y0, x1, y1 = rect(".start-card")
        captured = {}

        def hover():
            captured["title"] = edge.js("document.getElementById('drop-title').textContent")

        edge.drop_files([IMAGES / "chantier.jpg"], ((x0 + x1) / 2, y0 + 60), hover)
        assert captured["title"] == "Déposez le fichier pour l'ouvrir", captured
        edge.wait_for("window.__app.doc && window.__app.doc.name === 'chantier.pdf'", timeout=20)
        doc = edge.js("window.__app.doc")
        assert doc["page_count"] == 1 and doc["dirty"] and not doc["path"], doc
        page = doc["pages"][0] if doc.get("pages") else None
        if page:
            assert page["h"] > page["w"], page  # orientation de l'appareil photo appliquée
        time.sleep(1.0)
        edge.shot(OUT / "r5-01-photo-ouverte.png")

    @step("Organiser : une photo et un TIFF de deux pages déposés entre deux pages")
    def _():
        open_doc(LOT / "2 - memoire.pdf")
        edge.js("void window.__app.organizer.open()")
        edge.wait_for("document.body.classList.contains('organizing')", timeout=10)
        thumbs_loaded(".org-card img")
        x0, y0, x1, y1 = rect(card(0))
        v = version()
        edge.drop_files([IMAGES / "scan.tif", IMAGES / "chantier.jpg"], (x1 - 12, (y0 + y1) / 2), lambda: None)
        wait_version(v)
        assert edge.js("window.__app.doc.page_count") == 6
        assert selection() == [1, 2, 3], selection()
        print("    ", toast_with("ajoutées"))
        thumbs_loaded(".org-card img")
        edge.shot(OUT / "r5-02-images-ajoutees.png")
        edge.js("void window.__app.undo()")
        edge.wait_for("window.__app.doc.page_count === 3", timeout=10)

    @step("Accueil : « Assembler des fichiers » avec PDF et images")
    def _():
        edge.js("void window.__app.closeDocument()")
        discard_if_asked()
        edge.wait_for("!document.getElementById('start').hidden", timeout=10)
        set_files("#assemble-input", [IMAGES / "logo.png", LOT / "1 - lettre.pdf", IMAGES / "scan.tif"])
        edge.wait_for("window.__app.doc && window.__app.doc.name === '1 - lettre - assemblé.pdf'", timeout=20)
        assert edge.js("window.__app.doc.page_count") == 4
        print("    ", toast_with("assemblés : 4 pages"))
        edge.shot(OUT / "r5-03-assemblage-images.png")

    @step("Compresser le PDF : estimation par niveau puis copie compressée")
    def _():
        source = RECETTE / "chantier.pdf"
        original = source.stat().st_size
        open_doc(source)
        edge.click_on("#btn-more")
        edge.wait_for("[...document.querySelectorAll('.menu-item')].some(b => b.textContent.includes('Compresser le PDF'))")
        edge.js("[...document.querySelectorAll('.menu-item')].find(b => b.textContent.includes('Compresser le PDF')).click()")
        edge.wait_for("document.querySelector('.modal-title') && document.querySelector('.modal-title').textContent === 'Compresser le PDF'")
        edge.wait_for("document.querySelector('.choice[aria-checked=\"true\"] .choice-size').textContent.startsWith('≈')", timeout=60)
        assert not edge.js("document.querySelector('.modal-actions .btn-primary').disabled")
        print("     équilibrée :", edge.js("document.querySelector('.choice[aria-checked=\"true\"] .choice-size').textContent"))
        print("    ", edge.js("document.querySelector('.compress-current').textContent"))
        # boîte ouverte : les notifications passent en haut, jamais sur ses boutons
        assert edge.js("getComputedStyle(document.getElementById('toasts')).top") == "14px"
        edge.shot(OUT / "r4-11-compresser.png")
        edge.js("document.querySelector('.choice[data-level=\"minimum\"]').click()")
        edge.wait_for("document.querySelector('.choice[data-level=\"minimum\"] .choice-size').textContent.startsWith('≈')", timeout=60)
        print("     minimale :", edge.js("document.querySelector('.choice[data-level=\"minimum\"] .choice-size').textContent"))
        edge.viewport(1024, 680)
        time.sleep(0.3)
        edge.shot(OUT / "r4-12-compresser-1024.png")
        reachable = edge.js("""(() => { const m = document.querySelector('.modal'); m.scrollTop = m.scrollHeight;
            const b = document.querySelector('.modal-actions .btn-primary').getBoundingClientRect();
            return b.bottom <= innerHeight && b.top >= 0 && document.documentElement.scrollWidth <= innerWidth; })()""")
        edge.viewport(1280, 720)
        assert reachable, "bouton Enregistrer hors d'atteinte en 1024×680"
        edge.js("document.querySelector('.modal-actions .btn-primary').click()")
        target = RECETTE / "chantier - compressé.pdf"
        edge.wait_for("document.querySelector('.modal input.text-input')", timeout=10)
        value = edge.js("document.querySelector('.modal input.text-input').value")
        assert value.endswith("chantier - compressé.pdf"), value
        edge.js(f"document.querySelector('.modal input.text-input').value = {json.dumps(str(target))}")
        edge.js("[...document.querySelectorAll('.modal .btn-primary')][0].click()")
        print("    ", toast_with("PDF compressé enregistré", timeout=60))
        assert target.exists() and target.stat().st_size < original / 10, (target.stat().st_size, original)
        assert source.stat().st_size == original
        assert "Photo du chantier" in fitz.open(target)[0].get_text()
        assert edge.js("[...document.querySelectorAll('.toast-action')].some(b => b.textContent === 'Ouvrir')")
        edge.shot(OUT / "r4-13-compresse.png")

    @step("Organiser en 1024×680, 1920×1080 et en sombre : rien ne déborde")
    def _():
        open_doc(RECETTE / "dossier.pdf")
        edge.js("window.__app.organizer.open()")
        edge.wait_for("document.querySelectorAll('.org-card').length === 12", timeout=10)
        mclick(card(2))
        mclick(card(4), SHIFT)
        for width, height, name in ((1024, 680, "r4-14-organiser-1024.png"), (1920, 1080, "r4-15-organiser-1920.png")):
            edge.viewport(width, height)
            time.sleep(0.5)
            thumbs_loaded(".org-card img")
            edge.shot(OUT / name)
            fits = edge.js("""(() => { const done = [...document.querySelectorAll('.org-bar .btn-primary')].pop().getBoundingClientRect();
                return document.documentElement.scrollWidth <= innerWidth && done.right <= innerWidth && done.bottom <= innerHeight; })()""")
            assert fits, (width, height)
        edge.viewport(1280, 720)
        edge.js("document.documentElement.dataset.theme = 'dark'")
        time.sleep(0.4)
        edge.shot(OUT / "r4-16-organiser-sombre.png")
        edge.js("window.__app.applyTheme()")
        edge.key("Escape")
        edge.wait_for("!document.body.classList.contains('organizing')", timeout=5)

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
