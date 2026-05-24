"""Neo4j 只读图客户端（进程内复用）。"""

from __future__ import annotations

from functools import lru_cache

from langchain_neo4j import Neo4jGraph

from rag_core.core.config import get_settings


@lru_cache(maxsize=1)
def get_read_graph() -> Neo4jGraph:
    settings = get_settings()
    return Neo4jGraph(
        url=settings.neo4j_uri,
        username=settings.neo4j_username,
        password=settings.neo4j_password,
    )


def clear_read_graph_cache() -> None:
    get_read_graph.cache_clear()
