"""Assemblage de PDF, déplacement de plusieurs pages et compression."""

import hashlib

import pymupdf as fitz
import pytest

from destripdf import document as d
from destripdf.signing import pades, wincert
from tests import samples
from tests.pki import PFX_PASSWORD, make_test_pki


def _first_lines(session):
    return [d._contents_textpage(session.doc[i]).extractText().strip().splitlines()[0] for i in range(session.doc.page_count)]


def _numbered(count=6):
    return d.PdfSession(samples.other_pdf(count, "Page"), name="pages.pdf")


@pytest.mark.parametrize("pages, before, expected, start", [
    ([1, 3], 5, ["Page 1", "Page 3", "Page 5", "Page 2", "Page 4", "Page 6"], 3),  # vers l'avant, ordre gardé
    ([4, 5], 0, ["Page 5", "Page 6", "Page 1", "Page 2", "Page 3", "Page 4"], 0),  # en tête
    ([0, 2], 6, ["Page 2", "Page 4", "Page 5", "Page 6", "Page 1", "Page 3"], 4),  # à la fin
    ([5, 0], 3, ["Page 2", "Page 3", "Page 1", "Page 6", "Page 4", "Page 5"], 2),  # ordre du document, pas du clic
])
def test_move_pages_together_in_one_undo_step(pages, before, expected, start):
    s = _numbered()
    summary, moved = s.move_pages(pages, before)
    assert _first_lines(s) == expected
    assert moved == {"start": start, "count": len(pages)}
    assert summary["undo_label"] == "Déplacement de pages" and summary["dirty"]
    s.undo()
    assert _first_lines(s) == [f"Page {i}" for i in range(1, 7)] and not s.dirty


def test_move_pages_already_in_place_changes_nothing():
    s = _numbered()
    version = s.version
    summary, moved = s.move_pages([2, 3], 3)  # déposées sur elles-mêmes
    assert moved == {"start": 2, "count": 2}
    assert s.version == version and not summary["can_undo"] and not s.dirty


def test_move_pages_refuses_bad_requests():
    s = _numbered(3)
    for pages, before in (([], 0), ([3], 0), ([-1], 0), ([0], 4), ([0], -1)):
        with pytest.raises(d.DocumentError):
            s.move_pages(pages, before)
    assert not s.history.can_undo()


def test_move_pages_keeps_forms_annotations_links_and_bookmarks():
    """`select()` de MuPDF retire /AcroForm : le déplacement ne doit rien perdre."""
    doc = fitz.open("pdf", samples.other_pdf(4, "Page"))
    widget = fitz.Widget()
    widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    widget.field_name = "montant"
    widget.rect = fitz.Rect(100, 200, 300, 220)
    doc[1].add_widget(widget)
    doc[2].add_text_annot((100, 100), "note page 3")
    doc[0].insert_link({"kind": fitz.LINK_GOTO, "from": fitz.Rect(56, 100, 200, 120), "page": 3, "to": fitz.Point(0, 0)})
    doc.set_toc([[1, "Début", 1], [1, "Quatre", 4]])
    s = d.PdfSession(doc.tobytes(), name="formulaire.pdf")
    s.move_pages([3, 1], 0)  # pages 2 et 4 en tête
    assert _first_lines(s) == ["Page 2", "Page 4", "Page 1", "Page 3"]
    assert s.doc.is_form_pdf and [w.field_name for w in s.doc[0].widgets()] == ["montant"]
    assert [a.info["content"] for a in s.doc[3].annots()] == ["note page 3"]
    assert [link.get("page") for link in s.doc[2].get_links()] == [1]  # la page 4 est maintenant la 2
    assert s.doc.get_toc() == [[1, "Début", 3], [1, "Quatre", 2]]
    saved = fitz.open("pdf", s.export_bytes())
    assert saved.is_form_pdf and [w.field_name for w in saved[0].widgets()] == ["montant"]


def test_insert_several_pdfs_in_one_undo_step():
    s = d.PdfSession(samples.quote_pdf(), name="devis.pdf")
    summary, info = s.insert_pdfs([("plan.pdf", samples.other_pdf(2, "Plan")), ("cctp.pdf", samples.other_pdf(1, "CCTP"))], 1)
    assert _first_lines(s) == ["DEVIS DEV-2026-042", "Plan 1", "Plan 2", "CCTP 1", "Conditions générales — page 2"]
    assert info == {"start": 1, "count": 3, "files": 2, "signed": []}
    assert summary["undo_label"] == "Insertion de 2 PDF"
    s.undo()
    assert s.doc.page_count == 2 and not s.dirty
    # sans position : à la fin
    s.insert_pdfs([("plan.pdf", samples.other_pdf(1, "Plan"))])
    assert _first_lines(s)[-1] == "Plan 1"


def test_insert_refuses_everything_when_one_source_is_bad():
    s = d.PdfSession(samples.quote_pdf(), name="devis.pdf")
    with pytest.raises(d.DocumentError) as err:
        s.insert_pdfs([("plan.pdf", samples.other_pdf(1)), ("note.pdf", b"pas un pdf")])
    assert err.value.code == "not_pdf" and "« note.pdf »" in str(err.value)
    locked = fitz.open("pdf", samples.other_pdf(1)).tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="1234", owner_pw="o")
    with pytest.raises(d.DocumentError) as err:
        s.insert_pdfs([("secret.pdf", locked)])
    assert err.value.code == "password" and "« secret.pdf »" in str(err.value)
    with pytest.raises(d.DocumentError):
        s.insert_pdfs([])
    assert s.doc.page_count == 2 and not s.history.can_undo()


def test_assemble_in_order_with_one_bookmark_per_file(tmp_path):
    chapters = fitz.open("pdf", samples.other_pdf(3, "Chapitre"))
    chapters.set_toc([[1, "Premier", 1], [2, "Détail", 2], [1, "Dernier", 3]])
    data, signed = d.assemble_pdfs([
        ("01 - devis.pdf", samples.quote_pdf()),
        ("02 - cctp.pdf", chapters.tobytes()),
        ("03 - plan.pdf", samples.rotated_pdf()),
    ])
    assert signed == []
    out = fitz.open("pdf", data)
    assert out.page_count == 6 and out[5].rotation == 90
    assert out.get_toc() == [
        [1, "01 - devis", 1],
        [1, "02 - cctp", 3], [2, "Premier", 3], [3, "Détail", 4], [2, "Dernier", 5],
        [1, "03 - plan", 6],
    ]
    # Document neuf : à enregistrer, jamais perdu sans question.
    s = d.PdfSession(data, name="01 - devis - assemblé.pdf", new_document=True)
    assert s.dirty and s.path is None
    with pytest.raises(d.DocumentError):
        s.save()
    s.save(str(tmp_path / "dossier.pdf"))
    assert not s.dirty and fitz.open(tmp_path / "dossier.pdf").page_count == 6


def test_assemble_single_file_keeps_its_own_bookmarks():
    source = fitz.open("pdf", samples.other_pdf(2))
    source.set_toc([[1, "Annexes", 1], [1, "Fin", 2]])
    data, _ = d.assemble_pdfs([("annexes.pdf", source.tobytes())])
    assert fitz.open("pdf", data).get_toc() == [[1, "Annexes", 1], [1, "Fin", 2]]


def _ink(page, rect):
    pix = page.get_pixmap(clip=rect, dpi=72)
    return sum(1 for i in range(0, len(pix.samples), pix.n) if pix.samples[i] < 128)


def test_signed_sources_are_flattened_not_left_as_invalid_signatures():
    """Une signature hors de son fichier est invalide : elle reste visible (image), le
    document assemblé n'est pas « signé » (ni bandeau rouge, ni compression refusée)."""
    identity = make_test_pki()
    frame = (320, 680, 540, 750)
    signed_pdf, _ = pades.sign_pdf(
        samples.quote_pdf(),
        pades.SignOptions(thumbprint=hashlib.sha1(identity.der).hexdigest(),
                          appearance=pades.Appearance(page_index=1, rect=frame)),
        store_factory=lambda: wincert.CertStore.from_pfx(identity.pfx, PFX_PASSWORD),
    )
    data, signed = d.assemble_pdfs([("devis signé.pdf", signed_pdf), ("plan.pdf", samples.rotated_pdf())])
    assert signed == ["devis signé.pdf"]
    out = fitz.open("pdf", data)
    assert not d.has_signatures(out)
    shown = fitz.Rect(frame) * out[1].rotation_matrix
    assert _ink(out[1], shown) > 50  # le cadre de la signature reste visible
    s = d.PdfSession(data, name="dossier.pdf", new_document=True)
    assert not s.signed_original and len(s.compressed_bytes("screen")) > 0
    host = d.PdfSession(samples.other_pdf(1), name="dossier.pdf")
    _, info = host.insert_pdfs([("devis signé.pdf", signed_pdf)])
    assert info["signed"] == ["devis signé.pdf"] and not d.has_signatures(host.doc)


def test_layers_keep_their_default_state_and_attachments_follow():
    """`insert_pdf` ne reprend pas /OCProperties : un calque masqué apparaîtrait."""
    layered = samples.layered_pdf()
    hidden, shown = fitz.Rect(50, 100, 300, 125), fitz.Rect(50, 140, 300, 165)
    source = fitz.open("pdf", layered)
    assert _ink(source[0], hidden) == 0 and _ink(source[0], shown) > 0
    data, _ = d.assemble_pdfs([("devis.pdf", samples.quote_pdf()), ("plan.pdf", layered)])
    out = fitz.open("pdf", data)
    plan = out[2]
    assert _ink(plan, hidden) == 0 and _ink(plan, shown) > 0
    assert sorted((o["name"], o["on"]) for o in out.get_ocgs().values()) == [("Cotes", False), ("Mobilier", True)]
    assert out.embfile_names() == ["factur-x.xml"] and out.embfile_get("factur-x.xml") == b"<rsm:CrossIndustryInvoice/>"
    # insertion dans un document déjà à calques : les deux jeux, chacun dans son état
    s = d.PdfSession(layered, name="plan.pdf")
    s.insert_pdfs([("plan bis.pdf", layered)], 0)
    assert sorted(o["on"] for o in s.doc.get_ocgs().values()) == [False, False, True, True]
    saved = fitz.open("pdf", s.export_bytes())  # calques identiques fusionnés à l'enregistrement
    assert [_ink(saved[i], hidden) for i in range(2)] == [0, 0] and all(_ink(saved[i], shown) > 0 for i in range(2))
    assert sorted(saved.embfile_names()) == ["factur-x.xml", "factur-x.xml (2)"]


@pytest.mark.parametrize("jpeg", [False, True])
def test_compress_keeps_colours_of_icc_cmyk_images(jpeg):
    """MuPDF recompresse une image CMJN à profil ICC en JPEG RVB en lui laissant l'espace
    CMJN : sans correction, le bleu canard devient brun."""
    source = samples.icc_cmyk_pdf(jpeg)
    zone = fitz.Rect(72, 90, 288, 378)

    def mean(data):
        pix = fitz.open("pdf", data)[0].get_pixmap(clip=zone, dpi=36, alpha=False)
        count = pix.width * pix.height
        return [sum(pix.samples[c::pix.n]) / count for c in range(3)]

    before = mean(source)
    s = d.PdfSession(source, name="catalogue.pdf")
    for level in ("print", "screen", "minimum"):
        after = mean(s.compressed_bytes(level))
        assert max(abs(a - b) for a, b in zip(after, before)) < 8, (level, before, after)


def _images(data):
    doc = fitz.open("pdf", data)
    out = []
    for page in doc:
        for info in page.get_image_info():
            out.append(round(info["width"] / (fitz.Rect(info["bbox"]).width / 72)))
    return out


def test_compress_levels_reduce_images_and_keep_text():
    source = samples.photo_pdf(400)
    s = d.PdfSession(source, name="chantier.pdf")
    sizes = {}
    for level, max_dpi in (("print", 400), ("screen", 150), ("minimum", 100)):
        data = s.compressed_bytes(level)
        sizes[level] = len(data)
        out = fitz.open("pdf", data)
        assert out.page_count == 1 and "Photo du chantier" in out[0].get_text()
        assert all(dpi <= max_dpi + 1 for dpi in _images(data)), (level, _images(data))
    assert sizes["minimum"] < sizes["screen"] < sizes["print"] < len(source)
    assert sizes["screen"] < len(source) / 4
    # le document ouvert n'est pas touché
    assert not s.dirty and not s.history.can_undo() and _images(s.history.current) == [400]


def test_compress_keeps_password_and_refuses_signed_or_unknown_level():
    locked = fitz.open("pdf", samples.photo_pdf(300)).tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="1234", owner_pw="o")
    s = d.PdfSession(locked, name="secret.pdf", password="1234")
    out = fitz.open("pdf", s.compressed_bytes("screen"))
    assert out.needs_pass and out.authenticate("1234") and "Photo du chantier" in out[0].get_text()
    with pytest.raises(d.DocumentError) as err:
        s.compressed_bytes("extreme")
    assert err.value.code == "bad_level"
    identity = make_test_pki()
    signed_pdf, _ = pades.sign_pdf(
        samples.photo_pdf(300),
        pades.SignOptions(thumbprint=hashlib.sha1(identity.der).hexdigest()),
        store_factory=lambda: wincert.CertStore.from_pfx(identity.pfx, PFX_PASSWORD),
    )
    with pytest.raises(d.DocumentError) as err:
        d.PdfSession(signed_pdf, name="signé.pdf").compressed_bytes("screen")
    assert err.value.code == "signed"


def test_compress_includes_unsaved_changes():
    s = d.PdfSession(samples.photo_pdf(300), name="chantier.pdf")
    s.add_annotation(0, {"type": "note", "point": [300, 400], "content": "Reprendre l'enduit"})
    out = fitz.open("pdf", s.compressed_bytes("screen"))
    assert [a.info["content"] for a in out[0].annots()] == ["Reprendre l'enduit"]
