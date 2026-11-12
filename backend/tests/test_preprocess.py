"""Предобработка сканов: удаление цветных отметок, выравнивание наклона, отсутствие лишних шагов."""
from PIL import Image, ImageDraw, ImageFont

from eis.parsing.preprocess import deskew, prepare, remove_color_marks

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def page(color=False):
    img = Image.new("RGB" if color else "L", (900, 500), (248, 248, 248) if color else 248)
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(FONT, 26)
    for i in range(8):
        d.text((40, 40 + i * 50), "Рабочее давление не более 1,6 МПа", font=f, fill=(15, 15, 15) if color else 15)
    return img, d


def test_clean_page_is_not_modified():
    img, _ = page()
    _, steps = prepare(img)
    assert steps == []


def test_blue_stamp_is_removed_text_kept():
    img, d = page(color=True)
    d.ellipse((500, 150, 850, 350), outline=(40, 70, 190), width=8)
    out, done = remove_color_marks(img)
    assert done and out.mode == "L"
    px = out.load()
    assert px[500, 250] > 200            # контур печати стал фоном
    assert min(out.crop((40, 40, 400, 70)).getdata()) < 60   # чёрный текст остался


def test_skew_is_detected():
    img, _ = page()
    rotated = img.rotate(3, resample=Image.BICUBIC, expand=True, fillcolor=248)
    _, angle = deskew(rotated)
    assert abs(angle + 3) < 0.6
