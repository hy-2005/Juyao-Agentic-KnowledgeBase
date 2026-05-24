"""图谱边视图模型与 Neo4j 行解析。"""

from __future__ import annotations

from dataclasses import dataclass


def tuple_strs(raw: object) -> tuple[str, ...]:
    if isinstance(raw, str):
        return (raw,) if raw else ()
    if raw is None:
        return ()
    try:
        return tuple(str(x).strip() for x in raw if str(x).strip())
    except TypeError:
        return ()


@dataclass(frozen=True)
class GraphEdgeView:
    head_name: str
    relation_predicate: str
    tail_name: str
    chunk_ids: tuple[str, ...]
    time_hints: tuple[str, ...] = ()
    location_hints: tuple[str, ...] = ()
    evidence_snippets: tuple[str, ...] = ()
    head_kinds: tuple[str, ...] = ()
    tail_kinds: tuple[str, ...] = ()
    head_sense_hints: tuple[str, ...] = ()
    tail_sense_hints: tuple[str, ...] = ()
    relation_category_hints: tuple[str, ...] = ()
    relation_full_hints: tuple[str, ...] = ()
    modality_hints: tuple[str, ...] = ()


def rows_to_views(rows: list[dict]) -> list[GraphEdgeView]:
    out: list[GraphEdgeView] = []
    for row in rows:
        head = str(row.get("head_name") or row.get("head") or "").strip()
        rel = str(row.get("relation_predicate") or row.get("relation") or "").strip()
        tail = str(row.get("tail_name") or row.get("tail") or "").strip()
        if not (head and rel and tail):
            continue
        out.append(
            GraphEdgeView(
                head_name=head,
                relation_predicate=rel,
                tail_name=tail,
                chunk_ids=tuple_strs(row.get("chunk_ids")),
                time_hints=tuple_strs(row.get("time_hints")),
                location_hints=tuple_strs(row.get("location_hints")),
                evidence_snippets=tuple_strs(row.get("evidence_snippets")),
                head_kinds=tuple_strs(row.get("head_kind_hints")),
                tail_kinds=tuple_strs(row.get("tail_kind_hints")),
                head_sense_hints=tuple_strs(row.get("head_sense_hints")),
                tail_sense_hints=tuple_strs(row.get("tail_sense_hints")),
                relation_category_hints=tuple_strs(row.get("relation_category_hints")),
                relation_full_hints=tuple_strs(row.get("relation_full_hints")),
                modality_hints=tuple_strs(row.get("modality_hints")),
            )
        )
    return out
