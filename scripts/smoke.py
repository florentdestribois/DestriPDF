"""Test de fumée d'une instance lancée en mode recette (--serve), y compris l'exécutable figé.

Usage : python scripts/smoke.py http://127.0.0.1:8791/recette/ <dossier de travail>
Le dossier contient devis.pdf ; l'instance a été lancée avec DESTRIPDF_TEST_PFX.
"""

from __future__ import annotations

import http.client
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit


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
        deadline = time.time() + 30
        reports = []
        while time.time() < deadline:
            status, sigs = c.call("GET", "api/signatures")
            if not sigs.get("pending"):
                reports = sigs.get("reports", [])
                break
            time.sleep(0.3)
        check("vérification de la signature", bool(reports) and reports[0]["intact"] and reports[0]["valid"], str(reports)[:300])
    failed = [name for name, ok, _ in checks if not ok]
    print(f"\n{len(checks) - len(failed)} / {len(checks)} contrôles réussis")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
