from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from storage import (
    ModuleRecord,
    ProcedureRecord,
    clear_code_index,
    ensure_schema,
    insert_chunk,
    insert_module,
    insert_procedure,
    open_db,
    object_search_text,
)


MODULE_EXTENSIONS = {".bsl", ".txt", ".xml"}
START_RE = re.compile(
    r"^\s*(?P<kind>Процедура|Функция|Procedure|Function)\s+"
    r"(?P<name>[A-Za-zА-Яа-я_][\wА-Яа-я]*)"
    r"(?P<signature>\s*\([^)]*\))?",
    re.IGNORECASE,
)
END_RE = re.compile(
    r"^\s*(КонецПроцедуры|КонецФункции|EndProcedure|EndFunction)\b",
    re.IGNORECASE,
)


def read_text_file(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="ignore")


def extract_module_text(path: Path) -> str:
    return read_text_file(path)


def extract_procedures(module_text: str) -> list[tuple[str, str, int, int, str, str]]:
    lines = module_text.splitlines()
    procedures: list[tuple[str, str, int, int, str, str]] = []
    current: dict[str, object] | None = None

    for index, line in enumerate(lines, start=1):
        if current is None:
            match = START_RE.match(line)
            if not match:
                continue
            current = {
                "kind": match.group("kind"),
                "name": match.group("name"),
                "signature": f"{match.group('name')}{match.group('signature') or ''}",
                "line_start": index,
                "body": [line],
            }
            continue

        current["body"].append(line)
        if END_RE.match(line):
            body_lines = current["body"]  # type: ignore[assignment]
            body_text = "\n".join(body_lines)
            procedures.append(
                (
                    str(current["kind"]),
                    str(current["name"]),
                    int(current["line_start"]),
                    index,
                    str(current["signature"]),
                    body_text,
                )
            )
            current = None

    if current is not None:
        body_lines = current["body"]  # type: ignore[assignment]
        procedures.append(
            (
                str(current["kind"]),
                str(current["name"]),
                int(current["line_start"]),
                len(lines),
                str(current["signature"]),
                "\n".join(body_lines),
            )
        )

    return procedures


def index_code_root(root: Path, reset: bool = False) -> None:
    conn = open_db()
    ensure_schema(conn)
    if reset:
        clear_code_index(conn)

    files = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in MODULE_EXTENSIONS
    ]

    total_modules = 0
    total_procedures = 0

    conn.execute("BEGIN")
    try:
        for file_path in files:
            module_text = extract_module_text(file_path)
            rel_path = file_path.relative_to(root).as_posix()
            module_type = file_path.suffix.lower().lstrip(".")
            owner_full_name = file_path.parent.relative_to(root).as_posix() if file_path.parent != root else None
            module_record = ModuleRecord(
                path=rel_path,
                module_type=module_type,
                owner_full_name=owner_full_name,
                content=module_text,
                search_text=object_search_text(rel_path, module_type, owner_full_name, module_text),
            )
            insert_module(conn, module_record)
            insert_chunk(
                conn,
                chunk_type="module",
                chunk_key=rel_path,
                title=file_path.stem,
                content=module_text[:10000],
                section_name=owner_full_name or file_path.parent.name or root.name,
                object_full_name=owner_full_name,
            )
            total_modules += 1

            for kind, proc_name, line_start, line_end, signature, body_text in extract_procedures(module_text):
                proc_record = ProcedureRecord(
                    module_path=rel_path,
                    proc_name=proc_name,
                    kind=kind,
                    line_start=line_start,
                    line_end=line_end,
                    signature=signature,
                    search_text=object_search_text(rel_path, proc_name, kind, signature, body_text),
                )
                insert_procedure(conn, proc_record)
                insert_chunk(
                    conn,
                    chunk_type="procedure",
                    chunk_key=f"{rel_path}:{proc_name}",
                    title=proc_name,
                    content=body_text,
                    section_name=owner_full_name or file_path.parent.name or root.name,
                    object_full_name=owner_full_name,
                )
                total_procedures += 1

            if total_modules % 50 == 0:
                conn.commit()
                print("PROCESSED MODULES:", total_modules)

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print("MODULES:", total_modules)
    print("PROCEDURES:", total_procedures)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path, help="Root folder with exported 1C module files")
    parser.add_argument("--reset", action="store_true", help="Drop and recreate the index schema")
    args = parser.parse_args()

    root = args.root.expanduser().resolve()
    if not root.exists():
        raise SystemExit(f"Path does not exist: {root}")
    index_code_root(root, reset=args.reset)


if __name__ == "__main__":
    main()
