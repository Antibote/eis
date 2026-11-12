"""Предобработка сканов перед OCR (эксперимент E4 показал главные источники потерь: штампы, шум, наклон).

1. Цветные печати и штампы (синие, фиолетовые, красные) заменяются фоном — текст документа обычно чёрный.
2. Изображения низкого разрешения увеличиваются (первым шагом).
3. Импульсный шум (точки) подавляется медианным фильтром, если доля «выбивающихся» пикселей заметна.
4. Наклон оценивается по профилю строк (максимум дисперсии сумм по строкам) и исправляется.
Каждый шаг включается по признаку, а не всегда: чистый скан проходит без изменений.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter


def remove_color_marks(img: Image.Image) -> tuple[Image.Image, bool]:
    if img.mode not in ("RGB", "RGBA", "P"):
        return img, False
    hsv = np.asarray(img.convert("RGB").convert("HSV"), dtype=np.int16)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    # насыщенные пиксели синего/фиолетового (h ≈ 140–215 из 255) и красного (h < 12 или > 235) тонов
    mask = (s > 70) & (v > 40) & (((h > 140) & (h < 215)) | (h < 12) | (h > 235))
    if mask.mean() < 0.0005:
        return img.convert("L"), False
    gray = np.asarray(img.convert("L")).copy()
    gray[mask] = 248
    return Image.fromarray(gray), True


def denoise(img: Image.Image) -> tuple[Image.Image, bool]:
    med = img.filter(ImageFilter.MedianFilter(3))
    a, m = np.asarray(img, dtype=np.int16), np.asarray(med, dtype=np.int16)
    outliers = (np.abs(a - m) > 80).mean()
    return (med, True) if outliers > 0.01 else (img, False)


def deskew(img: Image.Image, max_angle: float = 6.0, step: float = 0.25) -> tuple[Image.Image, float]:
    small = img.copy()
    small.thumbnail((800, 800))
    arr = np.asarray(small, dtype=np.uint8)
    ink = Image.fromarray(((arr < 128) * 255).astype(np.uint8))

    def score(angle):
        rot = np.asarray(ink.rotate(angle, resample=Image.BILINEAR, expand=False), dtype=np.float32)
        return float(np.var(rot.sum(axis=1)))
    best = max(np.arange(-max_angle, max_angle + 1e-9, step), key=score)
    if abs(best) < 1.0:              # малый наклон Tesseract компенсирует сам, лишний поворот только размывает
        return img, 0.0
    return img.rotate(float(best), resample=Image.BICUBIC, expand=True, fillcolor=248), float(best)


def upscale(img: Image.Image, dpi: float | None) -> tuple[Image.Image, bool]:
    if dpi and dpi < 150:
        f = 300 / dpi
        return img.resize((int(img.width * f), int(img.height * f)), Image.LANCZOS), True
    return img, False


def prepare(img: Image.Image) -> tuple[Image.Image, list[str]]:
    """→ (изображение в оттенках серого, список применённых шагов). Увеличение — первым: на скане низкого
    разрешения тонкие штрихи иначе принимаются за точечный шум и стираются медианным фильтром."""
    steps = []
    dpi = img.info.get("dpi", (None,))[0]
    img, done = remove_color_marks(img)
    if done:
        steps.append("удалены цветные отметки")
    img = img.convert("L")
    img, done = upscale(img, dpi)
    if done:
        steps.append("увеличено разрешение")
    img, done = denoise(img)
    if done:
        steps.append("подавлен шум")
    img, angle = deskew(img)
    if angle:
        steps.append(f"выровнен наклон {angle:+.2f}°")
    return img, steps
