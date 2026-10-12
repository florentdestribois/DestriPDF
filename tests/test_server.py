"""Serveur local : garde-fous HTTP et parcours complet par l'API."""

import hashlib
import http.client
import json
import time

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
