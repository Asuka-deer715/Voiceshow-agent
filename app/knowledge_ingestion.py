"""Import local reference documents into a reproducible, text-only collection."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_FORMATS = {".md", ".txt", ".pdf"}
CHAPTER = re.compile(r"^第[一二三四五六七八九十百\d]+章\s*.+")
HEADING = re.compile(r"^(?:#{1,6}\s*\S|\d+\.\d+(?:\.\d+)*[ \t]+\S|Q\d+[:：])")


def split_sections(text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    lines: list[str] = []
    chapter = ""
    heading = ""
    for line in text.splitlines():
        clean = line.strip()
        if CHAPTER.match(clean) or HEADING.match(clean):
            body = "\n".join(lines).strip()
            if body:
                sections.append((heading, body))
            lines = []
            if CHAPTER.match(clean):
                chapter = clean
                heading = clean
            else:
                heading = " / ".join(part for part in (chapter, clean.lstrip("# ")) if part)
        lines.append(line)
    body = "\n".join(lines).strip()
    if body:
        sections.append((heading, body))
    return sections


def split_long_text(text: str, limit: int = 1000, overlap: int = 100) -> list[str]:
    parts: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + limit, len(text))
        if end < len(text):
            boundary = text.rfind("\n", start + limit // 2, end)
            if boundary > start:
                end = boundary
        parts.append(text[start:end].strip())
        if end == len(text):
            break
        start = end - overlap
    return parts


def read_pages(path: Path) -> list[tuple[int | None, str]]:
    if path.suffix.lower() != ".pdf":
        return [(None, path.read_text(encoding="utf-8-sig"))]
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("PDF import requires pypdf; use an existing PDF-enabled Python environment.") from exc
    return [(number, page.extract_text() or "") for number, page in enumerate(PdfReader(path).pages, 1)]


def document_chunks(path: Path, collection: str) -> tuple[list[dict], dict]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    pages = read_pages(path)
    if not any(text.strip() for _, text in pages):
        raise ValueError(f"No extractable text in {path.name}; OCR is required for scanned PDFs.")
    first_page = pages[0][1]
    header_lines = [line.strip().lstrip("# ") for line in first_page.splitlines() if line.strip()]
    header = "\n".join(header_lines[:5 if path.suffix.lower() == ".pdf" else 2])
    chunks = []
    for page, text in pages:
        for heading, section in split_sections(text):
            if not any(line.strip() and not CHAPTER.match(line.strip()) and not HEADING.match(line.strip()) for line in section.splitlines()):
                continue
            for part in split_long_text(section):
                ordinal = len(chunks) + 1
                chunks.append({
                    "chunk_id": f"{collection}:{path.name}:{digest[:12]}:{ordinal}",
                    "collection": collection,
                    "source": path.name,
                    "source_sha256": digest,
                    "page": page,
                    "heading": heading,
                    "document_title": header_lines[0] if header_lines else path.stem,
                    "text": "\n\n".join(value for value in (header, heading, part) if value),
                })
    return chunks, {
        "source": path.name, "sha256": digest, "bytes": path.stat().st_size,
        "pages": len(pages) if path.suffix.lower() == ".pdf" else None,
        "empty_pages": [page for page, text in pages if not text.strip()],
        "chunks": len(chunks),
    }


def import_collection(source: Path, target: Path, collection: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", collection):
        raise ValueError("Collection names may contain letters, digits, underscores and hyphens.")
    files = sorted(path for path in source.iterdir() if path.is_file() and path.suffix.lower() in SUPPORTED_FORMATS)
    if not files:
        raise ValueError(f"No supported documents in {source}")
    chunks, documents = [], []
    for path in files:
        imported, metadata = document_chunks(path, collection)
        chunks.extend(imported)
        documents.append(metadata)
    output = target / collection
    raw_dir = output / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for path in files:
        destination = raw_dir / path.name
        if destination.resolve() != path.resolve():
            shutil.copy2(path, destination)
    manifest = {
        "schema_version": 1, "collection": collection,
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "document_count": len(documents), "chunk_count": len(chunks), "documents": documents,
    }
    chunk_path = output / "chunks.jsonl"
    temporary = output / "chunks.jsonl.tmp"
    temporary.write_text("".join(json.dumps(chunk, ensure_ascii=False) + "\n" for chunk in chunks), encoding="utf-8")
    temporary.replace(chunk_path)
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--collection", default="jc_ai")
    parser.add_argument("--target", type=Path, default=ROOT / "data" / "knowledge")
    args = parser.parse_args()
    result = import_collection(args.source, args.target, args.collection)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
