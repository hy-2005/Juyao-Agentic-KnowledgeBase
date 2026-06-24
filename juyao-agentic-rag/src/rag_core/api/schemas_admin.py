"""管理台只读 API 响应模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChunkListResponse(BaseModel):
    rows: list[dict]
    total: int


class ChunkStatsResponse(BaseModel):
    total: int
    by_source: list[dict] = Field(default_factory=list)


class GraphStatsResponse(BaseModel):
    entity_count: int
    edge_count: int
    top_entities: list[dict] = Field(default_factory=list)


class GraphListResponse(BaseModel):
    rows: list[dict]
    total: int


class GraphSubgraphResponse(BaseModel):
    nodes: list[dict]
    links: list[dict]
    total_edges: int | None = None
    returned_edges: int | None = None
    truncated: bool = False


class EntityCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=500)


class EntityRenameRequest(BaseModel):
    old_name: str = Field(..., min_length=1, max_length=500)
    new_name: str = Field(..., min_length=1, max_length=500)


class EdgeCreateRequest(BaseModel):
    head_name: str = Field(..., min_length=1, max_length=500)
    relation_predicate: str = Field(..., min_length=1, max_length=500)
    tail_name: str = Field(..., min_length=1, max_length=500)
    evidence: str = ""


class EdgeUpdateRequest(BaseModel):
    head_name: str = Field(..., min_length=1, max_length=500)
    relation_predicate: str = Field(..., min_length=1, max_length=500)
    tail_name: str = Field(..., min_length=1, max_length=500)
    new_head_name: str | None = Field(None, max_length=500)
    new_relation_predicate: str | None = Field(None, max_length=500)
    new_tail_name: str | None = Field(None, max_length=500)
    evidence: str | None = None
