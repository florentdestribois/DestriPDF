"""Livret (piqûre à cheval) mis en page par DestriPDF.

La fonction Livret des imprimantes n'est pas utilisée : sur la Canon de
l'atelier, elle réclame du papier « A4R » (A4 chargé dans l'autre sens, pour
le pliage de l'imprimante) que les bacs n'ont pas. DestriPDF compose donc
lui-même les faces des feuilles — deux pages côte à côte, dans l'ordre qui
donne le livret une fois la pile pliée au milieu — et les imprime comme un
document Word recto verso ordinaire (portrait, bord long), chaque face tournée
d'un quart de tour sur la feuille (voir `printing.py`).

Ordre des faces : recto de la feuille 1, verso de la feuille 1, recto de la
feuille 2… Pour 8 pages : (8|1), (2|7), (6|3), (4|5). Le verso d'une moitié de
feuille porte la page suivante : la page 2 est au dos de la page 1.
"""

from __future__ import annotations

import math

import pymupdf as fitz

MM = 72 / 25.4
# Feuilles en paysage, en points.
SHEETS = {
    "a4": (297 * MM, 210 * MM),
    "a3": (420 * MM, 297 * MM),
}
# Marge minimale autour de chaque page, y compris au pli (la gouttière fait le double).
MIN_MARGIN = 5 * MM


def booklet_sides(count: int, binding: str = "left") -> list[tuple[int | None, int | None]]:
    """Faces imprimées dans l'ordre : (page de gauche, page de droite), index à partir
    de 0, None pour une page blanche ajoutée afin d'atteindre un multiple de 4.
    `binding` : 'left' (lecture de gauche à droite) ou 'right' (reliure à droite)."""
    total = max(4, math.ceil(count / 4) * 4)
    faces = []
    for sheet in range(total // 4):
        for left, right in (
            (total - 1 - 2 * sheet, 2 * sheet),  # recto
            (2 * sheet + 1, total - 2 - 2 * sheet),  # verso
        ):
            left = left if left < count else None
            right = right if right < count else None
            faces.append((right, left) if binding == "right" else (left, right))
    return faces


def sheet_count(count: int) -> int:
    return max(4, math.ceil(count / 4) * 4) // 4


def impose(doc: fitz.Document, pages: list[int], sheet: tuple[float, float], margin: float = MIN_MARGIN,
           binding: str = "left") -> fitz.Document:
    """Document des faces du livret, une page PDF par face (feuille paysage).

    Chaque page paraît telle qu'affichée dans DestriPDF : rotation de la page,
    annotations, champs remplis et signatures visibles compris (intégrés à une
    copie, le document ouvert n'est pas modifié). Elle est réduite sans
    déformation et centrée dans sa moitié de feuille, à `margin` au moins des
    bords et du pli ; une page paysage y est tournée d'un quart de tour vers la
    gauche. L'appelant tient `document.FITZ_LOCK`.
    """
    if not pages:
        raise ValueError("aucune page à mettre en livret")
    source = fitz.open("pdf", doc.tobytes())  # copie déchiffrée, jamais le document ouvert
    source.bake()  # annotations et champs deviennent du contenu de page
    width, height = sheet
    half = width / 2
    out = fitz.open()
    for left, right in booklet_sides(len(pages), binding):
        face = out.new_page(width=width, height=height)
        for slot, position in ((0, left), (1, right)):
            if position is None:
                continue
            index = pages[position]
            page = source[index]
            box = fitz.Rect(slot * half + margin, margin, (slot + 1) * half - margin, height - margin)
            shown_w, shown_h = page.rect.width, page.rect.height  # taille affichée (rotation comprise)
            turn = 90 if (shown_w > shown_h) != (box.width > box.height) and shown_w != shown_h else 0
            if turn:
                shown_w, shown_h = shown_h, shown_w
            scale = min(box.width / shown_w, box.height / shown_h)
            w, h = shown_w * scale, shown_h * scale
            target = fitz.Rect(box.x0 + (box.width - w) / 2, box.y0 + (box.height - h) / 2, 0, 0)
            target.x1, target.y1 = target.x0 + w, target.y0 + h
            # show_pdf_page ignore /Rotate : -rotation la rétablit, +90 tourne vers la gauche.
            face.show_pdf_page(target, source, index, rotate=(turn - page.rotation) % 360)
    source.close()
    return out
