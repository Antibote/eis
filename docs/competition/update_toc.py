"""Обновить оглавление и поля через LibreOffice (UNO) и экспортировать PDF (с --save-docx — и пересохранить DOCX).

Запуск: python3 update_toc.py файл.docx   (нужен системный python3 с модулем uno)
"""
import os
import subprocess
import sys
import time
from pathlib import Path

import uno
from com.sun.star.beans import PropertyValue


def prop(name, value):
    p = PropertyValue()
    p.Name, p.Value = name, value
    return p


def main(src: str):
    src = Path(src).resolve()
    port = 2003
    profile = Path(os.environ.get("TMPDIR", "/tmp")) / "lo_toc_profile"
    proc = subprocess.Popen(["soffice", "--headless", "--invisible", "--norestore",
                             f"-env:UserInstallation=file://{profile}",
                             f"--accept=socket,host=127.0.0.1,port={port};urp;"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        local = uno.getComponentContext()
        resolver = local.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", local)
        for _ in range(60):
            try:
                ctx = resolver.resolve(f"uno:socket,host=127.0.0.1,port={port};urp;StarOffice.ComponentContext")
                break
            except Exception:
                time.sleep(0.5)
        else:
            raise RuntimeError("LibreOffice не запустился")
        desktop = ctx.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
        doc = desktop.loadComponentFromURL(src.as_uri(), "_blank", 0, (prop("Hidden", True),))
        for _ in range(2):  # второй проход — номера страниц после появления оглавления
            idx = doc.getDocumentIndexes()
            for i in range(idx.getCount()):
                idx.getByIndex(i).update()
            doc.getTextFields().refresh()
        if "--save-docx" in sys.argv:  # по умолчанию DOCX не трогаем: Word сам обновит оглавление при открытии
            doc.storeToURL(src.as_uri(), (prop("FilterName", "MS Word 2007 XML"),))
        doc.storeToURL(src.with_suffix(".pdf").as_uri(), (prop("FilterName", "writer_pdf_Export"),))
        doc.close(True)
        print("pdf:", src.with_suffix(".pdf").name)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main(sys.argv[1])
