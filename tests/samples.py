"""Documents d'essai fabriqués à la volée (aucun fichier réel)."""

from __future__ import annotations

import pymupdf as fitz

from destripdf import fonts

ARIAL = r"C:\Windows\Fonts\arial.ttf"
ARIAL_BOLD = r"C:\Windows\Fonts\arialbd.ttf"


def write(page: fitz.Page, pos, text: str, *, size: float = 11, bold: bool = False, color=(0, 0, 0)):
    # Police réduite aux glyphes utiles : table Unicode sans ambiguïté (espace, tiret).
    choice = fonts.FontChoice(ARIAL_BOLD if bold else ARIAL, 0, "Arial", bold, False, True)
    font = fonts.subset_font(choice, text)
    writer = fitz.TextWriter(page.rect, color=color)
    writer.append(pos, text, font=font, fontsize=size)
    writer.write_text(page)


def quote_pdf() -> bytes:
    """Devis d'essai : paragraphe, tableau avec montants alignés à droite, cadre, image."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    write(page, (56, 80), "DEVIS DEV-2026-042", size=16, bold=True)
    write(page, (56, 110), "Client : Mairie de Zellwiller")
    write(page, (56, 124), "Objet : Remplacement des portes du préau")
    write(page, (56, 138), "Date : 12/10/2026")
    # tableau : désignation à gauche, montant aligné à droite (x1 = 540)
    rows = [("Porte chêne 93 x 204", "1 250,00 €"), ("Pose et ajustage", "480,00 €"), ("Total HT", "1 730,00 €")]
    y = 200
    font = fitz.Font(fontfile=ARIAL)  # mesure seulement
    for label, amount in rows:
        write(page, (56, y), label)
        width = font.text_length(amount, fontsize=11)
        write(page, (540 - width, y), amount)
        y += 16
    page.draw_rect(fitz.Rect(50, 186, 546, 250), color=(0.2, 0.2, 0.2), width=0.6)
    page.draw_line((50, 204), (546, 204), color=(0.2, 0.2, 0.2), width=0.4)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 40), False)
    pix.clear_with(180)
    page.insert_image(fitz.Rect(480, 60, 540, 120), pixmap=pix)
    page2 = doc.new_page(width=595, height=842)
    write(page2, (56, 80), "Conditions générales — page 2")
    return doc.tobytes()


def rotated_pdf(rotation: int = 90) -> bytes:
    """Page pivotée par /Rotate avec texte droit à l'affichage."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.set_rotation(rotation)
    # Point choisi dans l'affichage, converti dans l'espace non pivoté.
    origin = fitz.Point(100, 120) * page.derotation_matrix
    page.insert_text(origin, "Plan de pose niveau 1", fontsize=14, fontname="helv", rotate=rotation)
    return doc.tobytes()


def form_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    text = fitz.Widget()
    text.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    text.field_name = "raison_sociale"
    text.rect = fitz.Rect(100, 100, 400, 120)
    page.add_widget(text)
    box = fitz.Widget()
    box.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
    box.field_name = "accepte"
    box.rect = fitz.Rect(100, 140, 114, 154)
    page.add_widget(box)
    return doc.tobytes()


def other_pdf(pages: int = 2) -> bytes:
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=595, height=842)
        write(page, (56, 80), f"Annexe {i + 1}")
    return doc.tobytes()
