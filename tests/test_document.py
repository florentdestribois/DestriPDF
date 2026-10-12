"""Opérations du document : texte, annotations, pages, historique, enregistrement."""

import hashlib

import pymupdf as fitz
import pytest

from destripdf import document as d
from destripdf.signing import pades, wincert
from tests import samples
from tests.pki import PFX_PASSWORD, make_test_pki


def _line(session, page, text):
    for line in session.page_text(page)["lines"]:
        if line["text"] == text:
            return line
    raise AssertionError(f"ligne absente : {text!r} parmi {[l['text'] for l in session.page_text(page)['lines']]}")


def _texts(session, page=0):
    return [l["text"] for l in session.page_text(page)["lines"]]


def _edit(session, page, line, new_text, **kw):
    span = line["spans"][0]
    run = d.Run(text=new_text, family=span["family"], size=span["size"], color=span["color"], bold=span["bold"], italic=span["italic"])
    return session.edit_line(page, d.LineRef(tuple(line["bbox"]), line["text"]), [run], **kw)


def test_text_segments_split_table_columns_and_detect_alignment():
    s = d.PdfSession(samples.quote_pdf(), name="devis.pdf")
    texts = _texts(s)
    assert "Porte chêne 93 x 204" in texts and "1 250,00 €" in texts
    amount = _line(s, 0, "1 250,00 €")
    assert amount["align"] == "right"
    assert amount["editable"]
    assert amount["spans"][0]["family"] == "Arial"
    assert _line(s, 0, "Client : Mairie de Zellwiller")["align"] == "left"


def test_reading_never_modifies_the_document():
    """Affichage, texte, recherche et rendu ne touchent aucun objet, même /Rotate hérité."""
    doc = fitz.open(stream=samples.quote_pdf(), filetype="pdf")
    kind, pages_ref = doc.xref_get_key(doc.pdf_catalog(), "Pages")
    pages_xref = int(pages_ref.split()[0])
    for page in doc:
        doc.xref_set_key(page.xref, "Rotate", "null")  # aucune rotation propre à la page
    doc.xref_set_key(pages_xref, "Rotate", "90")  # rotation héritée par toutes les pages
    data = doc.tobytes()
    s = d.PdfSession(data, name="herite.pdf")
    assert s.doc[0].rotation == 90
    page_xref = s.doc[0].xref
    before = s.doc.xref_object(page_xref)
    texts = _texts(s)
    assert "Client : Mairie de Zellwiller" in texts
    assert s.search("Zellwiller")
    s.render(0, 1.0)
    s.annotations(0)
    s.form_fields(0)
    assert s.doc.xref_object(page_xref) == before
    assert "/Rotate 90" not in s.doc.xref_object(page_xref)  # aucune rotation recopiée sur la page
    assert not s.dirty


def test_annotation_and_field_text_is_not_page_text():
    s = d.PdfSession(samples.form_pdf(), name="dc1.pdf")
    field = s.form_fields(0)[0]
    s.set_field(0, field["id"], "Valeur du champ")
    s.add_annotation(0, {"type": "freetext", "rect": [60, 400, 300, 430], "content": "Texte ajouté"})
    texts = _texts(s)
    assert "Valeur du champ" not in texts and "Texte ajouté" not in texts
    # la recherche, elle, trouve aussi les annotations
    assert s.search("Texte ajouté")


def test_edit_line_replaces_text_and_keeps_neighbours_graphics_images():
    s = d.PdfSession(samples.quote_pdf(), name="devis.pdf")
    drawings_before = len(s.doc[0].get_drawings())
    images_before = len(s.doc[0].get_images())
    _edit(s, 0, _line(s, 0, "Date : 12/10/2026"), "Date : 15/10/2026 — révisé")
    texts = _texts(s)
    assert "Date : 15/10/2026 — révisé" in texts
    assert "Date : 12/10/2026" not in texts
    for keep in ("Client : Mairie de Zellwiller", "Objet : Remplacement des portes du préau", "DEVIS DEV-2026-042"):
        assert keep in texts
    assert len(s.doc[0].get_drawings()) == drawings_before
    assert len(s.doc[0].get_images()) == images_before
    assert s.dirty and s.history.can_undo()
    new = _line(s, 0, "Date : 15/10/2026 — révisé")
    old_line_y = 138
    assert abs(new["spans"][0]["origin"][1] - old_line_y) < 0.6  # même ligne de base


def test_edit_amount_right_aligned_keeps_column_edge():
    s = d.PdfSession(samples.quote_pdf(), name="devis.pdf")
    line = _line(s, 0, "1 250,00 €")
    _edit(s, 0, line, "12 500,00 €", align="right")
    new = _line(s, 0, "12 500,00 €")
    assert abs(new["bbox"][2] - line["bbox"][2]) < 1.0
    assert "Porte chêne 93 x 204" in _texts(s)
    assert "480,00 €" in _texts(s)


def test_delete_line_with_empty_runs():
    s = d.PdfSession(samples.quote_pdf(), name="devis.pdf")
    line = _line(s, 0, "Pose et ajustage")
    s.edit_line(0, d.LineRef(tuple(line["bbox"]), line["text"]), [])
    assert "Pose et ajustage" not in _texts(s)
    assert "480,00 €" in _texts(s)


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_edit_on_rotated_page_keeps_orientation(rotation):
    s = d.PdfSession(samples.rotated_pdf(rotation), name="plan.pdf")
    line = _line(s, 0, "Plan de pose niveau 1")
    assert line["editable"] and abs(line["angle"]) < 0.5
    _edit(s, 0, line, "Plan de pose niveau 2")
    new = _line(s, 0, "Plan de pose niveau 2")
    assert abs(new["angle"]) < 0.5
    assert abs(new["bbox"][0] - line["bbox"][0]) < 1.5
    assert abs(new["bbox"][3] - line["bbox"][3]) < 2.5


def test_stale_line_is_refused():
    s = d.PdfSession(samples.quote_pdf(), name="devis.pdf")
    with pytest.raises(d.DocumentError) as err:
        s.edit_line(0, d.LineRef((300, 600, 400, 620), "inexistant"), [d.Run("x")])
    assert err.value.code == "stale"
    assert not s.dirty


def test_undo_redo_text_edit():
    s = d.PdfSession(samples.quote_pdf(), name="devis.pdf")
    _edit(s, 0, _line(s, 0, "Date : 12/10/2026"), "Date : 01/01/2027")
    s.undo()
    assert "Date : 12/10/2026" in _texts(s) and not s.dirty
    s.redo()
    assert "Date : 01/01/2027" in _texts(s) and s.dirty


def test_annotations_lifecycle():
    s = d.PdfSession(samples.quote_pdf(), name="devis.pdf")
    created = {}
    for spec in (
        {"type": "note", "point": [300, 300], "content": "Vérifier la cote 93", "author": "Florent"},
        {"type": "freetext", "rect": [60, 400, 300, 430], "content": "Bon pour accord — 1 250,00 €", "fontsize": 12, "color": "#1a2b3c"},
        {"type": "highlight", "rects": [[56, 100, 230, 114]], "color": "#f5d04a"},
        {"type": "underline", "rects": [[56, 114, 300, 128]]},
        {"type": "strikeout", "rects": [[56, 128, 200, 142]]},
        {"type": "ink", "strokes": [[[100, 500], [150, 520], [200, 500]]], "width": 2, "color": "#b4503c"},
        {"type": "rect", "rect": [60, 550, 200, 600]},
        {"type": "ellipse", "rect": [220, 550, 360, 600]},
        {"type": "arrow", "from": [400, 600], "to": [500, 550]},
    ):
        out = s.add_annotation(0, spec)
        created[spec["type"]] = out["created"]
    items = s.annotations(0)
    kinds = sorted(i["type"] for i in items)
    assert kinds == sorted(["Text", "FreeText", "Highlight", "Underline", "StrikeOut", "Ink", "Square", "Circle", "Line"])
    note = next(i for i in items if i["type"] == "Text")
    assert note["content"] == "Vérifier la cote 93" and note["author"] == "Florent"
    free = next(i for i in items if i["type"] == "FreeText")
    assert free["content"] == "Bon pour accord — 1 250,00 €"
    assert abs(free["fontsize"] - 12) < 0.01
    # contenu, déplacement, couleur
    s.update_annotation(0, created["note"], {"content": "Cote validée"})
    s.update_annotation(0, created["freetext"], {"offset": [10, 20]})
    s.update_annotation(0, created["ink"], {"offset": [5, 5]})
    s.update_annotation(0, created["arrow"], {"offset": [-10, 0], "color": "#287a5d"})
    items = {i["type"]: i for i in s.annotations(0)}
    assert items["Text"]["content"] == "Cote validée"
    assert abs(items["FreeText"]["rect"][0] - 70) < 0.5 and abs(items["FreeText"]["rect"][1] - 420) < 0.5
    assert items["Line"]["color"] == "#287a5d"
    # suppression puis annulation
    s.delete_annotation(0, items["Square"]["id"])
    assert "Square" not in {i["type"] for i in s.annotations(0)}
    s.undo()
    assert "Square" in {i["type"] for i in s.annotations(0)}
    assert len(s.all_annotations()) == 9


def test_freetext_box_never_wraps_a_line():
    s = d.PdfSession(samples.quote_pdf(), name="devis.pdf")
    text = "Bon pour accord — 1 520,00 €"
    s.add_annotation(0, {"type": "freetext", "rect": [60, 400, 110, 410], "content": text, "fontsize": 12})
    rendered = s.doc[0].get_text("text")  # inclut l'apparence des annotations
    assert text in rendered.replace("\xa0", " ")
    free = next(a for a in s.annotations(0) if a["type"] == "FreeText")
    assert free["rect"][2] - free["rect"][0] > 150


def test_freetext_keeps_euro_after_save(tmp_path):
    s = d.PdfSession(samples.quote_pdf(), name="devis.pdf")
    s.add_annotation(0, {"type": "freetext", "rect": [60, 400, 360, 430], "content": "Montant : 1 250,00 € — Œuvre", "fontsize": 12})
    target = tmp_path / "annote.pdf"
    s.save(str(target))
    doc = fitz.open(target)
    annot = next(doc[0].annots())
    assert annot.info["content"] == "Montant : 1 250,00 € — Œuvre"


def test_signature_image_upright_on_rotated_page():
    """L'image apposée sur une page pivotée s'affiche droite (bandeau rouge en haut)."""
    img = fitz.open()
    p = img.new_page(width=200, height=70)
    p.draw_rect(fitz.Rect(0, 0, 200, 14), color=(1, 0, 0), fill=(1, 0, 0))
    png = p.get_pixmap(alpha=False).tobytes("png")
    s = d.PdfSession(samples.rotated_pdf(), name="plan.pdf")
    s.add_annotation(0, {"type": "stamp_image", "rect": [100, 100, 300, 170], "image": png})
    stamp = next(a for a in s.annotations(0) if a["type"] == "Stamp")
    x0, y0, x1, y1 = stamp["rect"]
    assert x1 - x0 > y1 - y0  # cadre affiché plus large que haut
    pix = s.doc[0].get_pixmap(clip=fitz.Rect(x0, y0, x1, y1) * s.doc[0].derotation_matrix)
    # rendu affiché : la page pivotée se dessine tournée ; on lit le rendu complet
    full = s.doc[0].get_pixmap()
    top_row = [full.pixel(int(x), int(y0 + 3)) for x in range(int(x0) + 5, int(x1) - 5, 10)]
    left_col = [full.pixel(int(x0 + 3), int(y)) for y in range(int(y0) + 20, int(y1) - 5, 5)]
    red = lambda c: c[0] > 200 and c[1] < 80 and c[2] < 80  # noqa: E731
    assert sum(map(red, top_row)) >= len(top_row) * 0.8
    assert sum(map(red, left_col)) <= 1
    assert pix.width > 0


def test_annotations_land_where_drawn_on_rotated_page():
    s = d.PdfSession(samples.rotated_pdf(), name="plan.pdf")
    shown = {
        "highlight": [100, 200, 300, 214],
        "rect": [400, 300, 500, 360],
    }
    s.add_annotation(0, {"type": "highlight", "rects": [shown["highlight"]]})
    s.add_annotation(0, {"type": "rect", "rect": shown["rect"], "width": 1})
    s.add_annotation(0, {"type": "ink", "strokes": [[[600, 100], [650, 150], [700, 100]]], "width": 1})
    s.add_annotation(0, {"type": "arrow", "from": [100, 500], "to": [250, 450], "width": 1})
    s.add_annotation(0, {"type": "note", "point": [700, 500], "content": "ici"})
    items = {a["type"]: a["rect"] for a in s.annotations(0)}

    def near(a, b, tol):
        return all(abs(x - y) <= tol for x, y in zip(a, b))

    # MuPDF arrondit les extrémités d'un surlignage : léger débord horizontal.
    assert near(items["Highlight"], shown["highlight"], 4), items["Highlight"]
    assert near(items["Square"], shown["rect"], 3), items["Square"]
    # Tracé et flèche : MuPDF ajoute une marge autour du cadre, le centre fait foi.
    def center(r):
        return [(r[0] + r[2]) / 2, (r[1] + r[3]) / 2]

    assert near(center(items["Ink"]), [650, 125], 2), items["Ink"]
    assert near(center(items["Line"]), [175, 475], 2), items["Line"]
    assert near(items["Text"][:2], [700, 500], 25), items["Text"]


def test_erase_zone_removes_content():
    s = d.PdfSession(samples.quote_pdf(), name="devis.pdf")
    s.erase(0, [50, 98, 400, 126])
    texts = _texts(s)
    assert "Client : Mairie de Zellwiller" not in texts
    assert "Objet : Remplacement des portes du préau" not in texts
    assert "Date : 12/10/2026" in texts
    assert len(s.doc[0].get_images()) == 1


def test_page_operations_and_undo():
    s = d.PdfSession(samples.quote_pdf(), name="devis.pdf")
    s.rotate_pages([1], 90)
    assert s.doc[1].rotation == 90
    s.insert_pdf(samples.other_pdf(2), at=1)
    assert s.doc.page_count == 4
    assert "Annexe 1" in _texts(s, 1)
    s.move_page(3, 0)
    assert "Conditions générales — page 2" in _texts(s, 0)
    s.delete_pages([0])
    assert s.doc.page_count == 3
    with pytest.raises(d.DocumentError):
        s.delete_pages([0, 1, 2])
    for _ in range(4):
        s.undo()
    assert s.doc.page_count == 2 and s.doc[1].rotation == 0 and not s.dirty


def test_move_page_forward():
    s = d.PdfSession(samples.other_pdf(4), name="annexes.pdf")
    s.move_page(0, 2)
    assert [_texts(s, i)[0] for i in range(4)] == ["Annexe 2", "Annexe 3", "Annexe 1", "Annexe 4"]
    s.move_page(2, 3)
    assert [_texts(s, i)[0] for i in range(4)] == ["Annexe 2", "Annexe 3", "Annexe 4", "Annexe 1"]


def test_search_and_render():
    s = d.PdfSession(samples.quote_pdf(), name="devis.pdf")
    hits = s.search("zellwiller")
    assert len(hits) == 1 and hits[0]["page"] == 0
    png, mime = s.render(0, 1.5)
    assert mime == "image/png" and png.startswith(b"\x89PNG")
    pix = fitz.Pixmap(png)
    assert pix.width == round(595 * 1.5) or abs(pix.width - 595 * 1.5) <= 1


def test_save_full_and_reopen(tmp_path):
    s = d.PdfSession(samples.quote_pdf(), name="devis.pdf")
    _edit(s, 0, _line(s, 0, "Date : 12/10/2026"), "Date : 20/10/2026")
    target = tmp_path / "devis.pdf"
    s.save(str(target))
    assert not s.dirty and s.path == str(target)
    reopened = d.PdfSession(target.read_bytes(), path=str(target))
    assert "Date : 20/10/2026" in _texts(reopened)
    # la police ajoutée est un sous-ensemble : le fichier reste léger
    assert target.stat().st_size < 120_000


def test_signed_document_keeps_signature_on_save(tmp_path):
    identity = make_test_pki()
    factory = lambda: wincert.CertStore.from_pfx(identity.pfx, PFX_PASSWORD)  # noqa: E731
    signed, _ = pades.sign_pdf(
        samples.quote_pdf(),
        pades.SignOptions(thumbprint=hashlib.sha1(identity.der).hexdigest()),
        store_factory=factory,
    )
    s = d.PdfSession(signed, name="signe.pdf")
    assert s.signed_original
    s.add_annotation(0, {"type": "note", "point": [300, 300], "content": "Reçu le 12/10"})
    target = tmp_path / "signe-annote.pdf"
    s.save(str(target))
    data = target.read_bytes()
    assert data.startswith(signed)
    report = pades.validate_signatures(data, trust_check=lambda ders: wincert.ChainResult(ders, 0))[0]
    assert report.intact and report.valid
    # pyHanko qualifie tout ajout d'annotation de modification : la signature reste intègre.
    assert report.modification and not report.covers_whole_file
    # seconde modification : la base devient le fichier enregistré
    s.add_annotation(0, {"type": "rect", "rect": [60, 550, 200, 600]})
    s.save(str(target))
    data2 = target.read_bytes()
    assert data2.startswith(data)
    assert pades.validate_signatures(data2, trust_check=lambda ders: wincert.ChainResult(ders, 0))[0].intact


def test_signed_document_without_sigflags_is_still_detected(tmp_path):
    identity = make_test_pki()
    factory = lambda: wincert.CertStore.from_pfx(identity.pfx, PFX_PASSWORD)  # noqa: E731
    signed, _ = pades.sign_pdf(
        samples.quote_pdf(), pades.SignOptions(thumbprint=hashlib.sha1(identity.der).hexdigest()), store_factory=factory
    )
    path = tmp_path / "sans-sigflags.pdf"
    path.write_bytes(signed)
    doc = fitz.open(path)
    doc.xref_set_key(doc.pdf_catalog(), "AcroForm/SigFlags", "null")
    doc.saveIncr()
    doc.close()
    data = path.read_bytes()
    assert fitz.open("pdf", data).get_sigflags() < 1
    s = d.PdfSession(data, name="sans-sigflags.pdf")
    assert s.signed_original
    s.add_annotation(0, {"type": "note", "point": [100, 100], "content": "vu"})
    assert s.export_bytes().startswith(data)  # mise à jour incrémentale, signature préservée


def test_repaired_signed_document_refuses_silent_rewrite(tmp_path):
    """PDF signé réparé à l'ouverture : refus explicite, réécriture seulement sur confirmation."""
    import re

    raw = bytearray(samples.quote_pdf())
    match = list(re.finditer(rb"startxref\s+(\d+)", raw))[-1]
    start, end = match.span(1)
    raw[start:end] = str(int(raw[start:end]) + 1).encode().rjust(end - start, b"0")  # table décalée d'un octet
    identity = make_test_pki()
    factory = lambda: wincert.CertStore.from_pfx(identity.pfx, PFX_PASSWORD)  # noqa: E731
    signed, _ = pades.sign_pdf(bytes(raw), pades.SignOptions(thumbprint=hashlib.sha1(identity.der).hexdigest()), store_factory=factory)
    s = d.PdfSession(signed, name="repare.pdf")
    assert s.signed_original
    s.add_annotation(0, {"type": "note", "point": [100, 100], "content": "vu"})
    target = tmp_path / "repare.pdf"
    with pytest.raises(d.DocumentError) as err:
        s.save(str(target))
    assert err.value.code == "repaired_signed"
    assert not target.exists()
    s.save(str(target), force_full=True)
    assert target.exists() and not s.dirty
    assert any(a["type"] == "Text" for a in d.PdfSession(target.read_bytes()).annotations(0))


def test_form_fields():
    s = d.PdfSession(samples.form_pdf(), name="dc1.pdf")
    fields = s.form_fields(0)
    names = {f["name"]: f for f in fields}
    assert set(names) == {"raison_sociale", "accepte"}
    s.set_field(0, names["raison_sociale"]["id"], "Menuiserie Destribois")
    s.set_field(0, names["accepte"]["id"], True)
    names = {f["name"]: f for f in s.form_fields(0)}
    assert names["raison_sociale"]["value"] == "Menuiserie Destribois"
    assert names["accepte"]["checked"]


def test_password_protected(tmp_path):
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Secret")
    data = doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="1234", owner_pw="owner")
    with pytest.raises(d.DocumentError) as err:
        d.PdfSession(data, name="secret.pdf")
    assert err.value.code == "password"
    s = d.PdfSession(data, name="secret.pdf", password="1234")
    s.add_annotation(0, {"type": "note", "point": [100, 100], "content": "ok"})
    target = tmp_path / "secret.pdf"
    s.save(str(target))
    again = fitz.open(target)
    assert again.needs_pass
    assert again.authenticate("1234")


def test_dirty_after_save_undo_and_new_edit(tmp_path):
    """Enregistrer, annuler, modifier autrement : le document reste « modifié »."""
    s = d.PdfSession(samples.quote_pdf(), name="devis.pdf")
    s.add_annotation(0, {"type": "note", "point": [100, 100], "content": "A"})
    s.save(str(tmp_path / "devis.pdf"))
    assert not s.dirty
    s.undo()
    assert s.dirty
    s.add_annotation(0, {"type": "note", "point": [200, 200], "content": "B"})
    assert s.dirty  # l'état enregistré contient A, la mémoire contient B
    s.undo()
    s.redo()
    assert s.dirty


def test_history_budget_drops_oldest():
    h = d.History(b"a" * 10, budget=35)
    ids = {h.state_id}
    for i in range(5):
        h.push(bytes([65 + i]) * 10, f"op{i}")
        ids.add(h.state_id)
    assert len(ids) == 6  # un identifiant par état
    assert h.can_undo()
    steps = 0
    while h.can_undo():
        h.undo()
        steps += 1
    assert steps == 2  # budget : trois états de 10 octets au plus


def test_encode_png_roundtrip():
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 7, 3), False)
    pix.clear_with(100)
    png = d.encode_png(pix.samples, pix.width, pix.height, pix.n)
    back = fitz.Pixmap(png)
    assert (back.width, back.height) == (7, 3)
    assert back.pixel(3, 1) == (100, 100, 100)


@pytest.mark.parametrize("rotation", [0, 90])
def test_render_jpeg_for_export(rotation):
    """Export JPG : page entière à la résolution demandée, droite si la page est pivotée,
    annotations comprises, résolution inscrite dans le fichier."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 72), "Facture INV_2026_00119", fontsize=14)
    page.add_rect_annot(fitz.Rect(300, 300, 400, 400)).set_colors(stroke=(1, 0, 0), fill=(1, 0, 0))
    page.first_annot.update()
    if rotation:
        page.set_rotation(rotation)
    s = d.PdfSession(doc.tobytes(), name="facture.pdf")
    data, dpi = s.render_jpeg(0, 150)
    assert data[:2] == b"\xff\xd8" and dpi == 150
    image = fitz.Pixmap(data)
    width, height = (595, 842) if rotation == 0 else (842, 595)
    assert abs(image.width - width * 150 / 72) <= 1 and abs(image.height - height * 150 / 72) <= 1
    assert image.xres == 150
    red = sum(1 for x in range(0, image.width, 8) for y in range(0, image.height, 8) if image.pixel(x, y)[0] > 200 > image.pixel(x, y)[1])
    assert red > 100, "annotation absente de l'image"


def test_render_jpeg_caps_huge_pages():
    """Un plan A0 à 300 ppp dépasserait 100 millions de pixels : résolution réduite."""
    doc = fitz.open()
    doc.new_page(width=3370, height=2384)
    data, dpi = d.PdfSession(doc.tobytes(), name="plan.pdf").render_jpeg(0, 300)
    image = fitz.Pixmap(data)
    assert dpi < 300 and image.width * image.height <= d.MAX_EXPORT_PIXELS * 1.01
