"""Captures de charte : écrans que les parcours de recette ne montrent pas (menus,
voile du glisser, attente, erreur, états vides, À propos, confirmation), en clair
et en sombre.

Usage : python scripts/recette/captures_charte.py <captures> [url]
L'instance doit tourner en mode recette (défaut : http://127.0.0.1:8790/recette/),
un document ouvert.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cdp import Edge

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
URL = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8790/recette/"

edge = Edge(1280, 720, port=9335)


def shot(name):
    time.sleep(0.25)
    edge.shot(OUT / f"c-{name}.png")
    print("capture", name)


def escape():
    edge.key("Escape")
    time.sleep(0.2)


def theme(value):
    edge.js(f"""(() => {{ if ({value!r} === 'auto') delete document.documentElement.dataset.theme;
        else document.documentElement.dataset.theme = {value!r}; }})()""")


def tour(suffix):
    app = "window.__app"
    edge.js("document.getElementById('btn-more').click()")
    shot(f"menu-plus{suffix}")
    escape()
    edge.js("document.getElementById('zoom-value').click()")
    shot(f"menu-zoom{suffix}")
    escape()
    edge.js(f"void {app}.about()")
    shot(f"a-propos{suffix}")
    escape()
    edge.js(f"void {app}.openSettings()")
    shot(f"reglages{suffix}")
    escape()
    edge.js(f"void {app}.exportJpeg()")
    shot(f"export-jpg{suffix}")
    escape()
    # Voile du glisser, attente, erreur : états transitoires montrés à la main.
    edge.js("document.getElementById('drop-title').textContent = 'Ouvrir le fichier'; document.getElementById('drop-overlay').hidden = false")
    shot(f"voile-glisser{suffix}")
    edge.js("document.getElementById('drop-overlay').hidden = true")
    edge.js("""void import('./static/js/ui.js').then(ui => { window.__busy = ui.busy('Envoi à l\\'imprimante…');
        ui.toast('Ce fichier est ouvert ou verrouillé par un autre logiciel.', 'error');
        ui.toast('Enregistré.', 'ok'); ui.toast('Ouverture…'); })""")
    shot(f"attente-et-notifications{suffix}")
    edge.js("window.__busy.close(); document.getElementById('toasts').textContent = ''")
    # Panneaux : commentaires, signets vides, outils et leurs options.
    edge.js(f"{app}.panel.open('comments')")
    edge.js("document.getElementById('tab-toc').click()")
    shot(f"commentaires-et-signets{suffix}")
    edge.js("document.getElementById('tab-pages').click()")
    edge.js(f"{app}.panel.close()")
    for tool in ("text", "highlight", "shape"):
        edge.js(f"{app}.tools.set('{tool}')")
        shot(f"outil-{tool}{suffix}")
    edge.js(f"{app}.tools.set('select')")
    edge.js(f"{app}.startSigning()")
    time.sleep(1.2)
    shot(f"signer{suffix}")
    edge.js(f"{app}.panel.close()")
    edge.js(f"{app}.organizer.open()")
    time.sleep(0.6)
    shot(f"organiser{suffix}")
    edge.js(f"{app}.organizer.close()")


try:
    edge.goto(URL, wait=0.5)
    edge.wait_for("window.__app && window.__app.doc", timeout=15)
    time.sleep(0.8)
    shot("lecture")
    tour("")
    theme("dark")
    shot("lecture-sombre")
    tour("-sombre")
    theme("light")
    # Confirmation à la fermeture d'un document modifié, puis accueil.
    edge.js("void fetch('api/pages/rotate', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-DestriPDF': '1'}, body: JSON.stringify({pages: [0], angle: 90})}).then(r => r.json()).then(d => window.__app.applyDoc(d.doc))")
    time.sleep(0.8)
    edge.js("void window.__app.closeDocument()")
    shot("confirmation")
    edge.js("[...document.querySelectorAll('.modal .btn')].find(b => b.textContent === 'Ne pas enregistrer').click()")
    edge.wait_for("!document.getElementById('start').hidden", timeout=10)
    shot("accueil")
    theme("dark")
    shot("accueil-sombre")
    for width, height in ((1024, 680), (1920, 1080)):
        theme("light")
        edge.viewport(width, height)
        shot(f"accueil-{width}")
    overflow = edge.js("document.documentElement.scrollWidth - innerWidth")
    print("débordement horizontal :", overflow)
    errors = [line for line in edge.console if line.startswith(("error", "EXCEPTION"))]
    print("console :", errors or "propre")
finally:
    edge.close()
