"""Livret mis en page par DestriPDF : ordre des faces et composition des feuilles."""

import pymupdf as fitz
import pytest

from destripdf import booklet as b
from destripdf import document as d


def test_booklet_sides_order():
    assert b.booklet_sides(1) == [(None, 0), (None, None)]
    assert b.booklet_sides(2) == [(None, 0), (1, None)]
    assert b.booklet_sides(4) == [(3, 0), (1, 2)]
    assert b.booklet_sides(5) == [(None, 0), (1, None), (None, 2), (3, 4)]
    # 8 pages : (8|1), (2|7), (6|3), (4|5) ; la page 2 est au dos de la page 1
    assert b.booklet_sides(8) == [(7, 0), (1, 6), (5, 2), (3, 4)]
    assert b.booklet_sides(8, "right") == [(0, 7), (6, 1), (2, 5), (4, 3)]
    assert b.sheet_count(8) == 2 and b.sheet_count(9) == 3 and b.sheet_count(1) == 1


@pytest.mark.parametrize("count", [1, 3, 4, 7, 12, 13])
def test_every_page_once_and_folded_order(count):
    """Chaque page une seule fois ; pliée, la pile se lit 1, 2, 3… : au recto d'une
    feuille, gauche + droite = total - 1, et le verso suit le recto."""
    faces = b.booklet_sides(count)
    total = b.sheet_count(count) * 4
    seen = [p for face in faces for p in face if p is not None]
    assert sorted(seen) == list(range(count))
    for sheet in range(len(faces) // 2):
        front, back = faces[2 * sheet], faces[2 * sheet + 1]
        full_front = (total - 1 - 2 * sheet, 2 * sheet)
        assert front == tuple(p if p < count else None for p in full_front)
        # dos de la moitié droite du recto (page impaire 2s+1 en numérotation humaine) = page suivante
        assert back[0] in (2 * sheet + 1, None)


def _numbered_pdf(count, size=(595, 842)):
    doc = fitz.open()
    for i in range(count):
        page = doc.new_page(width=size[0], height=size[1])
        page.insert_text((60, 120), f"Page{i + 1}", fontsize=40)
    return doc


def _words_by_half(face):
    width = face.rect.width
    left, right = [], []
    for x0, y0, x1, y1, word, *_ in face.get_text("words"):
        assert x1 <= width / 2 or x0 >= width / 2, f"{word} chevauche le pli"
        (left if x1 <= width / 2 else right).append(word)
    return left, right


def test_impose_puts_pages_in_folding_order():
    src = _numbered_pdf(6)
    faces = b.impose(src, list(range(6)), b.SHEETS["a4"])
    assert faces.page_count == 4
    # numéros humains ; 8 emplacements dont 2 blancs (pages 7 et 8, au dos de la couverture)
    expected = [(None, 1), (2, None), (6, 3), (4, 5)]
    for face, (left, right) in zip(faces, expected):
        assert abs(face.rect.width - 841.89) < 0.5 and abs(face.rect.height - 595.28) < 0.5
        words_left, words_right = _words_by_half(face)
        assert words_left == ([f"Page{left}"] if left else [])
        assert words_right == ([f"Page{right}"] if right else [])


def test_impose_selected_pages_and_right_binding():
    src = _numbered_pdf(5)
    faces = b.impose(src, [4, 2, 0], b.SHEETS["a4"], binding="right")  # pages 5, 3, 1 dans cet ordre
    # 3 pages → 4 : recto (blanche | 5) et verso (3 | 1) deviennent (5 | blanche) et (1 | 3)
    assert _words_by_half(faces[0]) == (["Page5"], [])
    assert _words_by_half(faces[1]) == (["Page1"], ["Page3"])


def test_impose_keeps_margins_and_proportions():
    src = _numbered_pdf(4)
    margin = 20
    faces = b.impose(src, list(range(4)), b.SHEETS["a4"], margin=margin)
    face = faces[0]
    half = face.rect.width / 2
    # contenu vectoriel (pages posées comme Form XObject, pas d'images), dans sa moitié, à la marge près
    assert not face.get_image_info()
    for x0, y0, x1, y1, *_ in face.get_text("words"):
        assert y0 >= margin - 0.5 and x0 >= margin - 0.5 and x1 <= face.rect.width - margin + 0.5
        assert x1 <= half - margin + 0.5 or x0 >= half + margin - 0.5
    # taille de la page réduite : A4 (595×842) dans 841.89/2 − 2×20 de large → échelle 0.639
    scale = min((half - 2 * margin) / 595, (face.rect.height - 2 * margin) / 842)
    assert 0.6 < scale < 0.7


def test_impose_shows_pages_as_displayed():
    """Page pivotée dans DestriPDF : droite sur la feuille ; page paysage : tournée
    d'un quart de tour vers la gauche pour tenir dans la demi-feuille."""
    src = fitz.open()
    turned = src.new_page(width=595, height=842)
    turned.insert_text((60, 120), "Pivotee", fontsize=40)
    turned.set_rotation(90)  # affichée en paysage, texte vertical
    wide = src.new_page(width=842, height=595)
    wide.insert_text((60, 120), "Paysage", fontsize=40)
    faces = b.impose(src, [0, 1], b.SHEETS["a4"])
    lines = {}
    for block in faces[0].get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            lines["".join(s["text"] for s in line["spans"])] = tuple(round(v) for v in line["dir"])
    # page pivotée d'un quart de tour à droite, posée dans une demi-feuille portrait :
    # ramenée à son sens d'origine, texte horizontal
    assert lines["Pivotee"] == (1, 0)
    # page 2 au verso (face 1) : paysage tourné vers la gauche, texte montant
    lines = {}
    for block in faces[1].get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            lines["".join(s["text"] for s in line["spans"])] = tuple(round(v) for v in line["dir"])
    assert lines["Paysage"] == (0, -1)


def test_impose_includes_annotations_and_fields_without_touching_document():
    src = fitz.open()
    page = src.new_page(width=595, height=842)
    page.add_rect_annot(fitz.Rect(0, 0, 150, 150)).set_colors(stroke=(1, 0, 0), fill=(1, 0, 0))
    page.first_annot.update()
    widget = fitz.Widget()
    widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    widget.field_name = "client"
    widget.field_value = "Mairie de Zellwiller"
    widget.rect = fitz.Rect(72, 400, 400, 430)
    page.add_widget(widget)
    before = (src[0].read_contents(), src.xref_length())
    faces = b.impose(src, [0], b.SHEETS["a4"])
    assert "Zellwiller" in faces[0].get_text()
    pix = faces[0].get_pixmap(dpi=36)
    red = [(x, y) for x in range(pix.width) for y in range(pix.height) if pix.pixel(x, y)[0] > 200 and pix.pixel(x, y)[1] < 80]
    assert red and min(x for x, _ in red) > pix.width / 2  # page 1 à droite du recto
    # le document ouvert n'est pas modifié (annotations et champs toujours là)
    assert (src[0].read_contents(), src.xref_length()) == before
    assert len(list(src[0].annots())) == 1 and next(src[0].widgets()).field_value == "Mairie de Zellwiller"


def test_session_impose_booklet_checks_pages():
    session = d.PdfSession(_numbered_pdf(3).tobytes(), name="devis.pdf")
    faces = session.impose_booklet([0, 1, 2], b.SHEETS["a3"], b.MIN_MARGIN, "left")
    assert faces.page_count == 2 and abs(faces[0].rect.width - 1190.55) < 0.5
    with pytest.raises(Exception):
        session.impose_booklet([0, 9], b.SHEETS["a4"], b.MIN_MARGIN, "left")
