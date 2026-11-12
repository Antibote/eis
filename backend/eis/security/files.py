"""Проверка загружаемых файлов: формат по сигнатуре, размер, архивные бомбы, макросы."""
from __future__ import annotations

import zipfile
from pathlib import Path

MAX_FILE_MB = 50
MAX_UNZIPPED_MB = 200

SIGNATURES = {
    "pdf": [b"%PDF-"],
    "docx": [b"PK\x03\x04"],
    "xlsx": [b"PK\x03\x04"],
    "png": [b"\x89PNG\r\n\x1a\n"],
    "jpg": [b"\xff\xd8\xff"],
    "jpeg": [b"\xff\xd8\xff"],
}
TEXT_FORMATS = {"txt", "csv"}
ALLOWED = set(SIGNATURES) | TEXT_FORMATS


class FileRejected(Exception):
    pass


def detect_format(filename: str) -> str:
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext not in ALLOWED:
        raise FileRejected(f"Недопустимое расширение «.{ext}». Разрешены: {', '.join(sorted(ALLOWED))}")
    return ext


def validate_file(path: Path, fmt: str) -> None:
    size = path.stat().st_size
    if size == 0:
        raise FileRejected("Пустой файл")
    if size > MAX_FILE_MB * 2**20:
        raise FileRejected(f"Файл больше {MAX_FILE_MB} МБ")
    head = path.open("rb").read(16)
    if fmt in SIGNATURES and not any(head.startswith(s) for s in SIGNATURES[fmt]):
        raise FileRejected(f"Содержимое не соответствует формату {fmt} (сигнатура файла)")
    if fmt in TEXT_FORMATS:
        sample = path.open("rb").read(65536)
        if b"\x00" in sample:
            raise FileRejected("Текстовый файл содержит двоичные данные")
    if fmt in ("docx", "xlsx"):
        try:
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
                total = sum(i.file_size for i in z.infolist())
        except zipfile.BadZipFile as e:
            raise FileRejected("Повреждённый контейнер OOXML") from e
        if total > MAX_UNZIPPED_MB * 2**20:
            raise FileRejected("Подозрение на архивную бомбу: слишком большой распакованный объём")
        if any(n.lower().endswith("vbaproject.bin") for n in names):
            raise FileRejected("Документ содержит макросы — загрузка запрещена")
        need = "word/document.xml" if fmt == "docx" else "xl/workbook.xml"
        if need not in names:
            raise FileRejected(f"Структура файла не соответствует {fmt}")
