"""Test de fumée d'une instance lancée en mode recette (--serve), y compris l'exécutable figé.

Usage : python scripts/smoke.py http://127.0.0.1:8791/recette/ <dossier de travail>
Le dossier contient devis.pdf ; l'instance a été lancée avec DESTRIPDF_TEST_PFX.
Si le dossier contient crl/ (echantillons.py --crl-port), une autorité simulée
publie les listes de révocation : la signature doit intégrer leur état (LTV).
"""

from __future__ import annotations

import http.client
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlsplit


def serve_crls(crl_dir: Path) -> ThreadingHTTPServer:
    """Autorité simulée : sert les listes de révocation du certificat de test."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = crl_dir / Path(self.path).name
            if path.suffix != ".crl" or not path.is_file():
                self.send_error(404)
                return
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/pkix-crl")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    port = int((crl_dir / "port").read_text(encoding="ascii"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class Client:
    def __init__(self, base: str):
        parts = urlsplit(base)
        self.host, self.port = parts.hostname, parts.port
        self.prefix = parts.path.rstrip("/") + "/"

    def call(self, method: str, path: str, body=None, raw: bool = False):
        conn = http.client.HTTPConnection(self.host, self.port, timeout=60)
        headers = {"Host": f"{self.host}:{self.port}"}
        data = None
        if method != "GET":
            headers["X-DestriPDF"] = "1"
            headers["Content-Type"] = "application/json"
            data = json.dumps(body or {}).encode()
        conn.request(method, self.prefix + path, body=data, headers=headers)
        resp = conn.getresponse()
        payload = resp.read()
        conn.close()
        if raw:
            return resp.status, payload, resp.getheader("Content-Type")
        try:
            return resp.status, json.loads(payload)
        except ValueError:
            return resp.status, payload


def main(base: str, workdir: str) -> int:
    work = Path(workdir)
    c = Client(base)
    checks: list[tuple[str, bool, str]] = []
    authority = serve_crls(work / "crl") if (work / "crl" / "port").exists() else None

    def check(name: str, ok: bool, detail: str = ""):
        checks.append((name, bool(ok), detail))
        print(("[OK] " if ok else "[ÉCHEC] ") + name + (f" — {detail}" if detail and not ok else ""))

    status, body, ctype = c.call("GET", "", raw=True)
    check("page d'accueil", status == 200 and b"DestriPDF" in body)
    for asset in ("static/app.css", "static/js/app.js", "static/fonts/Roboto-Regular.ttf", "static/icon.svg"):
        status, body, ctype = c.call("GET", asset, raw=True)
        check(f"ressource {asset}", status == 200 and len(body) > 100, f"{status}")
    status, data = c.call("POST", "api/open", {"path": str(work / "devis.pdf")})
    check("ouverture", status == 200, str(data)[:200])
    doc = data.get("doc", {})
    status, body, ctype = c.call("GET", f"api/page/0/image?s=1.5&v={doc['pages'][0]['v']}", raw=True)
    check("rendu de page", status == 200 and body[:4] in (b"\x89PNG", b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1", b"\xff\xd8\xff\xdb"), ctype)
    status, text = c.call("GET", "api/page/0/text")
    line = next((l for l in text.get("lines", []) if l["text"].startswith("Date")), None)
    check("extraction du texte", line is not None)
    span = line["spans"][0]
    status, data = c.call("POST", "api/edit-line", {
        "page": 0, "line": {"bbox": line["bbox"], "text": line["text"]},
        "runs": [{"text": "Date : 01/12/2026", "family": span["family"], "size": span["size"], "color": span["color"]}],
    })
    check("modification d'une ligne (sous-ensemble de police)", status == 200, str(data)[:200])
    status, data = c.call("POST", "api/annot/add", {"page": 0, "annot": {"type": "freetext", "rect": [60, 400, 300, 430], "content": "Bon pour accord — 1 520,00 €"}})
    check("texte ajouté", status == 200, str(data)[:200])
    target = work / "devis-fumee.pdf"
    status, data = c.call("POST", "api/save-as", {"path": str(target)})
    check("enregistrer sous", status == 200 and target.exists(), str(data)[:200])
    # Impression : imprimantes, capacités des pilotes (.NET System.Printing
    # embarqué), puis envoi réel au pilote « Microsoft Print to PDF » dans un fichier.
    status, printers = c.call("GET", "api/printers")
    check("imprimantes du poste", status == 200 and isinstance(printers, dict) and printers.get("printers"), str(printers)[:200])
    names = printers.get("printers", []) if isinstance(printers, dict) else []
    caps_ok = True
    for name in names:
        status, caps = c.call("GET", f"api/printers/capabilities?printer={quote(name)}")
        caps_ok = caps_ok and (status == 200 or (isinstance(caps, dict) and caps.get("code") == "print_failed"))
    check("capacités des pilotes (formats, recto verso)", caps_ok)
    if "Microsoft Print to PDF" in names:
        status, data = c.call("POST", "api/print", {"printer": "Microsoft Print to PDF", "pages": "all"})
        output = Path(data.get("output", "")) if isinstance(data, dict) else Path()
        deadline = time.time() + 30
        while status == 200 and not (output.is_file() and output.stat().st_size > 0) and time.time() < deadline:
            time.sleep(0.3)
        check("impression par le pilote Windows", status == 200 and output.is_file() and output.read_bytes()[:5] == b"%PDF-", str(data)[:200])
        # Livret mis en page par DestriPDF : faces tournées sur des feuilles A4 portrait.
        status, data = c.call("POST", "api/print", {"printer": "Microsoft Print to PDF", "pages": "all", "layout": "booklet", "sheet": "a4"})
        output = Path(data.get("output", "")) if isinstance(data, dict) else Path()
        deadline = time.time() + 30
        while status == 200 and not (output.is_file() and output.stat().st_size > 0) and time.time() < deadline:
            time.sleep(0.3)
        time.sleep(0.5)
        faces = []
        if output.is_file():
            import pymupdf

            with pymupdf.open(output) as printed:
                faces = [(page.rect.width, page.rect.height) for page in printed]
        check("livret mis en page par DestriPDF",
              status == 200 and len(faces) == data.get("faces") == 2 * data.get("sheets", 0) > 0
              and all(h > w and abs(h - 842) < 3 for w, h in faces), f"{str(data)[:200]} {faces}")
    status, certs = c.call("GET", "api/certificates")
    ok = status == 200 and certs.get("certificates")
    check("certificats (magasin Windows / PFX de recette)", ok, str(certs)[:200])
    if ok:
        signed = work / "devis-fumee - signé.pdf"
        status, data = c.call("POST", "api/sign", {
            "certificate": certs["certificates"][0]["id"],
            "visible": {"page": 0, "rect": [330, 700, 545, 780]},
            "reason": "Test de fumée", "location": "Zellwiller", "path": str(signed),
        })
        check("signature PAdES visible", status == 200 and signed.exists(), str(data)[:300])
        if authority is not None:
            signature = data.get("signature", {}) if isinstance(data, dict) else {}
            check("état de révocation intégré (LTV, autorité simulée)", signature.get("ltv") is True, str(signature)[:300])
        deadline = time.time() + 30
        reports = []
        while time.time() < deadline:
            status, sigs = c.call("GET", "api/signatures")
            if not sigs.get("pending"):
                reports = sigs.get("reports", [])
                break
            time.sleep(0.3)
        check("vérification de la signature", bool(reports) and reports[0]["intact"] and reports[0]["valid"], str(reports)[:300])
        if authority is not None:
            check("signature vérifiable hors ligne (LTV)", bool(reports) and reports[0].get("ltv") is True, str(reports)[:300])
    if authority is not None:
        authority.shutdown()
        authority.server_close()
    failed = [name for name, ok, _ in checks if not ok]
    print(f"\n{len(checks) - len(failed)} / {len(checks)} contrôles réussis")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
