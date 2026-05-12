from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from paths import DB_PATH


def _casefold(value: str | None) -> str:
    return (value or "").casefold()


def _like_pattern(value: str) -> str:
    folded = _casefold(value)
    folded = folded.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{folded}%"


def open_db(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def reset_schema(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.executescript(
        """
        DROP TABLE IF EXISTS docs;
        DROP TABLE IF EXISTS sections;
        DROP TABLE IF EXISTS metadata_objects;
        DROP TABLE IF EXISTS metadata_attributes;
        DROP TABLE IF EXISTS type_links;
        DROP TABLE IF EXISTS chunks;
        DROP TABLE IF EXISTS objects;
        DROP TABLE IF EXISTS modules;
        DROP TABLE IF EXISTS procedures;
        """
    )
    conn.commit()


def ensure_schema(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS docs (
            path TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            source_type TEXT NOT NULL,
            content TEXT NOT NULL,
            search_text TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sections (
            name TEXT PRIMARY KEY,
            object_count INTEGER NOT NULL DEFAULT 0,
            chunk_text TEXT NOT NULL,
            search_text TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS metadata_objects (
            full_name TEXT PRIMARY KEY,
            section_name TEXT NOT NULL,
            object_type TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            chunk_text TEXT NOT NULL,
            search_text TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS metadata_attributes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            object_full_name TEXT NOT NULL,
            section_name TEXT NOT NULL,
            container_name TEXT NOT NULL,
            attribute_kind TEXT NOT NULL,
            name TEXT NOT NULL,
            value_type TEXT,
            chunk_text TEXT NOT NULL,
            search_text TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS type_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            object_full_name TEXT NOT NULL,
            section_name TEXT NOT NULL,
            container_name TEXT NOT NULL,
            attribute_kind TEXT NOT NULL,
            attribute_name TEXT NOT NULL,
            referenced_type TEXT NOT NULL,
            search_text TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chunk_type TEXT NOT NULL,
            chunk_key TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            section_name TEXT NOT NULL,
            object_full_name TEXT,
            search_text TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS modules (
            path TEXT PRIMARY KEY,
            module_type TEXT,
            owner_full_name TEXT,
            content TEXT NOT NULL,
            search_text TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS procedures (
            module_path TEXT NOT NULL,
            proc_name TEXT NOT NULL,
            kind TEXT,
            line_start INTEGER,
            line_end INTEGER,
            signature TEXT,
            search_text TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_sections_search_text ON sections(search_text);
        CREATE INDEX IF NOT EXISTS idx_docs_search_text ON docs(search_text);
        CREATE INDEX IF NOT EXISTS idx_metadata_objects_search_text ON metadata_objects(search_text);
        CREATE INDEX IF NOT EXISTS idx_metadata_objects_section_name ON metadata_objects(section_name);
        CREATE INDEX IF NOT EXISTS idx_metadata_attributes_search_text ON metadata_attributes(search_text);
        CREATE INDEX IF NOT EXISTS idx_metadata_attributes_object_full_name ON metadata_attributes(object_full_name);
        CREATE INDEX IF NOT EXISTS idx_type_links_search_text ON type_links(search_text);
        CREATE INDEX IF NOT EXISTS idx_type_links_referenced_type ON type_links(referenced_type);
        CREATE INDEX IF NOT EXISTS idx_chunks_search_text ON chunks(search_text);
        CREATE INDEX IF NOT EXISTS idx_modules_search_text ON modules(search_text);
        CREATE INDEX IF NOT EXISTS idx_procedures_search_text ON procedures(search_text);
        """
    )
    conn.commit()


def split_types(value_type: str | None) -> list[str]:
    if not value_type:
        return []
    return [part.strip() for part in value_type.split(",") if part.strip()]


def normalize_text(*parts: str | None) -> str:
    return " ".join(part.strip() for part in parts if part and part.strip())


@dataclass(slots=True)
class MetadataAttributeRecord:
    object_full_name: str
    section_name: str
    container_name: str
    attribute_kind: str
    name: str
    value_type: str | None
    chunk_text: str
    search_text: str


@dataclass(slots=True)
class MetadataObjectRecord:
    section_name: str
    object_type: str
    full_name: str
    name: str
    description: str | None
    chunk_text: str
    search_text: str


@dataclass(slots=True)
class SectionRecord:
    name: str
    object_count: int
    chunk_text: str
    search_text: str


@dataclass(slots=True)
class DocRecord:
    path: str
    title: str
    source_type: str
    content: str
    search_text: str


def object_chunk_text(
    section_name: str,
    object_type: str,
    full_name: str,
    name: str,
    description: str | None,
    attributes: Iterable[tuple[str, str | None]],
    tabular_sections: Iterable[tuple[str, list[tuple[str, str | None]]]],
    standard_attributes: Iterable[tuple[str, str | None]],
) -> str:
    lines = [
        f"Раздел: {section_name}",
        f"Объект: {full_name}",
        f"Имя: {name}",
        f"Тип: {object_type}",
    ]
    if description:
        lines.append(f"Описание: {description}")

    attributes = list(attributes)
    if attributes:
        lines.append("Реквизиты:")
        for attr_name, value_type in attributes:
            if value_type:
                lines.append(f"- {attr_name}: {value_type}")
            else:
                lines.append(f"- {attr_name}")

    tabular_sections = list(tabular_sections)
    if tabular_sections:
        lines.append("Табличные части:")
        for tab_name, tab_attrs in tabular_sections:
            lines.append(f"- {tab_name}")
            for attr_name, value_type in tab_attrs:
                if value_type:
                    lines.append(f"  - {attr_name}: {value_type}")
                else:
                    lines.append(f"  - {attr_name}")

    standard_attributes = list(standard_attributes)
    if standard_attributes:
        lines.append("Стандартные реквизиты:")
        for attr_name, value_type in standard_attributes:
            if value_type:
                lines.append(f"- {attr_name}: {value_type}")
            else:
                lines.append(f"- {attr_name}")

    return "\n".join(lines)


def section_chunk_text(section_name: str, object_names: Iterable[str]) -> str:
    names = list(object_names)
    preview = ", ".join(names[:40])
    suffix = "" if len(names) <= 40 else f" ... (+{len(names) - 40})"
    return "\n".join(
        [
            f"Раздел: {section_name}",
            f"Количество объектов: {len(names)}",
            f"Объекты: {preview}{suffix}",
        ]
    )


def object_search_text(*parts: str | None) -> str:
    return _casefold(normalize_text(*parts))


def insert_section(conn: sqlite3.Connection, record: SectionRecord) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO sections (name, object_count, chunk_text, search_text)
        VALUES (?, ?, ?, ?)
        """,
        (record.name, record.object_count, record.chunk_text, record.search_text),
    )


def insert_doc(conn: sqlite3.Connection, record: DocRecord) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO docs (path, title, source_type, content, search_text)
        VALUES (?, ?, ?, ?, ?)
        """,
        (record.path, record.title, record.source_type, record.content, record.search_text),
    )


def insert_metadata_object(conn: sqlite3.Connection, record: MetadataObjectRecord) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO metadata_objects (
            full_name, section_name, object_type, name, description, chunk_text, search_text
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.full_name,
            record.section_name,
            record.object_type,
            record.name,
            record.description,
            record.chunk_text,
            record.search_text,
        ),
    )


def insert_metadata_attribute(conn: sqlite3.Connection, record: MetadataAttributeRecord) -> None:
    conn.execute(
        """
        INSERT INTO metadata_attributes (
            object_full_name, section_name, container_name, attribute_kind,
            name, value_type, chunk_text, search_text
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.object_full_name,
            record.section_name,
            record.container_name,
            record.attribute_kind,
            record.name,
            record.value_type,
            record.chunk_text,
            record.search_text,
        ),
    )


def insert_type_link(
    conn: sqlite3.Connection,
    object_full_name: str,
    section_name: str,
    container_name: str,
    attribute_kind: str,
    attribute_name: str,
    referenced_type: str,
) -> None:
    conn.execute(
        """
        INSERT INTO type_links (
            object_full_name, section_name, container_name, attribute_kind,
            attribute_name, referenced_type, search_text
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            object_full_name,
            section_name,
            container_name,
            attribute_kind,
            attribute_name,
            referenced_type,
            object_search_text(
                object_full_name,
                section_name,
                container_name,
                attribute_kind,
                attribute_name,
                referenced_type,
            ),
        ),
    )


def insert_chunk(
    conn: sqlite3.Connection,
    chunk_type: str,
    chunk_key: str,
    title: str,
    content: str,
    section_name: str,
    object_full_name: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO chunks (
            chunk_type, chunk_key, title, content, section_name, object_full_name, search_text
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            chunk_type,
            chunk_key,
            title,
            content,
            section_name,
            object_full_name,
            object_search_text(chunk_type, chunk_key, title, content, section_name, object_full_name),
        ),
    )


@dataclass(slots=True)
class ModuleRecord:
    path: str
    module_type: str | None
    owner_full_name: str | None
    content: str
    search_text: str


@dataclass(slots=True)
class ProcedureRecord:
    module_path: str
    proc_name: str
    kind: str
    line_start: int
    line_end: int
    signature: str
    search_text: str


def insert_module(conn: sqlite3.Connection, record: ModuleRecord) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO modules (path, module_type, owner_full_name, content, search_text)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            record.path,
            record.module_type,
            record.owner_full_name,
            record.content,
            record.search_text,
        ),
    )


def insert_procedure(conn: sqlite3.Connection, record: ProcedureRecord) -> None:
    conn.execute(
        """
        INSERT INTO procedures (
            module_path, proc_name, kind, line_start, line_end, signature, search_text
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.module_path,
            record.proc_name,
            record.kind,
            record.line_start,
            record.line_end,
            record.signature,
            record.search_text,
        ),
    )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_metadata_objects(conn: sqlite3.Connection, query: str, limit: int = 20) -> list[sqlite3.Row]:
    pattern = f"%{_escape_like(_casefold(query))}%"
    return conn.execute(
        """
        SELECT full_name, section_name, object_type, name, description, chunk_text
        FROM metadata_objects
        WHERE search_text LIKE ? ESCAPE '\\'
        ORDER BY section_name, name
        LIMIT ?
        """,
        (pattern, limit),
    ).fetchall()


def search_docs(conn: sqlite3.Connection, query: str, limit: int = 20) -> list[sqlite3.Row]:
    pattern = f"%{_escape_like(_casefold(query))}%"
    return conn.execute(
        """
        SELECT path, title, source_type, content
        FROM docs
        WHERE search_text LIKE ? ESCAPE '\\'
        ORDER BY title, path
        LIMIT ?
        """,
        (pattern, limit),
    ).fetchall()


def search_attributes(conn: sqlite3.Connection, query: str, limit: int = 20) -> list[sqlite3.Row]:
    pattern = f"%{_escape_like(_casefold(query))}%"
    return conn.execute(
        """
        SELECT object_full_name, section_name, container_name, attribute_kind, name, value_type, chunk_text
        FROM metadata_attributes
        WHERE search_text LIKE ? ESCAPE '\\'
        ORDER BY section_name, object_full_name, name
        LIMIT ?
        """,
        (pattern, limit),
    ).fetchall()


def search_type_links(conn: sqlite3.Connection, query: str, limit: int = 20) -> list[sqlite3.Row]:
    pattern = f"%{_escape_like(_casefold(query))}%"
    return conn.execute(
        """
        SELECT object_full_name, section_name, container_name, attribute_kind, attribute_name, referenced_type
        FROM type_links
        WHERE search_text LIKE ? ESCAPE '\\'
        ORDER BY referenced_type, object_full_name
        LIMIT ?
        """,
        (pattern, limit),
    ).fetchall()


def search_chunks(conn: sqlite3.Connection, query: str, limit: int = 10) -> list[sqlite3.Row]:
    pattern = f"%{_escape_like(_casefold(query))}%"
    return conn.execute(
        """
        SELECT chunk_type, chunk_key, title, content, section_name, object_full_name
        FROM chunks
        WHERE search_text LIKE ? ESCAPE '\\'
        ORDER BY chunk_type, title
        LIMIT ?
        """,
        (pattern, limit),
    ).fetchall()


def search_modules(conn: sqlite3.Connection, query: str, limit: int = 20) -> list[sqlite3.Row]:
    pattern = f"%{_escape_like(_casefold(query))}%"
    return conn.execute(
        """
        SELECT path, module_type, owner_full_name, content
        FROM modules
        WHERE search_text LIKE ? ESCAPE '\\'
        ORDER BY path
        LIMIT ?
        """,
        (pattern, limit),
    ).fetchall()


def search_procedures(conn: sqlite3.Connection, query: str, limit: int = 20) -> list[sqlite3.Row]:
    pattern = f"%{_escape_like(_casefold(query))}%"
    return conn.execute(
        """
        SELECT module_path, proc_name, kind, line_start, line_end, signature
        FROM procedures
        WHERE search_text LIKE ? ESCAPE '\\'
        ORDER BY proc_name
        LIMIT ?
        """,
        (pattern, limit),
    ).fetchall()


def list_sections(conn: sqlite3.Connection, limit: int = 100) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT name, object_count, chunk_text
        FROM sections
        ORDER BY name
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def get_object_details(conn: sqlite3.Connection, full_name: str) -> tuple[sqlite3.Row | None, list[sqlite3.Row], list[sqlite3.Row]]:
    object_row = conn.execute(
        """
        SELECT full_name, section_name, object_type, name, description, chunk_text
        FROM metadata_objects
        WHERE full_name = ?
        """,
        (full_name,),
    ).fetchone()
    attributes = conn.execute(
        """
        SELECT object_full_name, section_name, container_name, attribute_kind, name, value_type, chunk_text
        FROM metadata_attributes
        WHERE object_full_name = ?
        ORDER BY container_name, name
        """,
        (full_name,),
    ).fetchall()
    links = conn.execute(
        """
        SELECT object_full_name, section_name, container_name, attribute_kind, attribute_name, referenced_type
        FROM type_links
        WHERE object_full_name = ?
        ORDER BY referenced_type, attribute_name
        """,
        (full_name,),
    ).fetchall()
    return object_row, attributes, links


def format_metadata_object(row: sqlite3.Row, attributes: list[sqlite3.Row], links: list[sqlite3.Row]) -> str:
    lines = [
        f"Раздел: {row['section_name']}",
        f"Полное имя: {row['full_name']}",
        f"Имя: {row['name']}",
        f"Тип: {row['object_type']}",
    ]
    if row["description"]:
        lines.append(f"Описание: {row['description']}")

    grouped: dict[str, list[sqlite3.Row]] = {}
    for attr in attributes:
        grouped.setdefault(attr["container_name"], []).append(attr)

    for container_name, rows in grouped.items():
        if container_name == "Attributes":
            lines.append("Реквизиты:")
        elif container_name == "StandardAttributes":
            lines.append("Стандартные реквизиты:")
        else:
            lines.append(f"{container_name}:")
        for attr in rows:
            if attr["value_type"]:
                lines.append(f"- {attr['name']}: {attr['value_type']}")
            else:
                lines.append(f"- {attr['name']}")

    if links:
        lines.append("Связанные типы:")
        for link in links:
            lines.append(
                f"- {link['attribute_name']} -> {link['referenced_type']} "
                f"({link['container_name']}, {link['attribute_kind']})"
            )

    return "\n".join(lines)


def format_rows(rows: Iterable[sqlite3.Row], columns: Iterable[str]) -> str:
    columns = list(columns)
    output = []
    for row in rows:
        output.append(" | ".join(f"{column}={row[column]}" for column in columns))
    return "\n".join(output) if output else "Ничего не найдено"
