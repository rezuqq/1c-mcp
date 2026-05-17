from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from paths import DB_PATH


TOKEN_RE = re.compile(r"[0-9a-zа-яё]+", re.IGNORECASE)
CAMEL_RE = re.compile(r"(?<=[a-zа-я0-9])(?=[A-ZА-Я])")
STOP_TOKENS = {
    "и",
    "в",
    "во",
    "на",
    "по",
    "с",
    "со",
    "из",
    "за",
    "для",
    "к",
    "ко",
    "о",
    "об",
    "от",
    "до",
    "у",
    "их",
}
STRUCTURE_TERM_ALIASES: dict[str, tuple[str, ...]] = {
    "приход": ("оприход", "поступлен", "приобретен", "закуп"),
    "приходной": ("оприход", "поступлен", "приобретен"),
    "товар": ("номенклатур", "товар", "продукц"),
    "склад": ("склад", "складск", "помещен", "ячейк"),
    "остатки": ("остатк", "запас"),
    "остаток": ("остатк", "запас"),
    "регистр": ("регистр",),
    "накопления": ("накоплен",),
    "движения": ("движен",),
    "документ": ("документ",),
    "справочник": ("справочник",),
}
KIND_PREFIXES: tuple[tuple[str, str], ...] = (
    ("РегистрНакопления", "Регистр накопления"),
    ("РегистрСведений", "Регистр сведений"),
    ("РегистрБухгалтерии", "Регистр бухгалтерии"),
    ("РегистрРасчета", "Регистр расчета"),
    ("Справочник", "Справочник"),
    ("Документ", "Документ"),
    ("Перечисление", "Перечисление"),
    ("ОбщийМодуль", "Общий модуль"),
    ("Обработка", "Обработка"),
    ("Отчет", "Отчет"),
    ("ПланВидовХарактеристик", "План видов характеристик"),
    ("ПланСчетов", "План счетов"),
    ("ПланОбмена", "План обмена"),
    ("БизнесПроцесс", "Бизнес-процесс"),
    ("Задача", "Задача"),
)


def _casefold(value: str | None) -> str:
    return (value or "").casefold().replace("ё", "е")


def _like_pattern(value: str) -> str:
    folded = _casefold(value)
    folded = folded.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{folded}%"


def _search_tokens(value: str) -> list[str]:
    seen: set[str] = set()
    tokens: list[str] = []
    for token in TOKEN_RE.findall(_casefold(value)):
        if len(token) < 2 or token in STOP_TOKENS or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tokens


def _stem_token(token: str) -> str:
    if len(token) >= 10:
        return token[:-3]
    if len(token) >= 7:
        return token[:-2]
    if len(token) >= 5:
        return token[:-1]
    return token


def _expanded_structure_terms(value: str) -> list[str]:
    base_tokens = _search_tokens(value)
    terms: list[str] = []
    seen: set[str] = set()
    for token in base_tokens:
        variants = [token, _stem_token(token), *STRUCTURE_TERM_ALIASES.get(token, ())]
        for variant in variants:
            variant = variant.strip()
            if len(variant) < 2 or variant in seen:
                continue
            seen.add(variant)
            terms.append(variant)
    for left, right in zip(base_tokens, base_tokens[1:]):
        for compound in (
            f"{left}{right}",
            f"{right}{left}",
            f"{_stem_token(left)}{_stem_token(right)}",
            f"{_stem_token(right)}{_stem_token(left)}",
        ):
            if compound not in seen and len(compound) >= 6:
                seen.add(compound)
                terms.append(compound)
    return terms


def _doc_score(query: str, path: str, title: str, source_type: str, content: str) -> int:
    normalized_query = _casefold(query)
    normalized_path = _casefold(path)
    normalized_title = _casefold(title)
    normalized_content = _casefold(content)
    normalized_source = _casefold(source_type)
    normalized_text = " ".join((normalized_path, normalized_title, normalized_source, normalized_content))
    tokens = _search_tokens(query)

    score = 0
    if normalized_query and normalized_query in normalized_title:
        score += 120
    if normalized_query and normalized_query in normalized_path:
        score += 100
    if normalized_query and normalized_query in normalized_text:
        score += 70

    matched_tokens = 0
    for token in tokens:
        token_score = 0
        if token in normalized_title:
            token_score += 30
        if token in normalized_path:
            token_score += 24
        if token in normalized_source:
            token_score += 10
        if token in normalized_content:
            token_score += 8
        if token_score:
            matched_tokens += 1
            score += token_score

    if tokens:
        score += matched_tokens * 12
        if matched_tokens == len(tokens):
            score += 35

    return score


def _metadata_score(
    query: str,
    full_name: str,
    section_name: str,
    object_type: str,
    name: str,
    description: str | None,
    chunk_text: str,
) -> int:
    normalized_query = _casefold(query)
    normalized_full_name = _casefold(full_name)
    normalized_section = _casefold(section_name)
    normalized_type = _casefold(object_type)
    normalized_name = _casefold(name)
    normalized_description = _casefold(description)
    normalized_chunk = _casefold(chunk_text)
    combined = " ".join(
        (
            normalized_full_name,
            normalized_section,
            normalized_type,
            normalized_name,
            normalized_description,
            normalized_chunk,
        )
    )
    terms = _expanded_structure_terms(query)

    score = 0
    if normalized_query and normalized_query in normalized_name:
        score += 120
    if normalized_query and normalized_query in normalized_full_name:
        score += 110
    if normalized_query and normalized_query in combined:
        score += 70

    matched_terms = 0
    for term in terms:
        term_score = 0
        if term in normalized_name:
            term_score += 40
            if len(term) >= 8:
                term_score += 55
        if term in normalized_full_name:
            term_score += 35
            if len(term) >= 8:
                term_score += 45
        if term in normalized_type:
            term_score += 28
        if term in normalized_section:
            term_score += 24
        if term in normalized_description:
            term_score += 14
        if term in normalized_chunk:
            term_score += 3
        if term_score:
            matched_terms += 1
            score += term_score

    if terms:
        score += matched_terms * 14
        if matched_terms == len(terms):
            score += 40

    if "регистрнакопления" in terms and "регистрнакопления" in normalized_name:
        score += 220
    elif "регистрнакоплен" in terms and "регистрнакоплен" in normalized_name:
        score += 160
    if "регистрдвижен" in terms and "регистр" in normalized_name and "движен" in normalized_name:
        score += 120
    if "регистрац" in normalized_name and any(term.startswith("регистр") for term in terms):
        score -= 80

    # Favor less technical object kinds when scores are similar.
    if normalized_name.startswith("документ"):
        score += 25
    elif normalized_name.startswith("регистрнакопления"):
        score += 20
    elif normalized_name.startswith("справочник"):
        score += 18
    elif normalized_section == "catalogobject.значения":
        score -= 10

    return score


def _matches_kind_filter(name: str, kind_filters: tuple[str, ...] | None) -> bool:
    if not kind_filters:
        return True
    inferred_kind, _ = infer_metadata_kind(name)
    return inferred_kind in kind_filters


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
        DROP TABLE IF EXISTS ai_entities;
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


def clear_docs_index(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.executescript(
        """
        DELETE FROM docs;
        """
    )
    conn.commit()


def clear_structure_index(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.executescript(
        """
        DELETE FROM sections;
        DELETE FROM metadata_objects;
        DELETE FROM metadata_attributes;
        DELETE FROM type_links;
        DELETE FROM chunks WHERE chunk_type = 'xml_entry';
        """
    )
    conn.commit()


def clear_code_index(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.executescript(
        """
        DELETE FROM procedures;
        DELETE FROM modules;
        DELETE FROM chunks WHERE chunk_type IN ('module', 'procedure');
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


def humanize_identifier(value: str) -> str:
    normalized = value.replace("_", " ").replace(".", " ").strip()
    normalized = CAMEL_RE.sub(" ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def infer_metadata_kind(name: str, section_name: str | None = None) -> tuple[str, str]:
    for prefix, kind in KIND_PREFIXES:
        if name.startswith(prefix):
            short_name = name[len(prefix) :].strip("._ ")
            humanized_short = humanize_identifier(short_name or name)
            if len(humanized_short) < 2:
                humanized_short = humanize_identifier(name)
            return kind, humanized_short

    normalized_section = _casefold(section_name)
    if normalized_section == "catalogobject.объекты":
        return "Объект конфигурации", humanize_identifier(name)
    if normalized_section == "catalogobject.свойства":
        return "Свойство конфигурации", humanize_identifier(name)
    if normalized_section == "catalogobject.значения":
        return "Значение конфигурации", humanize_identifier(name)
    return "Элемент структуры", humanize_identifier(name)


def _kind_sort_weight(kind: str) -> int:
    order = {
        "Документ": 100,
        "Справочник": 96,
        "Регистр накопления": 94,
        "Регистр сведений": 92,
        "Регистр бухгалтерии": 90,
        "Регистр расчета": 88,
        "Перечисление": 82,
        "Общий модуль": 80,
        "Обработка": 78,
        "Отчет": 76,
        "План видов характеристик": 74,
        "План счетов": 72,
        "План обмена": 70,
        "Бизнес-процесс": 68,
        "Задача": 66,
        "Объект конфигурации": 50,
        "Свойство конфигурации": 45,
        "Значение конфигурации": 40,
        "Элемент структуры": 30,
    }
    return order.get(kind, 0)


def metadata_display_name(row: sqlite3.Row) -> str:
    kind, short_name = infer_metadata_kind(row["name"], row["section_name"])
    return f"{kind}: {short_name}"


def format_structure_rows(rows: Iterable[sqlite3.Row]) -> str:
    output = []
    for row in rows:
        kind, short_name = infer_metadata_kind(row["name"], row["section_name"])
        output.append(
            " | ".join(
                [
                    f"kind={kind}",
                    f"display_name={short_name}",
                    f"name={row['name']}",
                    f"full_name={row['full_name']}",
                    f"section_name={row['section_name']}",
                ]
            )
        )
    return "\n".join(output) if output else "Ничего не найдено"


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


def search_metadata_objects(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 20,
    kind_filters: tuple[str, ...] | None = None,
) -> list[sqlite3.Row]:
    terms = _expanded_structure_terms(query)
    patterns = [_like_pattern(query), *[_like_pattern(term) for term in terms[:10]]]
    where_clauses = " OR ".join(["search_text LIKE ? ESCAPE '\\'"] * len(patterns))
    rows = conn.execute(
        f"""
        SELECT
            full_name,
            section_name,
            object_type,
            name,
            description,
            chunk_text
        FROM metadata_objects
        WHERE {where_clauses}
        LIMIT ?
        """,
        (*patterns, max(limit * 120, 2000)),
    ).fetchall()

    normalized_query = _casefold(query)
    prioritized_rows: list[sqlite3.Row] = []
    if "регистр накопления" in normalized_query or "регистрнакопления" in terms:
        prioritized_rows.extend(
            conn.execute(
                """
                SELECT
                    full_name,
                    section_name,
                    object_type,
                    name,
                    description,
                    chunk_text
                FROM metadata_objects
                WHERE search_text LIKE ? ESCAPE '\\'
                LIMIT ?
                """,
                (_like_pattern("регистрнакопления"), max(limit * 10, 50)),
            ).fetchall()
        )

    scored_rows = [
        (
            _metadata_score(
                query,
                row["full_name"],
                row["section_name"],
                row["object_type"],
                row["name"],
                row["description"],
                row["chunk_text"],
            ),
            row["name"],
            row["full_name"],
            row,
        )
        for row in [*prioritized_rows, *rows]
        if _matches_kind_filter(row["name"], kind_filters)
    ]
    scored_rows = [item for item in scored_rows if item[0] > 0]
    scored_rows.sort(
        key=lambda item: (
            -item[0],
            -_kind_sort_weight(infer_metadata_kind(item[3]["name"], item[3]["section_name"])[0]),
            item[1],
            item[2],
        )
    )
    return [item[3] for item in scored_rows[:limit]]


def search_docs(conn: sqlite3.Connection, query: str, limit: int = 20) -> list[sqlite3.Row]:
    tokens = _search_tokens(query)
    patterns = [_like_pattern(query), *[_like_pattern(token) for token in tokens[:8]]]

    where_clauses = " OR ".join(["search_text LIKE ? ESCAPE '\\'"] * len(patterns))
    rows = conn.execute(
        f"""
        SELECT path, title, source_type, content
        FROM docs
        WHERE {where_clauses}
        LIMIT ?
        """,
        (*patterns, max(limit * 15, 50)),
    ).fetchall()

    if not rows and tokens:
        rows = conn.execute(
            """
            SELECT path, title, source_type, content
            FROM docs
            """
        ).fetchall()

    scored_rows = [
        (
            _doc_score(query, row["path"], row["title"], row["source_type"], row["content"]),
            row["title"],
            row["path"],
            row,
        )
        for row in rows
    ]
    scored_rows = [item for item in scored_rows if item[0] > 0]
    scored_rows.sort(key=lambda item: (-item[0], item[1], item[2]))
    return [item[3] for item in scored_rows[:limit]]


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
        SELECT
            full_name,
            section_name,
            object_type,
            name,
            description,
            chunk_text
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


def resolve_object_by_ref(conn: sqlite3.Connection, ref_value: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT full_name, section_name, object_type, name, description, chunk_text
        FROM metadata_objects
        WHERE full_name = ?
           OR full_name IN (
                SELECT object_full_name
                FROM metadata_attributes
                WHERE name = 'Ref' AND value_type = ?
           )
        LIMIT 1
        """,
        (ref_value, ref_value),
    ).fetchone()


def get_parent_object_details(
    conn: sqlite3.Connection,
    full_name: str,
) -> tuple[sqlite3.Row | None, list[sqlite3.Row], list[sqlite3.Row], str | None]:
    parent_ref_row = conn.execute(
        """
        SELECT value_type
        FROM metadata_attributes
        WHERE object_full_name = ?
          AND name = 'Parent'
          AND value_type IS NOT NULL
          AND value_type <> ''
        LIMIT 1
        """,
        (full_name,),
    ).fetchone()
    if parent_ref_row is None:
        return None, [], [], None

    parent_ref = parent_ref_row["value_type"]
    parent_row = resolve_object_by_ref(conn, parent_ref)
    if parent_row is None:
        return None, [], [], parent_ref

    attributes = conn.execute(
        """
        SELECT object_full_name, section_name, container_name, attribute_kind, name, value_type, chunk_text
        FROM metadata_attributes
        WHERE object_full_name = ?
        ORDER BY container_name, name
        """,
        (parent_row["full_name"],),
    ).fetchall()
    links = conn.execute(
        """
        SELECT object_full_name, section_name, container_name, attribute_kind, attribute_name, referenced_type
        FROM type_links
        WHERE object_full_name = ?
        ORDER BY referenced_type, attribute_name
        """,
        (parent_row["full_name"],),
    ).fetchall()
    return parent_row, attributes, links, parent_ref


def format_metadata_object(row: sqlite3.Row, attributes: list[sqlite3.Row], links: list[sqlite3.Row]) -> str:
    kind, short_name = infer_metadata_kind(row["name"], row["section_name"])
    lines = [
        f"Вид 1С: {kind}",
        f"Краткое имя: {short_name}",
        f"Раздел: {row['section_name']}",
        f"Полное имя: {row['full_name']}",
        f"Имя: {row['name']}",
        f"Тип: {row['object_type']}",
    ]
    if row["description"]:
        lines.append(f"Описание: {row['description']}")

    lines.append(f"Количество реквизитов: {len(attributes)}")
    lines.append(f"Количество связанных типов: {len(links)}")

    grouped: dict[str, list[sqlite3.Row]] = {}
    for attr in attributes:
        grouped.setdefault(attr["container_name"], []).append(attr)

    for container_name, rows in grouped.items():
        if container_name.endswith("Attributes") or container_name == "Attributes":
            lines.append("Реквизиты:")
        elif container_name.endswith("StandardAttributes") or container_name == "StandardAttributes":
            lines.append("Стандартные реквизиты:")
        else:
            lines.append(f"{container_name}:")
        for attr in rows[:30]:
            if attr["value_type"]:
                lines.append(f"- {attr['name']}: {attr['value_type']}")
            else:
                lines.append(f"- {attr['name']}")
        if len(rows) > 30:
            lines.append(f"- ... еще {len(rows) - 30}")

    if links:
        lines.append("Связанные типы:")
        for link in links[:20]:
            lines.append(
                f"- {link['attribute_name']} -> {link['referenced_type']} "
                f"({link['container_name']}, {link['attribute_kind']})"
            )
        if len(links) > 20:
            lines.append(f"- ... еще {len(links) - 20}")

    return "\n".join(lines)


def format_rows(rows: Iterable[sqlite3.Row], columns: Iterable[str]) -> str:
    columns = list(columns)
    output = []
    for row in rows:
        output.append(" | ".join(f"{column}={row[column]}" for column in columns))
    return "\n".join(output) if output else "Ничего не найдено"
