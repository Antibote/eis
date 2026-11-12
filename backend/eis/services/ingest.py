"""Загрузка корпуса документов: проверка → парсинг → извлечение → KnowledgeBase."""
from __future__ import annotations

import hashlib
import pickle
from pathlib import Path

from eis.domain.models import Document, KnowledgeBase, stable_id
from eis.extraction.pipeline import ParsedInput, run_pipeline
from eis.parsing.parsers import ParseError, parse
from eis.security.files import FileRejected, detect_format, validate_file


def _parser_version() -> str:
    """Хеш исходного кода разбора: кэш недействителен после любого изменения парсеров или предобработки."""
    import eis.parsing.parsers as p1
    import eis.parsing.preprocess as p2
    return hashlib.sha256(Path(p1.__file__).read_bytes() + Path(p2.__file__).read_bytes()).hexdigest()[:12]


def load_document(path: Path, project_id: str = "default", cache_dir: Path | None = None
                  ) -> tuple[ParsedInput | None, Document]:
    """Разбор файла. С cache_dir результат разбора (включая OCR) сохраняется по SHA-256 файла и версии
    парсера — при повторной обработке проекта неизменённые файлы не разбираются заново."""
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    doc = Document(id="doc:" + stable_id(project_id, sha), project_id=project_id, filename=path.name, fmt="?", sha256=sha)
    cache = cache_dir / f"{sha}-{doc.id[4:]}-{_parser_version()}.pkl" if cache_dir else None
    try:
        doc.fmt = detect_format(path.name)
        validate_file(path, doc.fmt)
        if cache and cache.exists():
            parsed = pickle.loads(cache.read_bytes())
            doc.metadata["parse_cache"] = True
        else:
            parsed = parse(path, doc.fmt, doc.id)
            if cache:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_bytes(pickle.dumps(parsed))
    except (FileRejected, ParseError) as e:
        doc.status, doc.error = "failed", str(e)
        return None, doc
    doc.status, doc.pages = "parsed", parsed.pages
    confs = [f.ocr_confidence for f in parsed.fragments if f.ocr and f.ocr_confidence is not None]
    if confs:
        doc.metadata["ocr_confidence"] = round(sum(confs) / len(confs), 3)
        doc.metadata["ocr_low_fragments"] = sum(c < 0.8 for c in confs)
    if getattr(parsed, "preprocessing", None):
        doc.metadata["preprocessing"] = parsed.preprocessing
    doc.is_synthetic = any("СИНТЕТИЧЕСКИЙ ДОКУМЕНТ" in h for h in parsed.header_lines + [f.text for f in parsed.fragments[:5]])
    if parsed.warnings:
        doc.metadata["warnings"] = parsed.warnings
    return ParsedInput(doc, parsed.fragments, parsed.header_lines), doc


def ingest_paths(paths: list[Path], project_id: str = "default", cache_dir: Path | None = None) -> KnowledgeBase:
    inputs, failed = [], []
    for p in sorted(paths):
        pi, doc = load_document(p, project_id, cache_dir)
        (inputs.append(pi) if pi else failed.append(doc))
    kb = run_pipeline(inputs, project_id)
    for d in failed:
        kb.documents[d.id] = d
    return kb


def ingest_dir(directory: Path, project_id: str = "default") -> KnowledgeBase:
    return ingest_paths([p for p in directory.iterdir() if p.is_file()], project_id)
