from __future__ import annotations

import json
import sys
from typing import Any, Callable
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from paths import DB_PATH
from storage import (
    search_docs,
    ensure_schema,
    format_metadata_object,
    format_rows,
    get_object_details,
    open_db,
    list_sections,
    search_attributes,
    search_chunks,
    search_metadata_objects,
    search_modules,
    search_procedures,
    search_type_links,
)


SERVER_INFO = {"name": "1C", "version": "0.1.0"}
PROTOCOL_VERSION = "2025-06-18"

conn = open_db(DB_PATH)
ensure_schema(conn)


def search_structure(query: str, limit: int = 20) -> str:
    rows = search_metadata_objects(conn, query, limit=limit)
    if not rows:
        return "Ничего не найдено"
    return format_rows(rows, ["full_name", "section_name", "object_type", "name"])


def search_docs_tool(query: str, limit: int = 20) -> str:
    rows = search_docs(conn, query, limit=limit)
    if not rows:
        return "Ничего не найдено"
    result = []
    for row in rows:
        content = row["content"]
        if len(content) > 2500:
            content = content[:2500] + "..."
        result.append(
            "\n".join(
                [
                    f"Path: {row['path']}",
                    f"Title: {row['title']}",
                    f"Source: {row['source_type']}",
                    content,
                ]
            )
        )
    return "\n\n=================\n\n".join(result)


def get_structure_object(full_name: str) -> str:
    row, attributes, links = get_object_details(conn, full_name)
    if row is None:
        return "Ничего не найдено"
    return format_metadata_object(row, attributes, links)


def search_attributes_tool(query: str, limit: int = 20) -> str:
    rows = search_attributes(conn, query, limit=limit)
    if not rows:
        return "Ничего не найдено"
    return format_rows(rows, ["object_full_name", "section_name", "container_name", "name", "value_type"])


def search_types_tool(query: str, limit: int = 20) -> str:
    rows = search_type_links(conn, query, limit=limit)
    if not rows:
        return "Ничего не найдено"
    return format_rows(rows, ["object_full_name", "section_name", "attribute_name", "referenced_type"])


def search_chunks_tool(query: str, limit: int = 10) -> str:
    rows = search_chunks(conn, query, limit=limit)
    if not rows:
        return "Ничего не найдено"
    result = []
    for row in rows:
        snippet = row["content"]
        if len(snippet) > 2500:
            snippet = snippet[:2500] + "..."
        result.append(
            "\n".join(
                [
                    f"Тип: {row['chunk_type']}",
                    f"Ключ: {row['chunk_key']}",
                    f"Заголовок: {row['title']}",
                    f"Раздел: {row['section_name']}",
                    snippet,
                ]
            )
        )
    return "\n\n=================\n\n".join(result)


def list_sections_tool(limit: int = 50) -> str:
    rows = list_sections(conn, limit=limit)
    if not rows:
        return "Ничего не найдено"
    return format_rows(rows, ["name", "object_count"])


def search_procedure(name: str, limit: int = 20) -> str:
    rows = search_procedures(conn, name, limit=limit)
    if not rows:
        return "Процедуры пока не проиндексированы"
    return format_rows(rows, ["module_path", "proc_name", "kind", "signature"])


def search_code(text: str, limit: int = 10) -> str:
    module_rows = search_modules(conn, text, limit=limit)
    chunk_rows = search_chunks(conn, text, limit=limit)
    parts = []
    if module_rows:
        parts.append("MODULES\n" + format_rows(module_rows, ["path", "module_type", "owner_full_name"]))
    if chunk_rows:
        parts.append(search_chunks_tool(text, limit=limit))
    return "\n\n=================\n\n".join(parts) if parts else "Ничего не найдено"


def get_module_source(path: str, max_chars: int = 12000) -> str:
    row = conn.execute(
        """
        SELECT path, module_type, owner_full_name, content
        FROM modules
        WHERE path = ?
        """,
        (path,),
    ).fetchone()
    if row is None:
        return "Ничего не найдено"
    content = row["content"]
    if len(content) > max_chars:
        content = content[:max_chars] + "..."
    return "\n".join(
        [
            f"Path: {row['path']}",
            f"Module type: {row['module_type']}",
            f"Owner: {row['owner_full_name']}",
            content,
        ]
    )


TOOLS: dict[str, tuple[Callable[..., str], dict[str, Any], str]] = {
    "search_structure": (
        search_structure,
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "Search 1C metadata structure by name or text.",
    ),
    "search_docs": (
        search_docs_tool,
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "Search indexed 1C documentation and reference material.",
    ),
    "get_structure_object": (
        get_structure_object,
        {
            "type": "object",
            "properties": {"full_name": {"type": "string"}},
            "required": ["full_name"],
            "additionalProperties": False,
        },
        "Get a full 1C metadata object description.",
    ),
    "search_attributes_tool": (
        search_attributes_tool,
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "Search metadata attributes and tabular section fields.",
    ),
    "search_types_tool": (
        search_types_tool,
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "Search reference and type links inside metadata.",
    ),
    "search_chunks_tool": (
        search_chunks_tool,
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "Search RAG chunks over metadata and code.",
    ),
    "list_sections_tool": (
        list_sections_tool,
        {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 50}},
            "additionalProperties": False,
        },
        "List top-level XML sections from the structure export.",
    ),
    "search_procedure": (
        search_procedure,
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
        "Search indexed 1C procedures and functions.",
    ),
    "search_code": (
        search_code,
        {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["text"],
            "additionalProperties": False,
        },
        "Search module text and code chunks.",
    ),
    "get_module_source": (
        get_module_source,
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_chars": {"type": "integer", "default": 12000},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        "Return full module text by indexed path.",
    ),
}


def _content_text(text: str) -> dict[str, str]:
    return {"type": "text", "text": text}


def _jsonrpc_result(message_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _jsonrpc_error(message_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def _call_tool(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    tool = TOOLS.get(name)
    if tool is None:
        raise KeyError(name)
    fn, _, _ = tool
    arguments = arguments or {}
    try:
        result = fn(**arguments)
        return {"content": [_content_text(result)]}
    except Exception as exc:
        return {"isError": True, "content": [_content_text(f"{type(exc).__name__}: {exc}")]}


def _list_tools() -> dict[str, Any]:
    return {
        "tools": [
            {
                "name": name,
                "description": description,
                "inputSchema": schema,
            }
            for name, (_, schema, description) in TOOLS.items()
        ]
    }


def handle_message(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    message_id = message.get("id")

    if method is None:
        return None

    if method == "initialize":
        return _jsonrpc_result(
            message_id,
            {
                "protocolVersion": message.get("params", {}).get("protocolVersion", PROTOCOL_VERSION),
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            },
        )

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return _jsonrpc_result(message_id, _list_tools())

    if method == "tools/call":
        params = message.get("params") or {}
        tool_name = params.get("name")
        if not isinstance(tool_name, str):
            return _jsonrpc_error(message_id, -32602, "Invalid tools/call request")
        return _jsonrpc_result(message_id, _call_tool(tool_name, params.get("arguments")))

    if method == "ping":
        return _jsonrpc_result(message_id, {})

    return _jsonrpc_error(message_id, -32601, f"Method not found: {method}")


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            response = _jsonrpc_error(None, -32700, f"Parse error: {exc.msg}")
            print(json.dumps(response, ensure_ascii=False), flush=True)
            continue

        response = handle_message(message)
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
