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


def other_pdf(pages: int = 2, label: str = "Annexe") -> bytes:
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=595, height=842)
        write(page, (56, 80), f"{label} {i + 1}")
    return doc.tobytes()


def icc_cmyk_pdf(jpeg: bool, dpi: int = 400) -> bytes:
    """Page avec une image CMJN à profil ICC (comme un export d'InDesign), sur 3 x 4 pouces,
    JPEG ou sans perte. Couleur dominante : bleu canard (C 200, M ~40, J 10, N 20 sur 255)."""
    import random
    import zlib

    rng = random.Random(1)
    width, height = 3 * dpi, 4 * dpi
    pixels = bytearray()
    for _ in range(width * height):
        pixels += bytes((200, 30 + rng.randrange(20), 10, 20))
    # Profil CMJN de MuPDF : celui qu'il intègre pour une image CMJN.
    probe = fitz.open()
    probe.new_page().insert_image(fitz.Rect(0, 0, 10, 10), pixmap=fitz.Pixmap(fitz.csCMYK, 2, 2, bytes(16), False))
    probe = fitz.open("pdf", probe.tobytes())
    profile = next(probe.xref_stream(x) for x in range(1, probe.xref_length())
                   if probe.xref_is_stream(x) and "/N 4" in probe.xref_object(x, compressed=True))
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    icc = doc.get_new_xref()
    doc.update_object(icc, "<</N 4>>")
    doc.update_stream(icc, profile)
    space = doc.get_new_xref()
    doc.update_object(space, f"[/ICCBased {icc} 0 R]")
    image = doc.get_new_xref()
    doc.update_object(image, f"<</Type/XObject/Subtype/Image/Width {width}/Height {height}/BitsPerComponent 8/ColorSpace {space} 0 R>>")
    if jpeg:
        pix = fitz.Pixmap(fitz.csCMYK, width, height, bytes(pixels), False)
        doc.update_stream(image, pix.tobytes("jpg", jpg_quality=95), compress=False)
        doc.xref_set_key(image, "Filter", "/DCTDecode")
    else:
        doc.update_stream(image, zlib.compress(bytes(pixels)), compress=False)
        doc.xref_set_key(image, "Filter", "/FlateDecode")
    doc.xref_set_key(page.xref, "Resources", f"<</XObject<</Im0 {image} 0 R>>>>")
    contents = doc.get_new_xref()
    doc.update_object(contents, "<<>>")
    doc.update_stream(contents, f"q 216 0 0 288 72 {842 - 90 - 288} cm /Im0 Do Q".encode())
    doc.xref_set_key(page.xref, "Contents", f"{contents} 0 R")
    return doc.tobytes(garbage=3)


def layered_pdf() -> bytes:
    """Plan à calques : « Cotes » masqué par défaut, « Mobilier » visible ; une pièce jointe."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    hidden = doc.add_ocg("Cotes", on=False)
    shown = doc.add_ocg("Mobilier", on=True)
    page.insert_text((56, 80), "Plan du rez-de-chaussée", fontsize=12)
    page.insert_text((56, 120), "COTES MASQUEES", fontsize=18, oc=hidden)
    page.insert_text((56, 160), "MOBILIER VISIBLE", fontsize=18, oc=shown)
    doc.embfile_add("factur-x.xml", b"<rsm:CrossIndustryInvoice/>", filename="factur-x.xml", desc="Facture")
    return doc.tobytes()


def photo_pdf(dpi: int = 400) -> bytes:
    """Page avec une photo (JPEG de qualité 95) posée sur 3 x 4 pouces à `dpi` ppp, et du texte."""
    import random

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    write(page, (56, 60), "Photo du chantier")
    width, height = 3 * dpi, 4 * dpi
    pixels = bytearray(random.Random(42).randbytes(width * height * 3))
    for y in range(0, height, 8):  # bandes claires : une image, pas seulement du bruit
        start = y * width * 3
        pixels[start:start + width * 3] = b"\xe0" * (width * 3)
    pix = fitz.Pixmap(fitz.csRGB, width, height, bytes(pixels), False)
    page.insert_image(fitz.Rect(72, 90, 72 + 216, 90 + 288), stream=pix.tobytes("jpg", jpg_quality=95))
    return doc.tobytes(garbage=3, deflate=True)
