"""Serveur local : garde-fous HTTP et parcours complet par l'API."""

import hashlib
import http.client
import json
import time
from pathlib import Path

import pymupdf as fitz
import pytest

from destripdf.server import AppState, LocalServer
from destripdf.settings import Settings
from destripdf.signing import pades, wincert
from tests import samples
from tests.pki import PFX_PASSWORD, make_test_pki


@pytest.fixture()
def server(tmp_path):
    identity = make_test_pki()
    state = AppState(
        Settings(tmp_path / "reglages"),
        store_factory=lambda: wincert.CertStore.from_pfx(identity.pfx, PFX_PASSWORD),
        mode="browser",
    )
    srv = LocalServer(state)
    srv.start()
    srv.identity = identity
    yield srv
    srv.shutdown()
    srv.server_close()
    if state.session:
        state.session.close()


def request(srv, method, path, body=None, *, token=True, host=None, headers=None, raw=False):
    port = srv.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    url = f"/{srv.token}/{path}" if token else path
    hdrs = {"Host": host or f"127.0.0.1:{port}"}
    if method != "GET":
        hdrs["X-DestriPDF"] = "1"
    data = None
    if body is not None:
        if isinstance(body, (bytes, bytearray)):
            data = bytes(body)
            hdrs["Content-Type"] = "application/pdf"
        else:
            data = json.dumps(body).encode()
            hdrs["Content-Type"] = "application/json"
    hdrs.update(headers or {})
    conn.request(method, url, body=data, headers=hdrs)
    resp = conn.getresponse()
    payload = resp.read()
    conn.close()
    if raw:
        return resp, payload
    return resp.status, (json.loads(payload) if payload and resp.getheader("Content-Type", "").startswith("application/json") else payload)


def test_security_guards(server):
    status, _ = request(server, "GET", "api/state")
    assert status == 200
    assert request(server, "GET", "/autre/api/state", token=False)[0] == 404
    assert request(server, "GET", "api/state", host="evil.example:80")[0] == 400
    # mutation sans en-tête applicatif ou depuis une autre origine
    assert request(server, "POST", "api/close", {}, headers={"X-DestriPDF": "0"})[0] == 403
    assert request(server, "POST", "api/close", {}, headers={"Origin": "http://evil.example"})[0] == 403
    assert request(server, "POST", "api/close", {}, headers={"Sec-Fetch-Site": "cross-site"})[0] == 403
    # pas de sortie du dossier statique
    assert request(server, "GET", "static/../server.py")[0] == 404
    assert request(server, "GET", "static/..%2Fserver.py")[0] == 404
    resp, body = request(server, "GET", "", raw=True)
    assert resp.status == 200 and b"DestriPDF" in body
    assert "default-src 'none'" in resp.getheader("Content-Security-Policy")
    assert resp.getheader("X-Content-Type-Options") == "nosniff"


def test_keep_alive_survives_unread_body(server):
    """Un corps JSON ignoré par la route ne doit pas corrompre la requête suivante."""
    port = server.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {"Host": f"127.0.0.1:{port}", "X-DestriPDF": "1", "Content-Type": "application/json"}
    for _ in range(3):
        conn.request("POST", f"/{server.token}/api/close", body=b'{"ignore": "moi"}', headers=headers)
        resp = conn.getresponse()
        assert resp.status == 200
        resp.read()
        conn.request("GET", f"/{server.token}/api/state", headers={"Host": f"127.0.0.1:{port}"})
        resp = conn.getresponse()
        assert resp.status == 200, resp.status
        assert json.loads(resp.read())["app"]["name"] == "DestriPDF"
    conn.close()


def test_full_workflow(server, tmp_path):
    source = tmp_path / "devis.pdf"
    source.write_bytes(samples.quote_pdf())
    status, data = request(server, "POST", "api/open", {"path": str(source)})
    assert status == 200, data
    doc = data["doc"]
    assert doc["page_count"] == 2 and doc["name"] == "devis.pdf" and not doc["dirty"]

    resp, png = request(server, "GET", f"api/page/0/image?d={doc['id']}&s=1.5&v={doc['pages'][0]['v']}", raw=True)
    assert resp.status == 200 and png.startswith(b"\x89PNG")
    assert "immutable" in resp.getheader("Cache-Control")
    # sans identifiant de document : servie, jamais mise en cache durablement
    resp, _ = request(server, "GET", f"api/page/0/image?s=1.5&v={doc['pages'][0]['v']}", raw=True)
    assert resp.status == 200 and resp.getheader("Cache-Control") == "no-store"
    # image d'un document déjà remplacé : refusée
    resp, _ = request(server, "GET", f"api/page/0/image?d=autre&s=1.5&v=1", raw=True)
    assert resp.status == 409

    status, text = request(server, "GET", "api/page/0/text")
    line = next(l for l in text["lines"] if l["text"] == "Date : 12/10/2026")
    span = line["spans"][0]
    status, data = request(server, "POST", "api/edit-line", {
        "page": 0,
        "line": {"bbox": line["bbox"], "text": line["text"]},
        "runs": [{"text": "Date : 30/10/2026", "family": span["family"], "size": span["size"], "color": span["color"]}],
        "align": "left",
    })
    assert status == 200, data
    assert data["doc"]["dirty"] and data["doc"]["undo_label"] == "Modification du texte"
    assert data["doc"]["pages"][0]["v"] > doc["pages"][0]["v"]

    status, data = request(server, "POST", "api/annot/add", {"page": 0, "annot": {"type": "note", "point": [300, 300], "content": "À vérifier"}})
    assert status == 200 and data["created"]
    status, annots = request(server, "GET", "api/annotations")
    assert annots["annots"][0]["content"] == "À vérifier"
    assert annots["annots"][0]["author"]  # auteur des réglages

    status, hits = request(server, "GET", "api/search?q=30/10/2026")
    assert len(hits["hits"]) == 1

    status, data = request(server, "POST", "api/undo")
    assert status == 200 and data["doc"]["redo_label"] == "Ajout d'une note"
    status, data = request(server, "POST", "api/redo")
    assert status == 200

    # « Enregistrer » d'un document ouvert depuis un chemin
    status, data = request(server, "POST", "api/save")
    assert status == 200 and not data["doc"]["dirty"]
    assert "Date : 30/10/2026" in fitz.open(source)[0].get_text()

    # signature (mode navigateur : chemin fourni)
    status, certs = request(server, "GET", "api/certificates")
    cert = certs["certificates"][0]
    assert cert["subject"] == "Florent TEST" and cert["qualified"]
    target = tmp_path / "devis - signé.pdf"
    status, data = request(server, "POST", "api/sign", {
        "certificate": cert["id"],
        "visible": {"page": 1, "rect": [320, 680, 540, 750]},
        "reason": "Bon pour accord",
        "location": "Zellwiller",
        "path": str(target),
    })
    assert status == 200, data
    assert data["doc"]["signed"] and data["doc"]["path"] == str(target)
    signed = target.read_bytes()
    report = pades.validate_signatures(signed, trust_check=lambda d: wincert.ChainResult(d, 0))[0]
    assert report.status == "valid" and report.reason == "Bon pour accord"
    assert source.read_bytes() != signed  # l'original reste intact

    deadline = time.time() + 20
    while True:
        status, sigs = request(server, "GET", "api/signatures")
        if not sigs["pending"] or time.time() > deadline:
            break
        time.sleep(0.2)
    assert sigs["reports"] and sigs["reports"][0]["signer"] == "Florent TEST"
    assert sigs["reports"][0]["status"] == "warning"  # racine de test non approuvée par Windows

    status, state = request(server, "GET", "api/state")
    assert state["recent"][0]["path"] == str(target)


def test_print_routes(server, tmp_path):
    from destripdf.printing import PrintError

    class Printing:
        jobs, prefs, booklets, paper = [], [], [], []
        fail = None

        def printers(self):
            return ["Bureau", "Atelier"], "Atelier"

        def capabilities(self, name):
            return {"duplex": name == "Atelier", "sheets": ["a4", "a3"]}

        def preferences(self, owner, name):
            Printing.prefs.append((owner, name))
            return True

        def print_document(self, name, copies, title, pages, page_size, render, output=None, sheet=None, duplex=None):
            if Printing.fail:
                raise Printing.fail
            assert render(pages[0], 0.1, 0)[1] > 0  # le rendu du document est bien transmis
            Printing.jobs.append((name, copies, title, pages, output))
            Printing.paper.append((sheet, duplex))

        def print_booklet(self, name, copies, title, sheet, impose, render_face, upside_down_backs=False, output=None):
            if Printing.fail:
                raise Printing.fail
            faces = impose(3.0)  # marge du pilote plus petite que la marge minimale du livret
            assert render_face(faces, 0, 0.1, 0)[1] > 0
            Printing.booklets.append((name, copies, sheet, faces.page_count, round(faces[0].rect.width), upside_down_backs, output))
            return faces.page_count

    class Dialogs:
        def owner_handle(self):
            return 4242

    server.app.printing = Printing()
    server.app.dialogs = Dialogs()
    status, data = request(server, "GET", "api/printers")
    assert status == 200 and data == {"printers": ["Bureau", "Atelier"], "default": "Atelier", "selected": "Atelier"}
    status, data = request(server, "GET", "api/printers/capabilities?printer=Atelier")
    assert status == 200 and data == {"printer": "Atelier", "duplex": True, "sheets": ["a4", "a3"], "flip_backs": False}
    assert request(server, "GET", "api/printers/capabilities?printer=Inconnue")[1]["code"] == "bad_printer"
    # sans document : rien à imprimer ni à mettre en livret
    assert request(server, "POST", "api/print", {"printer": "Bureau"})[0] == 409
    assert request(server, "GET", "api/print/booklet-plan")[0] == 409
    source = tmp_path / "devis.pdf"
    source.write_bytes(samples.quote_pdf())
    assert request(server, "POST", "api/open", {"path": str(source)})[0] == 200
    # garde-fous : sans en-tête applicatif ou depuis une autre origine, rien ne part
    assert request(server, "POST", "api/print", {"printer": "Bureau"}, headers={"X-DestriPDF": "0"})[0] == 403
    assert request(server, "POST", "api/print", {"printer": "Bureau"}, headers={"Origin": "http://evil.example"})[0] == 403
    assert request(server, "POST", "api/print/preferences", {"printer": "Bureau"}, headers={"X-DestriPDF": "0"})[0] == 403
    assert Printing.jobs == [] and Printing.prefs == []
    # imprimante inconnue du poste, pages, copies ou mise en page invalides : refus
    assert request(server, "POST", "api/print", {"printer": "\\\\autre\\imprimante"})[1]["code"] == "bad_printer"
    assert request(server, "POST", "api/print", {"printer": "Bureau", "pages": "3-4"})[1]["code"] == "bad_page"
    assert request(server, "POST", "api/print", {"printer": "Bureau", "pages": "a"})[1]["code"] == "bad_page"
    assert request(server, "POST", "api/print", {"printer": "Bureau", "copies": 0})[1]["code"] == "bad_copies"
    assert request(server, "POST", "api/print", {"printer": "Bureau", "pages": "current", "current": 5})[1]["code"] == "bad_page"
    assert request(server, "POST", "api/print", {"printer": "Bureau", "layout": "poster"})[1]["code"] == "bad_layout"
    assert request(server, "POST", "api/print", {"printer": "Atelier", "layout": "booklet", "sheet": "a5"})[1]["code"] == "bad_sheet"
    assert request(server, "POST", "api/print", {"printer": "Atelier", "layout": "booklet", "binding": "haut"})[1]["code"] == "bad_binding"
    assert request(server, "POST", "api/print", {"printer": "Bureau", "sheet": "a5"})[1]["code"] == "bad_sheet"
    assert request(server, "POST", "api/print", {"printer": "Bureau", "sheet": ["a4"]})[1]["code"] == "bad_sheet"
    assert request(server, "POST", "api/print", {"printer": "Bureau", "duplex": "both"})[1]["code"] == "bad_duplex"
    assert request(server, "POST", "api/print", {"printer": "Bureau", "duplex": 1})[1]["code"] == "bad_duplex"
    assert Printing.jobs == [] and Printing.booklets == []
    # préférences du pilote, ouvertes au-dessus de la fenêtre
    status, data = request(server, "POST", "api/print/preferences", {"printer": "Bureau"})
    assert status == 200 and data == {"changed": True} and Printing.prefs == [(4242, "Bureau")]
    status, data = request(server, "POST", "api/print", {"printer": "Bureau", "pages": "all", "copies": 2})
    assert status == 200 and data == {"pages": 2, "copies": 2, "layout": "normal", "sheet": None, "duplex": None}
    assert Printing.jobs[-1] == ("Bureau", 2, "devis.pdf", [0, 1], None)
    assert Printing.paper[-1] == (None, None)  # sans choix : réglages du pilote
    # papier et recto verso de la boîte Imprimer transmis au pilote
    status, data = request(server, "POST", "api/print", {"printer": "Atelier", "sheet": "a3", "duplex": "long"})
    assert status == 200 and data["sheet"] == "a3" and data["duplex"] == "long"
    assert Printing.paper[-1] == ("a3", "long")
    request(server, "POST", "api/print", {"printer": "Atelier", "sheet": "a4", "duplex": "simplex"})
    request(server, "POST", "api/print", {"printer": "Atelier", "duplex": "short"})
    assert Printing.paper[-2:] == [("a4", "simplex"), (None, "short")]
    del Printing.jobs[-3:]
    request(server, "POST", "api/print", {"printer": "Bureau", "pages": "current", "current": 1})
    request(server, "POST", "api/print", {"printer": "Bureau", "pages": "2, 1-1"})
    assert [job[3] for job in Printing.jobs[1:]] == [[1], [1, 0]]
    # plan du livret : 2 pages → 1 feuille, (blanche | 1) puis (2 | blanche) ; reliure à droite inversée
    status, data = request(server, "GET", "api/print/booklet-plan?pages=all")
    assert status == 200 and data == {"faces": [[None, 1], [2, None]], "sheets": 1, "pages": 2}
    assert request(server, "GET", "api/print/booklet-plan?pages=2&binding=right")[1]["faces"] == [[1 + 1, None], [None, None]]
    assert request(server, "GET", "api/print/booklet-plan?pages=9")[1]["code"] == "bad_page"
    assert request(server, "GET", "api/print/booklet-plan?binding=haut")[1]["code"] == "bad_binding"
    # livret : mis en page par DestriPDF, marge minimale gardée, versos retournés retenus par imprimante
    status, data = request(server, "POST", "api/print", {"printer": "Atelier", "layout": "booklet", "sheet": "a4",
                                                         "binding": "left", "flip_backs": True, "copies": 3})
    assert status == 200 and data == {"pages": 2, "copies": 3, "layout": "booklet", "sheets": 1, "faces": 2, "sheet": "a4"}
    assert Printing.booklets[-1] == ("Atelier", 3, "a4", 2, 842, True, None)
    assert request(server, "GET", "api/printers/capabilities?printer=Atelier")[1]["flip_backs"] is True
    request(server, "POST", "api/print", {"printer": "Atelier", "layout": "booklet", "sheet": "a3"})
    assert Printing.booklets[-1][2:6] == ("a3", 2, 1191, False)
    assert request(server, "GET", "api/printers/capabilities?printer=Atelier")[1]["flip_backs"] is False
    # dernière imprimante utilisée proposée la fois suivante
    request(server, "POST", "api/print", {"printer": "Bureau"})
    assert request(server, "GET", "api/printers")[1]["selected"] == "Bureau"
    Printing.fail = PrintError("Imprimante hors ligne.")
    status, data = request(server, "POST", "api/print", {"printer": "Bureau"})
    assert status == 400 and "hors ligne" in data["error"]
    status, data = request(server, "POST", "api/print", {"printer": "Atelier", "layout": "booklet"})
    assert status == 400 and data["code"] == "print_failed"
    Printing.fail = None
    # mode navigateur : ni préférences ni impression, sauf la recette qui imprime dans un fichier
    server.app.dialogs = None
    assert request(server, "POST", "api/print/preferences", {"printer": "Bureau"})[0] == 409
    assert request(server, "POST", "api/print", {"printer": "Bureau"})[1]["code"] == "no_dialog"
    server.app.print_output_dir = str(tmp_path)
    status, data = request(server, "POST", "api/print", {"printer": "Bureau"})
    assert status == 200 and data["output"].startswith(str(tmp_path)) and Printing.jobs[-1][4] == data["output"]
    status, data = request(server, "POST", "api/print", {"printer": "Atelier", "layout": "booklet"})
    assert status == 200 and Printing.booklets[-1][6] == data["output"]


def test_export_jpeg(server, tmp_path):
    from pathlib import Path

    source = tmp_path / "devis.pdf"
    source.write_bytes(samples.quote_pdf())
    assert request(server, "POST", "api/open", {"path": str(source)})[0] == 200
    # garde-fou : mutation sans en-tête applicatif, rien n'est écrit
    assert request(server, "POST", "api/export-jpeg", {"scope": "all", "path": str(tmp_path / "x.jpg")}, headers={"X-DestriPDF": "0"})[0] == 403
    assert not (tmp_path / "x.jpg").exists() and not (tmp_path / "x - page 1.jpg").exists()

    status, data = request(server, "POST", "api/export-jpeg", {"scope": "all", "dpi": 150, "path": str(tmp_path / "devis.jpg")})
    assert status == 200, data
    assert [Path(f).name for f in data["files"]] == ["devis - page 1.jpg", "devis - page 2.jpg"]
    assert all(Path(f).read_bytes()[:2] == b"\xff\xd8" for f in data["files"]) and not data["reduced"]

    status, data = request(server, "POST", "api/export-jpeg", {"scope": "current", "page": 1, "dpi": 300, "path": str(tmp_path / "seule")})
    assert status == 200 and data["files"] == [str(tmp_path / "seule.jpg")]
    assert fitz.Pixmap(str(tmp_path / "seule.jpg")).xres == 300

    assert request(server, "POST", "api/export-jpeg", {"dpi": 72, "path": str(tmp_path / "x.jpg")})[0] == 400
    assert request(server, "POST", "api/export-jpeg", {"page": 9, "path": str(tmp_path / "x.jpg")})[0] == 400
    # mode navigateur, sans dialogue Windows : le chemin est exigé
    assert request(server, "POST", "api/export-jpeg", {"scope": "all"})[0] == 409


def _bundle(*files):
    """Corps et requête d'un envoi de plusieurs PDF bout à bout (comme l'interface)."""
    from urllib.parse import quote

    names = quote(json.dumps([name for name, _ in files]))
    sizes = ",".join(str(len(data)) for _, data in files)
    return b"".join(data for _, data in files), f"sizes={sizes}&names={names}"


def _first_lines(server, count):
    lines = []
    for page in range(count):
        status, text = request(server, "GET", f"api/page/{page}/text")
        lines.append(text["lines"][0]["text"])
    return lines


def test_assembly_and_page_order_routes(server, tmp_path):
    body, query = _bundle(("02 - plan.pdf", samples.other_pdf(2, "Plan")), ("cctp.pdf", samples.other_pdf(1, "CCTP")))
    # sans document : rien à insérer ni à déplacer
    assert request(server, "POST", f"api/pages/insert-upload?{query}", body)[0] == 409
    assert request(server, "POST", "api/pages/move-many", {"pages": [0], "before": 1})[0] == 409
    # garde-fous : sans en-tête applicatif ou depuis une autre origine, rien n'est créé
    assert request(server, "POST", f"api/assemble-upload?{query}", body, headers={"X-DestriPDF": "0"})[0] == 403
    assert request(server, "POST", f"api/assemble-upload?{query}", body, headers={"Origin": "http://evil.example"})[0] == 403
    assert request(server, "GET", "api/state")[1]["doc"] is None
    # envoi incohérent, trop de fichiers, PDF illisible : refus
    assert request(server, "POST", "api/assemble-upload?sizes=10,20", body)[1]["code"] == "bad_request"
    assert request(server, "POST", "api/assemble-upload?sizes=a", body)[1]["code"] == "bad_request"
    assert request(server, "POST", f"api/assemble-upload?sizes={len(body)}&names=%7B", body)[1]["code"] == "bad_request"
    assert request(server, "POST", "api/assemble-upload?sizes=" + ",".join(["1"] * 101), b"x" * 101)[1]["code"] == "too_many"
    bad_body, bad_query = _bundle(("plan.pdf", samples.other_pdf(1)), ("note.pdf", b"pas un pdf"))
    status, data = request(server, "POST", f"api/assemble-upload?{bad_query}", bad_body)
    assert status == 400 and data["code"] == "not_pdf" and "« note.pdf »" in data["error"]

    # assemblage : nouveau document sans fichier, à enregistrer, signet par fichier
    status, data = request(server, "POST", f"api/assemble-upload?{query}", body)
    assert status == 200, data
    doc = data["doc"]
    assert data["assembled"] == 2 and data["signed_sources"] == []
    assert doc["name"] == "02 - plan - assemblé.pdf" and doc["path"] is None and doc["dirty"] and doc["page_count"] == 3
    assert doc["toc"] == [[1, "02 - plan", 0], [1, "cctp", 2]]
    assert request(server, "POST", "api/save")[1]["code"] == "need_path"

    # ajout de deux PDF en tête, en une seule étape d'annulation ; noms réduits à leur nom de fichier
    body2, query2 = _bundle(("C:\\dossier\\devis.pdf", samples.quote_pdf()), ("annexe.pdf", samples.other_pdf(1)))
    status, data = request(server, "POST", f"api/pages/insert-upload?at=0&{query2}", body2)
    assert status == 200, data
    assert data["inserted"] == {"start": 0, "count": 3, "files": 2} and data["doc"]["page_count"] == 6
    assert data["doc"]["undo_label"] == "Insertion de 2 PDF"
    assert _first_lines(server, 6) == ["DEVIS DEV-2026-042", "Conditions générales — page 2", "Annexe 1", "Plan 1", "Plan 2", "CCTP 1"]
    assert request(server, "POST", "api/undo")[1]["doc"]["page_count"] == 3
    assert request(server, "POST", "api/redo")[1]["doc"]["page_count"] == 6
    # un seul PDF sans « sizes » (ancien envoi) ; position invalide refusée
    assert request(server, "POST", "api/pages/insert-upload", samples.other_pdf(1, "Fin"))[1]["inserted"]["start"] == 6
    assert request(server, "POST", "api/pages/insert-upload?at=x", samples.other_pdf(1))[1]["code"] == "bad_page"
    status, data = request(server, "POST", f"api/pages/insert-upload?{bad_query}", bad_body)
    assert status == 400 and data["code"] == "not_pdf" and data.get("doc") is None
    assert request(server, "GET", "api/state")[1]["doc"]["page_count"] == 7

    # déplacement de plusieurs pages : les annexes « Plan » avant le devis
    assert request(server, "POST", "api/pages/move-many", {"pages": [4, 3], "before": 0}, headers={"X-DestriPDF": "0"})[0] == 403
    status, data = request(server, "POST", "api/pages/move-many", {"pages": [4, 3], "before": 0})
    assert status == 200 and data["moved"] == {"start": 0, "count": 2}
    assert data["doc"]["undo_label"] == "Déplacement de pages"
    assert _first_lines(server, 4) == ["Plan 1", "Plan 2", "DEVIS DEV-2026-042", "Conditions générales — page 2"]
    version = data["doc"]["version"]
    # déjà à leur place : aucune modification
    status, data = request(server, "POST", "api/pages/move-many", {"pages": [0, 1], "before": 2})
    assert status == 200 and data["doc"]["version"] == version
    for bad, code in (({"pages": [], "before": 0}, "empty"), ({"pages": "1", "before": 0}, "empty"),
                      ({"pages": [9], "before": 0}, "bad_page"), ({"pages": [0], "before": 99}, "bad_page"),
                      ({"pages": [0]}, "bad_request")):
        assert request(server, "POST", "api/pages/move-many", bad)[1]["code"] == code, bad

    # enregistrer sous : le document assemblé devient un fichier
    target = tmp_path / "dossier.pdf"
    status, data = request(server, "POST", "api/save-as", {"path": str(target)})
    assert status == 200 and not data["doc"]["dirty"] and fitz.open(target).page_count == 7


def test_files_are_sorted_like_explorer():
    from destripdf.server import sort_like_explorer

    names = ["plan 10.pdf", "Étude thermique.pdf", "Plan 2.pdf", "Devis.pdf", "Électricité.pdf"]
    assert [Path(p).name for p in sort_like_explorer([f"C:\\dossier\\{n}" for n in names])] == [
        "Devis.pdf", "Électricité.pdf", "Étude thermique.pdf", "Plan 2.pdf", "plan 10.pdf"]


def test_assembly_dialog_routes(server, tmp_path):
    files, written = {}, {}
    for name, data in (("10 - annexe.pdf", samples.other_pdf(1, "Annexe")), ("2 - plan.pdf", samples.other_pdf(1, "Plan")),
                       ("1 - devis.pdf", samples.quote_pdf())):
        files[name] = tmp_path / name
        files[name].write_bytes(data)
        written[name] = data

    class Dialogs:
        chosen = []
        saved = []

        def open_pdfs(self, directory):
            return list(Dialogs.chosen)

        def save_pdf(self, directory, filename):
            Dialogs.saved.append((directory, filename))
            return None

    # mode navigateur : pas de dialogue Windows
    assert request(server, "POST", "api/dialog/open-pdfs")[1]["code"] == "no_dialog"
    server.app.dialogs = Dialogs()
    assert request(server, "POST", "api/dialog/open-pdfs", headers={"X-DestriPDF": "0"})[0] == 403
    Dialogs.chosen = []
    assert request(server, "POST", "api/dialog/open-pdfs")[1] == {"cancelled": True}
    # rangés par nom comme dans l'Explorateur : 1, 2 puis 10
    Dialogs.chosen = [str(files["10 - annexe.pdf"]), str(files["2 - plan.pdf"]), str(files["1 - devis.pdf"])]
    status, data = request(server, "POST", "api/dialog/open-pdfs")
    assert status == 200 and [Path(p).name for p in data["paths"]] == ["1 - devis.pdf", "2 - plan.pdf", "10 - annexe.pdf"]
    # assemblage des fichiers choisis : refus sans chemin, fichier disparu, sans en-tête
    assert request(server, "POST", "api/assemble-files", {"paths": []})[1]["code"] == "empty"
    assert request(server, "POST", "api/assemble-files", {"paths": [1]})[1]["code"] == "empty"
    assert request(server, "POST", "api/assemble-files", {"paths": [str(tmp_path / "absent.pdf")]})[1]["code"] == "not_found"
    assert request(server, "POST", "api/assemble-files", {"paths": ["x.pdf"] * 101})[1]["code"] == "too_many"
    assert request(server, "POST", "api/assemble-files", {"paths": data["paths"]}, headers={"X-DestriPDF": "0"})[0] == 403
    assert request(server, "GET", "api/state")[1]["doc"] is None
    status, data = request(server, "POST", "api/assemble-files", {"paths": data["paths"]})
    assert status == 200, data
    assert data["doc"]["name"] == "1 - devis - assemblé.pdf" and data["doc"]["dirty"]
    assert [entry[1] for entry in data["doc"]["toc"]] == ["1 - devis", "2 - plan", "10 - annexe"]
    # les sources ne changent pas ; « Enregistrer sous » propose leur dossier
    assert all(files[name].read_bytes() == content for name, content in written.items())
    assert request(server, "POST", "api/dialog/save-pdf", {"name": "..\\dossier.pdf"})[1] == {"cancelled": True}
    assert Dialogs.saved == [(str(tmp_path), "dossier.pdf")]
    status, data = request(server, "POST", "api/pages/insert-files", {"paths": [str(files["2 - plan.pdf"])], "at": 1})
    assert status == 200 and data["inserted"] == {"start": 1, "count": 1, "files": 1}
    assert request(server, "POST", "api/pages/insert-files", {"paths": [str(files["2 - plan.pdf"])], "at": "x"})[1]["code"] == "bad_page"
    assert request(server, "POST", "api/pages/insert-files", {"paths": [str(tmp_path / "absent.pdf")]})[1]["code"] == "not_found"
    assert request(server, "GET", "api/state")[1]["doc"]["page_count"] == 5


def test_compress_routes(server, tmp_path):
    from destripdf.document import PdfSession

    assert request(server, "GET", "api/compress/estimate?level=screen")[0] == 409
    source = tmp_path / "chantier.pdf"
    original = samples.photo_pdf(400)
    source.write_bytes(original)
    assert request(server, "POST", "api/open", {"path": str(source)})[0] == 200
    assert request(server, "GET", "api/compress/estimate?level=extreme")[1]["code"] == "bad_level"
    status, data = request(server, "GET", "api/compress/estimate?level=screen")
    assert status == 200 and data["before"] == len(original) and data["after"] < len(original) / 4
    # garde-fous : rien n'est écrit sans en-tête applicatif
    target = tmp_path / "chantier - compressé.pdf"
    assert request(server, "POST", "api/compress/save", {"level": "screen", "path": str(target)}, headers={"X-DestriPDF": "0"})[0] == 403
    assert not target.exists()
    # sans chemin (dialogue annulé ou chemin non saisi) : refus explicite
    assert request(server, "POST", "api/compress/save", {"level": "screen"})[1]["code"] == "need_path"
    assert request(server, "POST", "api/compress/save", {"level": "fort", "path": str(target)})[1]["code"] == "bad_level"
    status, data = request(server, "POST", "api/compress/save", {"level": "screen", "path": str(target)})
    assert status == 200 and "doc" not in data and data["after"] == target.stat().st_size < len(original)
    assert "Photo du chantier" in fitz.open(target)[0].get_text()
    assert source.read_bytes() == original  # l'original reste intact
    # dialogue Windows : nom proposé dans le dossier du document
    proposed = []

    class Dialogs:
        def save_pdf(self, directory, filename):
            proposed.append((directory, filename))
            return str(source)

    assert request(server, "POST", "api/dialog/save-pdf", {"name": "chantier - compressé.pdf"})[1]["code"] == "no_dialog"
    server.app.dialogs = Dialogs()
    assert request(server, "POST", "api/dialog/save-pdf", {"name": "chantier - compressé.pdf"})[1] == {"path": str(source)}
    assert proposed == [(str(tmp_path), "chantier - compressé.pdf")]
    # fichier du document remplacé par sa version compressée : le document ouvert la reprend
    status, data = request(server, "POST", "api/compress/save", {"level": "minimum", "path": str(source)})
    assert status == 200 and data["doc"]["path"] == str(source) and not data["doc"]["dirty"]
    assert source.stat().st_size == data["after"] < target.stat().st_size
    # aucun gain : rien n'est écrit
    session = server.app.session
    session.compressed_bytes = lambda level: b"%PDF" + b"0" * (len(session.original) + 10)
    server.app.compressed = {"key": None, "levels": {}, "before": None}
    status, data = request(server, "POST", "api/compress/save", {"level": "print", "path": str(tmp_path / "rien.pdf")})
    assert status == 400 and data["code"] == "no_gain" and not (tmp_path / "rien.pdf").exists()
    # document signé : refus, la compression invaliderait ses signatures
    identity = server.identity
    signed, _ = pades.sign_pdf(original, pades.SignOptions(thumbprint=hashlib.sha1(identity.der).hexdigest()),
                               store_factory=lambda: wincert.CertStore.from_pfx(identity.pfx, PFX_PASSWORD))
    (tmp_path / "signé.pdf").write_bytes(signed)
    assert request(server, "POST", "api/open", {"path": str(tmp_path / "signé.pdf")})[0] == 200
    status, data = request(server, "GET", "api/compress/estimate?level=screen")
    assert status == 400 and data["code"] == "signed"
    assert isinstance(server.app.session, PdfSession)


def test_password_flow(server, tmp_path):
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Secret")
    path = tmp_path / "secret.pdf"
    path.write_bytes(doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="1234", owner_pw="o"))
    status, data = request(server, "POST", "api/open", {"path": str(path)})
    assert status == 400 and data["code"] == "password"
    status, data = request(server, "POST", "api/password", {"password": "faux"})
    assert status == 400 and data["code"] == "password" and "incorrect" in data["error"]
    status, data = request(server, "POST", "api/password", {"password": "1234"})
    assert status == 200 and data["doc"]["encrypted"]


def test_upload_and_errors(server):
    status, data = request(server, "POST", "api/upload?name=depose.pdf", samples.other_pdf(1))
    assert status == 200 and data["doc"]["name"] == "depose.pdf" and data["doc"]["path"] is None
    status, data = request(server, "POST", "api/save")
    assert status == 409 and data["code"] == "need_path"
    status, data = request(server, "POST", "api/upload?name=faux.pdf", b"pas un pdf")
    assert status == 400 and data["code"] == "not_pdf"
    status, data = request(server, "GET", "api/page/99/text")
    assert status == 400 and data["code"] == "bad_page"
    status, data = request(server, "POST", "api/edit-line", {"page": 0})
    assert status == 400 and data["code"] == "bad_request"


def test_signature_image_settings(server):
    status, data = request(server, "GET", "api/signature-image")
    assert status == 404
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 20, 10), False)
    png = pix.tobytes("png")
    port = server.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("POST", f"/{server.token}/api/signature-image", body=png,
                 headers={"Host": f"127.0.0.1:{port}", "X-DestriPDF": "1", "Content-Type": "image/png"})
    resp = conn.getresponse()
    assert resp.status == 200 and json.loads(resp.read())["settings"]["has_signature_image"]
    status, data = request(server, "POST", "api/settings", {"author": "Florent", "timestamp_url": "ftp://x"})
    assert status == 400 and data["code"] == "bad_setting"
    status, data = request(server, "POST", "api/settings", {"author": "Florent", "theme": "dark"})
    assert data["settings"]["author"] == "Florent" and data["settings"]["theme"] == "dark"
