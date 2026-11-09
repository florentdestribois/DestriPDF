"""Images converties en pages PDF : ouverture, ajout et assemblage."""

import pymupdf as fitz
import pytest

from destripdf import document as d
from tests import samples
from tests.test_server import request, server  # noqa: F401 - fixture partagée


def _convert(data, name=None):
    with d.FITZ_LOCK:
        return fitz.open("pdf", d.image_to_pdf(data, name))


def _red(pix, x, y):
    r, g, b = pix.pixel(x, y)[:3]
    return r > 200 and g < 60 and b < 60


def test_image_kind_by_signature_not_by_name():
    assert d.image_kind(samples.jpeg_photo()) == "jpg"
    assert d.image_kind(samples.png_image()) == "png"
    assert d.image_kind(samples.tiff_pages([(10, 10, (0, 0, 0), 100)])) == "tif"
    assert d.image_kind(b"BM" + b"\x00" * 40) == "bmp"
    assert d.image_kind(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "webp"
    assert d.image_kind(samples.other_pdf(1)) is None
    assert d.image_kind(b"") is None


def test_scan_keeps_its_real_size_and_photo_fits_a4():
    # Scan à 300 ppp d'un A4 : page A4 exacte.
    scan = _convert(samples.jpeg_photo(2480, 3508, dpi=300))
    assert scan.page_count == 1
    assert abs(scan[0].rect.width - 595.2) < 1 and abs(scan[0].rect.height - 841.9) < 1
    # Photo de téléphone (4032 × 3024 à 72 ppp, 1,4 m) : réduite dans un A4 paysage, proportions gardées.
    photo = _convert(samples.jpeg_photo(4032, 3024, dpi=72))
    width, height = photo[0].rect.width, photo[0].rect.height
    assert width <= 842.5 and abs(height - 595) < 1 and abs(width / height - 4032 / 3024) < 0.01
    # Petite image : taille réelle, jamais agrandie.
    small = _convert(samples.png_image(150, 75))
    assert small[0].rect.width < 150


def test_jpeg_is_not_recompressed_and_camera_orientation_applies():
    jpeg = samples.jpeg_photo(400, 200, dpi=96, orientation=6)
    pdf = _convert(jpeg)
    page = pdf[0]
    assert page.rect.height > page.rect.width  # quart de tour à droite appliqué
    xref = page.get_images(full=True)[0][0]
    assert pdf.xref_get_key(xref, "Filter") == ("name", "/DCTDecode")
    pix = page.get_pixmap()
    # Coin rouge de l'image (haut gauche) : en haut à droite après le quart de tour.
    assert _red(pix, pix.width - 3, 3) and not _red(pix, 3, 3)


def test_multipage_tiff_gives_one_page_per_image():
    tiff = samples.tiff_pages([(300, 420, (255, 0, 0), 100), (420, 300, (0, 0, 255), 100)])
    pdf = _convert(tiff, "scan.tif")
    assert pdf.page_count == 2
    assert pdf[0].rect.height > pdf[0].rect.width and pdf[1].rect.width > pdf[1].rect.height
    assert pdf[1].get_pixmap().pixel(10, 10)[:3] == (0, 0, 255)


def test_transparent_png_keeps_its_mask():
    pdf = _convert(samples.png_image(alpha=True))
    xref = pdf[0].get_images(full=True)[0][0]
    assert pdf.xref_get_key(xref, "SMask")[0] == "xref"
    pix = pdf[0].get_pixmap()
    assert pix.pixel(3, 3) == (255, 255, 255)  # fond de page visible à travers l'image
    centre = pix.pixel(pix.width // 2, pix.height // 2)
    assert centre[2] > 150 and centre[0] < 90


def test_bad_images_are_refused():
    with pytest.raises(d.DocumentError) as err:
        _convert(b"\xff\xd8\xff" + b"\x00" * 50, "casse.jpg")
    assert err.value.code == "bad_image" and "casse.jpg" in str(err.value)
    with pytest.raises(d.DocumentError) as err:
        _convert(b"texte", "notes.txt")
    assert err.value.code == "not_image"


def test_images_inserted_with_pdfs_in_one_step():
    s = d.PdfSession(samples.other_pdf(2), name="dossier.pdf")
    summary, info = s.insert_pdfs([("photo.jpg", samples.jpeg_photo()), ("plan.pdf", samples.other_pdf(1, "Plan"))], at=1)
    assert info == {"start": 1, "count": 2, "files": 2, "signed": []}
    assert s.doc.page_count == 4 and s.doc[1].get_images()
    s.undo()
    assert s.doc.page_count == 2


def test_one_bad_image_refuses_the_whole_insert():
    s = d.PdfSession(samples.other_pdf(2), name="dossier.pdf")
    with pytest.raises(d.DocumentError) as err:
        s.insert_pdfs([("photo.jpg", samples.jpeg_photo()), ("casse.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)])
    assert "casse.png" in str(err.value)
    assert s.doc.page_count == 2 and not s.history.can_undo()


def test_assemble_images_and_pdfs_with_one_bookmark_each():
    data, signed = d.assemble_pdfs([
        ("01 - devis.pdf", samples.quote_pdf()),
        ("02 - photo.jpg", samples.jpeg_photo()),
        ("03 - scan.tif", samples.tiff_pages([(100, 140, (0, 0, 0), 100), (100, 140, (0, 0, 0), 100)])),
    ])
    out = fitz.open("pdf", data)
    first = fitz.open("pdf", samples.quote_pdf()).page_count
    assert signed == [] and out.page_count == first + 3
    assert out.get_toc() == [[1, "01 - devis", 1], [1, "02 - photo", first + 1], [1, "03 - scan", first + 2]]


def test_image_routes_open_insert_assemble(server, tmp_path):  # noqa: F811
    photo = tmp_path / "chantier.jpg"
    photo.write_bytes(samples.jpeg_photo())
    # Ouvrir une image : nouveau PDF sans fichier, l'image n'est jamais remplacée.
    status, data = request(server, "POST", "api/open", {"path": str(photo)})
    assert status == 200 and data["doc"]["name"] == "chantier.pdf" and data["doc"]["path"] is None
    assert data["doc"]["page_count"] == 1 and server.app.session.dirty
    assert request(server, "POST", "api/save")[1]["code"] == "need_path"
    assert photo.read_bytes() == samples.jpeg_photo()
    assert server.app.session.origin_dir == str(tmp_path)
    assert server.app.settings.is_recent(str(photo))  # rouverte (et reconvertie) depuis l'accueil
    # Image déposée (navigateur) : même conversion.
    status, data = request(server, "POST", "api/upload?name=scan.png", samples.png_image())
    assert status == 200 and data["doc"]["name"] == "scan.pdf"
    # Ajout d'images au document ouvert.
    body = samples.jpeg_photo() + samples.png_image()
    query = f"sizes={len(samples.jpeg_photo())},{len(samples.png_image())}&names=%5B%22a.jpg%22%2C%22b.png%22%5D"
    status, data = request(server, "POST", f"api/pages/insert-upload?at=0&{query}", body)
    assert status == 200 and data["inserted"] == {"start": 0, "count": 2, "files": 2}
    # Assemblage de fichiers choisis dans le dialogue (chemins).
    scan = tmp_path / "scan.tif"
    scan.write_bytes(samples.tiff_pages([(100, 140, (0, 0, 0), 100), (100, 140, (0, 0, 0), 100)]))
    status, data = request(server, "POST", "api/assemble-files", {"paths": [str(photo), str(scan)]})
    assert status == 200 and data["doc"]["page_count"] == 3 and data["doc"]["name"] == "chantier - assemblé.pdf"
    # Refus : image illisible, garde-fous de la route.
    bad = b"\xff\xd8\xff" + b"\x00" * 50
    status, data = request(server, "POST", "api/upload?name=casse.jpg", bad)
    assert status == 400 and data["code"] == "bad_image"
    assert request(server, "POST", "api/upload?name=a.jpg", samples.jpeg_photo(), headers={"X-DestriPDF": "0"})[0] == 403
    assert request(server, "POST", "api/upload?name=a.jpg", samples.jpeg_photo(), token=False)[0] in (403, 404)
