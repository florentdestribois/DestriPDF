"""Impression par Windows : placement des pages, pages choisies, rendu et envoi au pilote."""

import ctypes
import faulthandler
import time

import pymupdf as fitz
import pytest

from destripdf import document as d
from destripdf import printing as p


def test_place_fits_and_centres_a4_on_a4():
    # A4 sur A4 à 600 ppp, zone imprimable avec marges : réduit, centré, droit.
    spot = p.place(595, 842, 4760, 6800, 600, 600)
    assert spot.rotate == 0
    assert spot.width <= 4760 and spot.height <= 6800 and min(4760 - spot.width, 6800 - spot.height) <= 1
    assert spot.x == (4760 - spot.width) // 2 and spot.y == (6800 - spot.height) // 2
    assert abs(spot.width / spot.height - 595 / 842) < 0.001


def test_place_turns_landscape_page_on_portrait_sheet():
    spot = p.place(842, 595, 4760, 6800, 600, 600)
    assert spot.rotate == 270
    assert spot.height > spot.width  # posée en long sur la feuille


def test_page_turned_right_prints_upright():
    """Page portrait pivotée d'un quart de tour à droite dans DestriPDF (affichée en
    paysage) : sur une feuille portrait, elle s'imprime droite, et non à l'envers."""
    s = d.PdfSession(_red_square_pdf(rotation=90), name="facture.pdf")
    w, h = s.page_size(0)
    assert w > h
    spot = p.place(w, h, 4760, 6800, 600, 600)
    data, width, height = s.render_print(0, 0.5, spot.rotate)
    assert height > width

    def red(x, y):
        b, g, r, _ = data[(y * width + x) * 4:(y * width + x) * 4 + 4]
        return r > 200 and g < 60

    # carré rouge d'origine en haut à gauche, comme sur la page non pivotée
    assert red(10, 10) and not red(width - 10, 10) and not red(10, height - 10)


def test_place_handles_unequal_resolutions():
    # 600 × 1200 ppp : la page garde ses proportions sur le papier.
    spot = p.place(595, 842, 4800, 13600, 600, 1200)
    assert abs((spot.width / 600) / (spot.height / 1200) - 595 / 842) < 0.002


def test_parse_pages():
    assert p.parse_pages("1-3, 5", 5) == [0, 1, 2, 4]
    assert p.parse_pages(" 4 - 2 ", 5) == [1, 2, 3]  # plage à l'envers acceptée
    for bad in ("", "0", "6", "2-9", "1;2", "un"):
        with pytest.raises(p.PrintError):
            p.parse_pages(bad, 5)


def test_set_copies_marks_devmode_fields():
    devmode = bytes(220)
    out = p.set_copies(devmode, 3)
    fields = int.from_bytes(out[72:76], "little")
    assert fields & p.DM_COPIES and fields & p.DM_COLLATE
    assert int.from_bytes(out[86:88], "little") == 3 and int.from_bytes(out[100:102], "little") == 1
    assert len(out) == len(devmode)


def _caps(media, duplex=("psk:OneSided", "psk:TwoSidedLongEdge", "psk:TwoSidedShortEdge"), extra=""):
    options = "".join(
        f'<psf:Option name="{name}"><psf:ScoredProperty name="psk:MediaSizeWidth"><psf:Value>{w}</psf:Value>'
        f'</psf:ScoredProperty><psf:ScoredProperty name="psk:MediaSizeHeight"><psf:Value>{h}</psf:Value>'
        "</psf:ScoredProperty></psf:Option>"
        for name, w, h in media
    )
    duplex_xml = "".join(f'<psf:Option name="{o}"/>' for o in duplex)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<psf:PrintCapabilities xmlns:psf="{p.PSF}" xmlns:psk="{p.PSK}">
  <psf:Feature name="psk:PageMediaSize">{options}</psf:Feature>
  <psf:Feature name="psk:PageOrientation"><psf:Option name="psk:Portrait"/><psf:Option name="psk:Landscape"/></psf:Feature>
  <psf:Feature name="psk:JobDuplexAllDocumentsContiguously">{duplex_xml}</psf:Feature>
  <psf:Feature name="psk:JobBindAllDocuments"><psf:Option name="psk:None"/><psf:Option name="psk:Booklet"/></psf:Feature>
  <psf:Feature name="psk:JobStapleAllDocuments"><psf:Option name="psk:None"/><psf:Option name="psk:StapleTopLeft"/></psf:Feature>
  <psf:Feature name="psk:JobNUpAllDocumentsContiguously"><psf:Option><psf:ScoredProperty name="psk:PagesPerSheet"><psf:Value>1</psf:Value></psf:ScoredProperty></psf:Option></psf:Feature>
  {extra}
</psf:PrintCapabilities>"""


CANON_LIKE = _caps([("psk:NorthAmericaLetter", 215900, 279400), ("psk:ISOA3", 297000, 420000),
                    ("psk:ISOA4", 210000, 297000), ("psk:ISOA5", 148000, 210000)])


def test_feature_options_reads_driver_capabilities():
    assert p.feature_options(CANON_LIKE, "psk:JobBindAllDocuments") == ["psk:None", "psk:Booklet"]
    assert p.feature_options(CANON_LIKE, "psk:DocumentStaple") == []


def test_booklet_settings_are_those_of_a_word_document():
    """Livret mis en page par DestriPDF, envoyé comme un document Word recto verso :
    A4 ordinaire en portrait, recto verso bord long (la Canon n'appliquait pas le
    bord court en paysage), livret et agrafage de l'imprimante désactivés."""
    assert p.booklet_settings(CANON_LIKE, "a4") == {
        "psk:PageMediaSize": "psk:ISOA4",
        "psk:PageOrientation": "psk:Portrait",
        "psk:JobDuplexAllDocumentsContiguously": "psk:TwoSidedLongEdge",
        "psk:JobBindAllDocuments": "psk:None",
        "psk:JobStapleAllDocuments": "psk:None",
        "psk:JobNUpAllDocumentsContiguously": 1,
    }
    assert p.booklet_settings(CANON_LIKE, "a3")["psk:PageMediaSize"] == "psk:ISOA3"
    # imprimante qui ne connaîtrait que le bord court : bord court, versos sans demi-tour
    short_only = _caps([("psk:ISOA4", 210000, 297000)], duplex=("psk:OneSided", "psk:TwoSidedShortEdge"))
    settings = p.booklet_settings(short_only, "a4")
    assert settings["psk:JobDuplexAllDocumentsContiguously"] == "psk:TwoSidedShortEdge"
    assert p.backs_half_turn(settings) is False and p.backs_half_turn(settings, flip_backs=True) is True
    assert p.backs_half_turn(p.booklet_settings(CANON_LIKE, "a4")) is True
    # sans recto verso (Microsoft Print to PDF) : le reste est imposé quand même
    one_sided = _caps([("psk:ISOA4", 210000, 297000)], duplex=("psk:OneSided",))
    assert "psk:JobDuplexAllDocumentsContiguously" not in p.booklet_settings(one_sided, "a4")
    assert p.backs_half_turn(p.booklet_settings(one_sided, "a4")) is False


def test_media_option_ignores_rotated_paper():
    """« A4R » (A4 tourné) n'est jamais demandé : c'est le papier qui manquait à la Canon."""
    rotated_only = _caps([("psk:ISOA4Rotated", 297000, 210000), ("vendor:A4R", 210000, 297000)])
    assert p.media_option(rotated_only, "a4") is None
    with pytest.raises(p.PrintError):
        p.booklet_settings(rotated_only, "a4")
    vendor = _caps([("vendor:A4", 210000, 297000), ("psk:ISOA4Rotated", 297000, 210000)])
    assert p.media_option(vendor, "a4") == "vendor:A4"
    assert p.media_option(CANON_LIKE, "a4") == "psk:ISOA4"


def test_delta_ticket_is_well_formed():
    import xml.etree.ElementTree as ET

    root = ET.fromstring(p._delta_ticket({"psk:PageOrientation": "psk:Landscape", "psk:JobNUpAllDocumentsContiguously": 1}))
    features = {f.get("name"): f for f in root.iter(f"{{{p.PSF}}}Feature")}
    assert features["psk:PageOrientation"].find(f"{{{p.PSF}}}Option").get("name") == "psk:Landscape"
    assert features["psk:JobNUpAllDocumentsContiguously"].find(f".//{{{p.PSF}}}Value").text == "1"


CANON_DEVICE = p.Device(dpi_x=600, dpi_y=600, area_w=4720, area_h=6774, phys_w=4961, phys_h=7016, off_x=120, off_y=122)


def test_place_sheet_full_size_with_fold_in_the_middle():
    """Face A4 paysage sur la Canon (A4 portrait, 600 ppp, 5 mm non imprimables) :
    quart de tour vers la gauche, taille réelle, posée sur tout le papier, pli au
    milieu exact du papier."""
    spot = p.place_sheet(297 * 72 / 25.4, 210 * 72 / 25.4, CANON_DEVICE)
    assert spot.rotate == 270 and abs(spot.scale - 600 / 72) < 0.01
    assert abs(spot.width - 4961) <= 1 and abs(spot.height - 7016) <= 1
    assert spot.x == -120 and spot.y == -122  # origine du papier, dans la marge non imprimable
    fold = spot.y + spot.height / 2 + CANON_DEVICE.off_y
    assert abs(fold - CANON_DEVICE.phys_h / 2) <= 1
    assert abs(CANON_DEVICE.margin_pt() - 14.6) < 0.1
    # versos d'un demi-tour : quart de tour vers la droite ; papier en paysage : droit
    assert p.place_sheet(841.89, 595.28, CANON_DEVICE, upside_down=True).rotate == 90
    landscape = p.Device(600, 600, 6774, 4720, 7016, 4961, 122, 120)
    assert p.place_sheet(841.89, 595.28, landscape).rotate == 0
    assert p.place_sheet(841.89, 595.28, landscape, upside_down=True).rotate == 180


# --- Feuille simulée : recto, verso, retournement, lecture ---

SIM_COLOURS = {1: (230, 30, 30), 2: (30, 160, 30), 3: (40, 60, 230), 4: (240, 150, 0),
               5: (150, 40, 160), 6: (0, 170, 170), 7: (120, 80, 30), 8: (240, 110, 180)}


def _marked_pages(count):
    """Pages A4 de couleurs distinctes, un carré noir en haut à gauche (sens de lecture)."""
    doc = fitz.open()
    for number in range(1, count + 1):
        page = doc.new_page(width=595, height=842)
        colour = tuple(c / 255 for c in SIM_COLOURS[number])
        page.draw_rect(page.rect, color=colour, fill=colour)
        page.draw_rect(fitz.Rect(40, 40, 200, 200), color=(0, 0, 0), fill=(0, 0, 0))
    return doc.tobytes()


def _grid(data, width, height):
    """Image BGRA → grille d'étiquettes : numéro de page, 'noir' ou None (papier)."""
    grid = []
    for y in range(height):
        row = []
        for x in range(width):
            b, g, r = data[(y * width + x) * 4:(y * width + x) * 4 + 3]
            if max(r, g, b) < 60:
                row.append("noir")
                continue
            best = min(SIM_COLOURS, key=lambda n: sum((a - c) ** 2 for a, c in zip((r, g, b), SIM_COLOURS[n])))
            row.append(best if sum((a - c) ** 2 for a, c in zip((r, g, b), SIM_COLOURS[best])) < 2500 else None)
        grid.append(row)
    return grid


def _rot_cw(grid):
    return [list(row) for row in zip(*grid[::-1])]


def _mirror_x(grid):
    return [row[::-1] for row in grid]


def _mirror_y(grid):
    return grid[::-1]


def _reading(view):
    """(page de gauche, page de droite), chacune avec « à l'endroit ? » : carré noir
    dans le quart haut gauche de la page."""
    height, width = len(view), len(view[0])
    halves = []
    for x0, x1 in ((0, width // 2), (width // 2, width)):
        cells = [(x, y, view[y][x]) for y in range(height) for x in range(x0, x1)]
        numbers = [c for _, _, c in cells if isinstance(c, int)]
        if not numbers:
            halves.append((None, None))
            continue
        number = max(set(numbers), key=numbers.count)
        xs = [x for x, _, c in cells if c == number]
        ys = [y for _, y, c in cells if c == number]
        bx0, bx1, by0, by1 = min(xs), max(xs), min(ys), max(ys)
        black = [(x, y) for x, y, c in cells if c == "noir" and bx0 <= x <= bx1 and by0 <= y <= by1]
        cx = sum(x for x, _ in black) / len(black)
        cy = sum(y for _, y in black) / len(black)
        halves.append((number, cx < (bx0 + bx1) / 2 and cy < (by0 + by1) / 2))
    return halves


def _simulate(count, device, duplex, flip_backs=False):
    """Imprime les faces du livret sur une feuille simulée et les lit comme un lecteur :
    recto tourné pour lire la page de droite à l'endroit, puis feuille retournée autour
    du pli (axe vertical de la vue). Le verso imprimé obéit à la définition du
    retournement : bord long = autour des grands côtés du papier, bord court = des petits."""
    from destripdf.booklet import SHEETS

    session = d.PdfSession(_marked_pages(count), name="livret.pdf")
    faces = session.impose_booklet(list(range(count)), SHEETS["a4"], 14, "left")
    settings = {"psk:JobDuplexAllDocumentsContiguously": duplex}
    turn = p.backs_half_turn(settings, flip_backs)
    sheets = []
    for sheet in range(faces.page_count // 2):
        printed = []
        for side in (0, 1):
            spot = p.place_sheet(841.89, 595.28, device, upside_down=turn and side == 1)
            data, width, height = d.render_bgra(faces.__getitem__, 2 * sheet + side, spot.scale, spot.rotate)
            printed.append(_grid(data, width, height))
        front, back = printed
        paper_portrait = len(front) > len(front[0])
        # la face 2 vue depuis la face 1, à travers le papier
        long_axis_vertical = paper_portrait
        flip_vertical_axis = (duplex == p.DUPLEX_LONG) == long_axis_vertical
        through = _mirror_x(back) if flip_vertical_axis else _mirror_y(back)
        # le lecteur tourne la feuille pour lire le recto (page de droite à l'endroit)
        view, behind = front, through
        for _ in range(4):
            if len(view[0]) > len(view) and _reading(view)[1][1]:
                break
            view, behind = _rot_cw(view), _rot_cw(behind)
        else:
            raise AssertionError("recto illisible dans tous les sens")
        sheets.append((_reading(view), _reading(_mirror_x(behind))))
    return sheets


SIM_PORTRAIT = p.Device(30, 30, 248, 351, 248, 351, 0, 0)  # A4 portrait, 30 ppp
SIM_LANDSCAPE = p.Device(30, 30, 351, 248, 351, 248, 0, 0)


@pytest.mark.parametrize("count", [4, 8])
def test_simulated_sheet_reads_as_a_booklet_long_edge_portrait(count):
    """Cas de la Canon : A4 portrait, recto verso bord long, versos d'un demi-tour.
    Pour chaque feuille : recto (gauche | droite) et verso à l'endroit, aux places
    données par l'ordre de pliage (4 pages : 4|1 puis 2|3 ; 8 pages : 8|1, 2|7, 6|3, 4|5)."""
    expected = {4: [((4, 1), (2, 3))], 8: [((8, 1), (2, 7)), ((6, 3), (4, 5))]}[count]
    for (front, back), (want_front, want_back) in zip(_simulate(count, SIM_PORTRAIT, p.DUPLEX_LONG), expected):
        assert front == [(want_front[0], True), (want_front[1], True)]
        assert back == [(want_back[0], True), (want_back[1], True)]


def test_simulated_sheet_short_edge_landscape_needs_no_turn():
    """Imprimante en paysage, bord court : versos sans demi-tour, livret juste aussi."""
    (front, back), = _simulate(4, SIM_LANDSCAPE, p.DUPLEX_SHORT)
    assert front == [(4, True), (1, True)] and back == [(2, True), (3, True)]


def test_simulated_sheet_without_half_turn_would_be_upside_down():
    """Garde-fou : bord long sans demi-tour (ou « Retourner les versos » coché à tort)
    donne des versos tête en bas et inversés — la simulation le voit."""
    (front, back), = _simulate(4, SIM_PORTRAIT, p.DUPLEX_LONG, flip_backs=True)
    assert front == [(4, True), (1, True)]
    assert back == [(3, False), (2, False)]


def test_capabilities_from_parallel_requests():
    """Plusieurs requêtes simultanées (changement rapide d'imprimante) : aucune erreur."""
    import concurrent.futures

    printing = p.WindowsPrinting()
    names, _ = printing.printers()
    if not names:
        pytest.skip("aucune imprimante")

    def caps(name):
        try:
            return printing.capabilities(name)
        except p.PrintError:
            return None  # imprimante réseau injoignable : erreur explicite, pas une panne

    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        results = list(pool.map(caps, names * 3))
    assert all(r is None or set(r) == {"duplex", "sheets"} for r in results)


def test_booklet_settings_accepted_by_real_drivers():
    """Sur chaque imprimante du poste (Canon de l'atelier comprise) : réglages du livret
    acceptés par le pilote et relus tels quels — ceux d'un document Word recto verso,
    A4 portrait, bord long —, copies gardées, jamais la fonction Livret de
    l'imprimante ni un papier tourné. Quand les réglages par défaut conviennent
    (cas de la Canon), ils sont gardés tels quels. Rien n'est imprimé."""
    printing = p.WindowsPrinting()
    tried = []
    for name in printing.printers()[0]:
        try:
            caps = printing.capabilities(name)
        except p.PrintError:
            continue  # imprimante réseau injoignable
        if "a4" not in caps["sheets"]:
            continue
        devmode, settings = printing.settings.booklet_devmode(name, 2, "a4")
        summary = p.ticket_summary(name, devmode)
        assert {k: summary.get(k) for k in settings} == settings, name
        assert summary.get("psk:PageMediaSize") == "psk:ISOA4"
        assert summary.get("psk:PageOrientation") == "psk:Portrait"
        assert summary.get("psk:JobBindAllDocuments") in (None, "psk:None")
        assert int.from_bytes(devmode[86:88], "little") == 2
        if caps["duplex"]:
            assert summary.get("psk:JobDuplexAllDocumentsContiguously", summary.get("psk:DocumentDuplex")) == p.DUPLEX_LONG
        with p._Printer(name) as printer:
            default = printer.devmode()
        current = p.ticket_summary(name, default)
        if all(current.get(k) == v for k, v in settings.items()):
            # réglages par défaut gardés : seul le nombre de copies diffère
            assert devmode[:86] == default[:86] and devmode[88:] == default[88:], name
        hdc = p.create_dc(name, devmode)
        try:
            device = p.device_of(hdc)
        finally:
            p._api()[0].DeleteDC(hdc)
        assert device.phys_w < device.phys_h, f"{name} : papier en paysage"
        assert abs(device.phys_w / device.dpi_x * 25.4 - 210) < 2 and abs(device.phys_h / device.dpi_y * 25.4 - 297) < 2
        tried.append(name)
    if not tried:
        pytest.skip("aucune imprimante utilisable")

def _red_square_pdf(rotation=0):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 72), "Facture", fontsize=14)
    page.add_rect_annot(fitz.Rect(0, 0, 100, 100)).set_colors(stroke=(1, 0, 0), fill=(1, 0, 0))
    page.first_annot.update()
    if rotation:
        page.set_rotation(rotation)
    return doc.tobytes()


def test_render_print_is_bgra_top_down_with_annotations():
    s = d.PdfSession(_red_square_pdf(), name="facture.pdf")
    data, width, height = s.render_print(0, 1.0)
    assert (width, height) == (595, 842) and len(data) == width * height * 4
    # coin haut gauche : annotation rouge, en BGRA (bleu, vert, rouge, opaque)
    b, g, r, a = data[(20 * width + 20) * 4:(20 * width + 20) * 4 + 4]
    assert r > 200 and g < 60 and b < 60 and a == 255
    # rotation d'un quart de tour : dimensions échangées
    data, width, height = s.render_print(0, 0.5, 90)
    assert (width, height) == (421, 298) or abs(width - 421) <= 1 and abs(height - 298) <= 1
    assert s.page_size(0) == (595, 842)


PRINT_TO_PDF = "Microsoft Print to PDF"


@pytest.fixture()
def quiet_driver():
    """Le pilote lève puis intercepte lui-même une exception COM (0x80040155) que
    faulthandler signale à tort comme fatale : suspendu pendant ce test."""
    enabled = faulthandler.is_enabled()
    faulthandler.disable()
    yield
    if enabled:
        faulthandler.enable()


def test_print_pages_through_windows_driver(tmp_path, quiet_driver):
    """Envoi réel à un pilote Windows (« Microsoft Print to PDF », sortie dans un fichier)."""
    printing = p.WindowsPrinting()
    names, default = printing.printers()
    assert default == "" or default in names
    if PRINT_TO_PDF not in names:
        pytest.skip("imprimante « Microsoft Print to PDF » absente")
    doc = fitz.open("pdf", _red_square_pdf())
    landscape = doc.new_page(width=842, height=595)
    landscape.insert_text((72, 72), "Plan", fontsize=14)
    s = d.PdfSession(doc.tobytes(), name="devis.pdf")
    seen = []
    target = tmp_path / "sortie.pdf"
    # contexte préparé avec les réglages du pilote (deux exemplaires assemblés acceptés)
    hdc = p.create_dc(PRINT_TO_PDF, printing.settings.job_devmode(PRINT_TO_PDF, 2))
    p.print_pages(hdc, "devis.pdf", [0, 1], s.page_size, s.render_print,
                  progress=lambda done, total: seen.append((done, total)), output=str(target))
    assert seen == [(1, 2), (2, 2)]
    deadline = time.time() + 30
    while not (target.exists() and target.stat().st_size > 0) and time.time() < deadline:
        time.sleep(0.2)
    time.sleep(0.5)
    out = fitz.open(target)
    # deux exemplaires assemblés par le pilote : 1, 2, 1, 2
    assert out.page_count == 4

    def red_corner(page):
        pix = page.get_pixmap(dpi=36)
        red = [(x, y) for x in range(pix.width) for y in range(pix.height)
               if pix.pixel(x, y)[0] > 200 and pix.pixel(x, y)[1] < 80]
        return bool(red) and max(x for x, _ in red) < pix.width / 3 and max(y for _, y in red) < pix.height / 4

    assert [red_corner(page) for page in out] == [True, False, True, False]
    # feuilles portrait du pilote ; la page paysage y est tournée d'un quart de tour
    assert all(page.rect.width < page.rect.height for page in out)


PALETTE = {1: (1, 0, 0), 2: (0, 0.6, 0), 3: (0, 0, 1), 4: (1, 0.55, 0), 5: (0.55, 0, 0.55), 6: (0, 0.7, 0.7)}


def _colour_pages():
    """Six pages A4, chacune marquée d'un bandeau de sa couleur en haut de page."""
    doc = fitz.open()
    for number, colour in PALETTE.items():
        page = doc.new_page(width=595, height=842)
        page.draw_rect(fitz.Rect(40, 40, 555, 300), color=colour, fill=colour)
        page.insert_text((60, 400), f"Page {number}", fontsize=40)
    return doc.tobytes()


def _halves(page):
    """Pour chaque moitié de la face : (numéro de page reconnu par sa couleur ou None,
    bandeau en haut ?). La feuille A4 portrait est d'abord tournée d'un quart de tour
    vers la droite, pour défaire le quart de tour vers la gauche de l'impression."""
    pix = page.get_pixmap(matrix=fitz.Matrix(20 / 72, 20 / 72).prerotate(90))
    found = []
    for half in (0, 1):
        votes, ys = {}, []
        for x in range(half * pix.width // 2, (half + 1) * pix.width // 2):
            for y in range(pix.height):
                r, g, b = (v / 255 for v in pix.pixel(x, y)[:3])
                if min(r, g, b) > 0.85:
                    continue  # papier blanc
                number = min(PALETTE, key=lambda n: sum((a - c) ** 2 for a, c in zip((r, g, b), PALETTE[n])))
                if sum((a - c) ** 2 for a, c in zip((r, g, b), PALETTE[number])) < 0.05:
                    votes[number] = votes.get(number, 0) + 1
                    ys.append(y)
        if not votes:
            found.append((None, None))
            continue
        number = max(votes, key=votes.get)
        found.append((number, sum(ys) / len(ys) < pix.height / 2))
    return found


def _print_booklet(tmp_path, upside_down_backs):
    from destripdf.booklet import MIN_MARGIN, SHEETS

    printing = p.WindowsPrinting()
    if PRINT_TO_PDF not in printing.printers()[0]:
        pytest.skip("imprimante « Microsoft Print to PDF » absente")
    session = d.PdfSession(_colour_pages(), name="livret.pdf")
    target = tmp_path / ("livret-inverse.pdf" if upside_down_backs else "livret.pdf")
    made = []

    def impose(margin):
        made.append(margin)
        return session.impose_booklet(list(range(6)), SHEETS["a4"], max(MIN_MARGIN, margin), "left")

    def render_face(faces, index, scale, rotate):
        return d.render_bgra(faces.__getitem__, index, scale, rotate)

    faces = printing.print_booklet(PRINT_TO_PDF, 1, "livret.pdf", "a4", impose, render_face,
                                   upside_down_backs=upside_down_backs, output=str(target))
    assert faces == 4 and len(made) == 1
    deadline = time.time() + 30
    while not (target.exists() and target.stat().st_size > 0) and time.time() < deadline:
        time.sleep(0.2)
    time.sleep(0.5)
    return fitz.open(target)


def test_booklet_printed_through_windows_driver(tmp_path, quiet_driver):
    """Livret réel par un pilote Windows : 6 pages → 2 feuilles A4 portrait (comme un
    document Word), 4 faces (recto, verso, recto, verso), chaque face tournée d'un quart
    de tour vers la gauche, chaque page à sa place et droite. Sans recto verso
    (« Microsoft Print to PDF »), pas de demi-tour des versos."""
    out = _print_booklet(tmp_path, upside_down_backs=False)
    assert out.page_count == 4
    for page in out:
        assert abs(page.rect.width - 595) < 3 and abs(page.rect.height - 842) < 3  # A4 portrait
    expected = [(None, 1), (2, None), (6, 3), (4, 5)]
    for page, (left, right) in zip(out, expected):
        halves = _halves(page)
        assert [h[0] for h in halves] == [left, right]
        assert all(top for number, top in halves if number)  # bandeaux en haut : faces droites


def test_booklet_backs_turned_upside_down_when_asked(tmp_path, quiet_driver):
    """« Retourner les versos » : chaque verso tourne d'un demi-tour (gauche ↔ droite,
    haut ↔ bas), les rectos ne bougent pas."""
    out = _print_booklet(tmp_path, upside_down_backs=True)
    assert [[h[0] for h in _halves(page)] for page in out] == [[None, 1], [None, 2], [6, 3], [5, 4]]
    assert [h[1] for h in _halves(out[1]) if h[0]] == [False]  # bandeau en bas : verso tourné
    assert [h[1] for h in _halves(out[0]) if h[0]] == [True]