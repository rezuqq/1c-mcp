from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from storage import DocRecord, ensure_schema, insert_doc, object_search_text, open_db, reset_schema


DOC_EXTENSIONS = {".md", ".txt", ".html", ".htm"}
TAG_RE = re.compile(r"<[^>]+>")
SCRIPT_STYLE_RE = re.compile(r"(?is)<(script|style).*?>.*?</\1>")
WS_RE = re.compile(r"\s+")


def read_text_file(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="ignore")


def extract_html_text(text: str) -> str:
    text = SCRIPT_STYLE_RE.sub(" ", text)
    text = TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = WS_RE.sub(" ", text)
    return text.strip()


def normalize_doc_text(path: Path) -> tuple[str, str]:
    raw = read_text_file(path)
    suffix = path.suffix.lower()
    if suffix in {".html", ".htm"}:
        return "html", extract_html_text(raw)
    return suffix.lstrip("."), raw.strip()


def title_from_path(path: Path, content: str) -> str:
    for line in content.splitlines():
        line = line.strip()
        if line:
            return line[:160]
    return path.stem


def index_docs_root(root: Path, reset: bool = False) -> None:
    conn = open_db()
    if reset:
        reset_schema(conn)
    ensure_schema(conn)

    files = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in DOC_EXTENSIONS
    ]

    total_docs = 0
    conn.execute("BEGIN")
    try:
        for file_path in files:
            source_type, content = normalize_doc_text(file_path)
            rel_path = file_path.relative_to(root).as_posix()
            title = title_from_path(file_path, content)
            insert_doc(
                conn,
                DocRecord(
                    path=rel_path,
                    title=title,
                    source_type=source_type,
                    content=content,
                    search_text=object_search_text(rel_path, title, source_type, content),
                ),
            )
            total_docs += 1
            if total_docs % 100 == 0:
                conn.commit()
                print("PROCESSED DOCS:", total_docs)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print("DOCS:", total_docs)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path, help="Root folder with documentation files")
    parser.add_argument("--reset", action="store_true", help="Drop and recreate the index schema")
    args = parser.parse_args()

    root = args.root.expanduser().resolve()
    if not root.exists():
        raise SystemExit(f"Path does not exist: {root}")
    index_docs_root(root, reset=args.reset)


if __name__ == "__main__":
    main()
