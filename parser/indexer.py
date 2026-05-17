from __future__ import annotations

import hashlib
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from paths import STRUCTURE_XML_PATH
from storage import (
    MetadataAttributeRecord,
    MetadataObjectRecord,
    SectionRecord,
    clear_structure_index,
    ensure_schema,
    insert_chunk,
    insert_metadata_attribute,
    insert_metadata_object,
    insert_section,
    insert_type_link,
    object_chunk_text,
    object_search_text,
    open_db,
    section_chunk_text,
    split_types,
)


REFERENCE_FIELDS = {
    "Ref",
    "Owner",
    "Parent",
    "Code",
    "Тип",
    "Типы",
    "ТипыСтрокой",
    "Row",
}

NAME_FIELDS = [
    "Имя",
    "Name",
    "Description",
    "Синоним",
    "Комментарий",
    "Code",
    "Ref",
]


def _tag_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _flatten_fields(element: ET.Element, path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], str]]:
    current_path = path + (_tag_name(element),)
    fields: list[tuple[tuple[str, ...], str]] = []

    for attr_name, attr_value in element.attrib.items():
        value = attr_value.strip()
        if value:
            fields.append((current_path + (f"@{attr_name}",), value))

    children = list(element)
    if children:
        for child in children:
            fields.extend(_flatten_fields(child, current_path))
    else:
        value = (element.text or "").strip()
        if value:
            fields.append((current_path, value))

    return fields


def _path_to_text(path: tuple[str, ...]) -> str:
    return "/".join(path)


def _first_value(field_map: dict[str, list[str]], *names: str) -> str | None:
    for name in names:
        values = field_map.get(name)
        if values:
            return values[0]
    return None


def _pick_display_name(field_map: dict[str, list[str]], fallback: str) -> str:
    value = _first_value(field_map, *NAME_FIELDS)
    return value or fallback


def _pick_description(field_map: dict[str, list[str]]) -> str | None:
    return _first_value(field_map, "Description", "Комментарий", "Синоним")


def _pick_key(field_map: dict[str, list[str]], tag: str, display_name: str) -> str:
    value = _first_value(field_map, "Ref", "Code", "Имя", "Name", "Description")
    if value:
        return f"{tag}:{value}"
    digest_source = f"{tag}|{display_name}|{len(field_map)}"
    return f"{tag}:{hashlib.sha1(digest_source.encode('utf-8')).hexdigest()[:12]}"


def _build_records(
    entry: ET.Element,
) -> tuple[SectionRecord, MetadataObjectRecord, list[MetadataAttributeRecord], list[tuple[str, str, str]], list[tuple[str, str]]]:
    tag = _tag_name(entry)
    fields = _flatten_fields(entry)

    field_map: dict[str, list[str]] = {}
    for path, value in fields:
        leaf_name = path[-1].lstrip("@")
        field_map.setdefault(leaf_name, []).append(value)

    display_name = _pick_display_name(field_map, tag)
    description = _pick_description(field_map)
    entry_key = _pick_key(field_map, tag, display_name)

    attributes: list[tuple[str, str | None]] = []
    attribute_records: list[MetadataAttributeRecord] = []
    type_links: list[tuple[str, str, str]] = []
    type_annotations: dict[str, str] = {}

    for path, value in fields:
        path_text = _path_to_text(path)
        container_name = "/".join(path[:-1]) or tag
        leaf_name = path[-1].lstrip("@")
        value_type = value or None
        is_xml_attribute = any(part.startswith("@") for part in path)

        if is_xml_attribute:
            parent_path_text = _path_to_text(path[:-1])
            if "type" in path[-1].lower():
                type_annotations[parent_path_text] = value

        attributes.append((path_text, value_type))
        attribute_records.append(
            MetadataAttributeRecord(
                object_full_name=entry_key,
                section_name=tag,
                container_name=container_name,
                attribute_kind="field",
                name=leaf_name,
                value_type=value_type,
                chunk_text=f"{path_text}: {value}",
                search_text=object_search_text(tag, entry_key, path_text, value),
            )
        )

        should_link = (
            not is_xml_attribute
            and (
            leaf_name in REFERENCE_FIELDS
            or path_text in type_annotations
            or value.startswith("{")
            or value.startswith("CatalogRef.")
            or value.startswith("DocumentRef.")
            or value.startswith("EnumRef.")
            or (leaf_name in {"Тип", "Типы", "ТипыСтрокой"} and "," in value)
            )
        )
        if should_link:
            referenced_source = type_annotations.get(path_text) or value
            for referenced_type in split_types(referenced_source):
                type_links.append((container_name, leaf_name, referenced_type))

    chunk_text = object_chunk_text(
        section_name=tag,
        object_type=tag,
        full_name=entry_key,
        name=display_name,
        description=description,
        attributes=attributes,
        tabular_sections=[],
        standard_attributes=[],
    )
    search_text = object_search_text(tag, entry_key, display_name, description, chunk_text)

    section_record = SectionRecord(
        name=tag,
        object_count=1,
        chunk_text=section_chunk_text(tag, [display_name]),
        search_text=object_search_text(tag, display_name, entry_key),
    )
    object_record = MetadataObjectRecord(
        section_name=tag,
        object_type=tag,
        full_name=entry_key,
        name=display_name,
        description=description,
        chunk_text=chunk_text,
        search_text=search_text,
    )
    return section_record, object_record, attribute_records, type_links, fields


def index_structure(xml_path: Path, reset: bool = True) -> None:
    conn = open_db()
    ensure_schema(conn)
    if reset:
        clear_structure_index(conn)

    section_counts: dict[str, list[str]] = {}
    total_entries = 0
    stack: list[str] = []

    conn.execute("BEGIN")
    try:
        for event, element in ET.iterparse(xml_path, events=("start", "end")):
            tag = _tag_name(element)

            if event == "start":
                stack.append(tag)
                continue

            if len(stack) == 2:
                section_record, object_record, attribute_records, type_links, _ = _build_records(element)

                insert_metadata_object(conn, object_record)
                for attribute_record in attribute_records:
                    insert_metadata_attribute(conn, attribute_record)
                for container_name, attribute_name, referenced_type in type_links:
                    insert_type_link(
                        conn,
                        object_full_name=object_record.full_name,
                        section_name=object_record.section_name,
                        container_name=container_name,
                        attribute_kind="linked_value",
                        attribute_name=attribute_name,
                        referenced_type=referenced_type,
                    )
                insert_chunk(
                    conn,
                    chunk_type="xml_entry",
                    chunk_key=object_record.full_name,
                    title=object_record.name,
                    content=object_record.chunk_text,
                    section_name=object_record.section_name,
                    object_full_name=object_record.full_name,
                )

                section_counts.setdefault(section_record.name, []).append(object_record.name)
                total_entries += 1

                if total_entries % 250 == 0:
                    conn.commit()
                    print("PROCESSED ENTRIES:", total_entries)

                element.clear()

            stack.pop()

        for section_name, object_names in section_counts.items():
            insert_section(
                conn,
                SectionRecord(
                    name=section_name,
                    object_count=len(object_names),
                    chunk_text=section_chunk_text(section_name, object_names),
                    search_text=object_search_text(section_name, " ".join(object_names)),
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> None:
    print("PROCESSING:", STRUCTURE_XML_PATH)
    index_structure(STRUCTURE_XML_PATH, reset=True)

    conn = open_db()
    try:
        counts = {
            "sections": conn.execute("SELECT COUNT(*) FROM sections").fetchone()[0],
            "objects": conn.execute("SELECT COUNT(*) FROM metadata_objects").fetchone()[0],
            "attributes": conn.execute("SELECT COUNT(*) FROM metadata_attributes").fetchone()[0],
            "links": conn.execute("SELECT COUNT(*) FROM type_links").fetchone()[0],
            "chunks": conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
        }
        print()
        for key, value in counts.items():
            print(f"{key.upper()}: {value}")
        print("DONE")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
