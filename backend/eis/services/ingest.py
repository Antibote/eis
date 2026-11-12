"""Загрузка корпуса документов: проверка → парсинг → извлечение → KnowledgeBase."""
from __future__ import annotations

import hashlib
from pathlib import Path

from eis.domain.models import Document, KnowledgeBase, stable_id
from eis.extraction.pipeline import ParsedInput, run_pipeline
from eis.parsing.parsers import ParseError, parse
from eis.security.files import FileRejected, detect_format, validate_file


def load_document(path: Path, project_id: str = "default") -> tuple[ParsedInput | None, Document]:
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    doc = Document(id="doc:" + stable_id(project_id, sha), project_id=project_id, filename=path.name, fmt="?", sha256=sha)
    try:
        doc.fmt = detect_format(path.name)
        validate_file(path, doc.fmt)
        parsed = parse(path, doc.fmt, doc.id)
    except (FileRejected, ParseError) as e:
        doc.status, doc.error = "failed", str(e)
        return None, doc
    doc.status, doc.pages = "parsed", parsed.pages
    doc.is_synthetic = any("СИНТЕТИЧЕСКИЙ ДОКУМЕНТ" in h for h in parsed.header_lines + [f.text for f in parsed.fragments[:5]])
    if parsed.warnings:
        doc.metadata["warnings"] = parsed.warnings
    return ParsedInput(doc, parsed.fragments, parsed.header_lines), doc


def ingest_paths(paths: list[Path], project_id: str = "default") -> KnowledgeBase:
    inputs, failed = [], []
    for p in sorted(paths):
        pi, doc = load_document(p, project_id)
        (inputs.append(pi) if pi else failed.append(doc))
    kb = run_pipeline(inputs, project_id)
    for d in failed:
        kb.documents[d.id] = d
    return kb


def ingest_dir(directory: Path, project_id: str = "default") -> KnowledgeBase:
    return ingest_paths([p for p in directory.iterdir() if p.is_file()], project_id)
