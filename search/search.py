from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from storage import (
    ensure_schema,
    format_metadata_object,
    format_rows,
    get_object_details,
    list_sections,
    open_db,
    search_docs,
    search_attributes,
    search_chunks,
    search_metadata_objects,
    search_modules,
    search_procedures,
    search_type_links,
)


conn = open_db()
ensure_schema(conn)


def cmd_search(text: str) -> str:
    rows = search_metadata_objects(conn, text, limit=20)
    if not rows:
        return "Ничего не найдено"
    return format_rows(rows, ["full_name", "section_name", "object_type", "name"])


def cmd_docs(text: str) -> str:
    rows = search_docs(conn, text, limit=20)
    if not rows:
        return "Ничего не найдено"
    return format_rows(rows, ["path", "title", "source_type"])


def cmd_object(full_name: str) -> str:
    row, attributes, links = get_object_details(conn, full_name)
    if row is None:
        return "Ничего не найдено"
    return format_metadata_object(row, attributes, links)


def cmd_attributes(text: str) -> str:
    rows = search_attributes(conn, text, limit=20)
    if not rows:
        return "Ничего не найдено"
    return format_rows(
        rows,
        ["object_full_name", "section_name", "container_name", "name", "value_type"],
    )


def cmd_types(text: str) -> str:
    rows = search_type_links(conn, text, limit=20)
    if not rows:
        return "Ничего не найдено"
    return format_rows(rows, ["object_full_name", "section_name", "attribute_name", "referenced_type"])


def cmd_chunks(text: str) -> str:
    rows = search_chunks(conn, text, limit=10)
    if not rows:
        return "Ничего не найдено"
    output = []
    for row in rows:
        content = row["content"]
        if len(content) > 1500:
            content = content[:1500] + "..."
        output.append(
            "\n".join(
                [
                    f"Тип: {row['chunk_type']}",
                    f"Ключ: {row['chunk_key']}",
                    f"Заголовок: {row['title']}",
                    content,
                ]
            )
        )
    return "\n\n-----------------\n\n".join(output)


def cmd_modules(text: str) -> str:
    rows = search_modules(conn, text, limit=20)
    if not rows:
        return "Ничего не найдено"
    return format_rows(rows, ["path", "module_type", "owner_full_name"])


def cmd_procedures(text: str) -> str:
    rows = search_procedures(conn, text, limit=20)
    if not rows:
        return "Ничего не найдено"
    return format_rows(rows, ["module_path", "proc_name", "kind", "signature"])


def cmd_sections() -> str:
    rows = list_sections(conn, limit=100)
    if not rows:
        return "Ничего не найдено"
    return format_rows(rows, ["name", "object_count"])


while True:
    cmd = input("\nCOMMAND: ").strip()
    if cmd == "exit":
        break
    if cmd.startswith("search "):
        print("\n" + cmd_search(cmd[len("search ") :]))
    elif cmd.startswith("docs "):
        print("\n" + cmd_docs(cmd[len("docs ") :]))
    elif cmd.startswith("object "):
        print("\n" + cmd_object(cmd[len("object ") :]))
    elif cmd.startswith("attrs "):
        print("\n" + cmd_attributes(cmd[len("attrs ") :]))
    elif cmd.startswith("types "):
        print("\n" + cmd_types(cmd[len("types ") :]))
    elif cmd.startswith("chunks "):
        print("\n" + cmd_chunks(cmd[len("chunks ") :]))
    elif cmd.startswith("modules "):
        print("\n" + cmd_modules(cmd[len("modules ") :]))
    elif cmd.startswith("procs "):
        print("\n" + cmd_procedures(cmd[len("procs ") :]))
    elif cmd == "sections":
        print("\n" + cmd_sections())
    else:
        print("UNKNOWN COMMAND")
