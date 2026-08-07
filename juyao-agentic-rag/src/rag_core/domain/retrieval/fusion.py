# RRF（Reciprocal Rank Fusion，倒数排名融合）。
#
# 提供两个层次的融合：
# 1) fuse_two_rankings：单 query 内融合两路（向量 / ES）的排名 → 一条 query 的最终顺序；
# 2) fuse_query_rankings：跨多条 query（原 query + sub-queries）的"单 query RRF 结果"再融合一次。
#
# 两层都用同一个公式（不直接比较向量相似度与 BM25 数值，只用名次）：
#     score(d) = Σ_i  1 / (rrf_k + rank_i(d))
# 其中 i 在第 1 层是"检索路"（向量 / ES），在第 2 层是"query 编号"。
# 某 chunk 在某路 / 某 query 没出现 → 该项不贡献。
#
# 设计权衡：跨 query 用 RRF 相加，比"取最小 rank"更能利用多条 query 的信号——
# 多个 sub-query 都命中的 chunk 会自然加分，正是 Multi-Query Retrieval 期望的行为。

from langchain_core.documents import Document


def fuse_two_rankings(
    vector_pairs: list[tuple[Document, float]],
    es_pairs: list[tuple[Document, float]],
    rrf_k: int,
) -> list[tuple[Document, float]]:
    # 单 query 内：向量 + ES 两路融合。
    # 输入：两路 (Document, 原始分) 列表，顺序即名次（第 1 条 rank=1）。
    # 输出：(Document, RRF 分) 按 RRF 分降序。
    doc_by_cid: dict[str, Document] = {}
    vec_rank: dict[str, int] = {}
    es_rank: dict[str, int] = {}

    for rank, (doc, _) in enumerate(vector_pairs, start=1):
        cid = doc.metadata.get("chunk_id")
        if not cid:
            continue
        vec_rank[cid] = rank
        doc_by_cid.setdefault(cid, doc)

    for rank, (doc, _) in enumerate(es_pairs, start=1):
        cid = doc.metadata.get("chunk_id")
        if not cid:
            continue
        es_rank[cid] = rank
        doc_by_cid.setdefault(cid, doc)

    all_cids = set(vec_rank) | set(es_rank)
    if not all_cids:
        return []

    rrf_scores: dict[str, float] = {}
    for cid in all_cids:
        score = 0.0
        if cid in vec_rank:
            score += 1.0 / (rrf_k + vec_rank[cid])
        if cid in es_rank:
            score += 1.0 / (rrf_k + es_rank[cid])
        rrf_scores[cid] = score

    ordered = sorted(rrf_scores.keys(), key=lambda c: rrf_scores[c], reverse=True)
    return [(doc_by_cid[c], rrf_scores[c]) for c in ordered]


def fuse_query_rankings(
    per_query_results: list[list[tuple[Document, float]]],
    rrf_k: int,
) -> list[tuple[Document, float]]:
    # 跨 query 二次融合：把每条 query 已经做过 RRF 的结果再做一次 RRF。
    # 输入：长度为 N 的列表（N = 1 原 query + 若干 sub-query），每个元素是该 query 的有序 (Document, 分) 列表。
    # 输出：(Document, 跨 query RRF 分) 按分降序。
    doc_by_cid: dict[str, Document] = {}
    per_query_ranks: list[dict[str, int]] = []

    for ranking in per_query_results:
        rank_map: dict[str, int] = {}
        for rank, (doc, _) in enumerate(ranking, start=1):
            cid = doc.metadata.get("chunk_id")
            if not cid:
                continue
            rank_map[cid] = rank
            doc_by_cid.setdefault(cid, doc)
        per_query_ranks.append(rank_map)

    all_cids: set[str] = set()
    for rank_map in per_query_ranks:
        all_cids.update(rank_map.keys())
    if not all_cids:
        return []

    cross_scores: dict[str, float] = {}
    for cid in all_cids:
        score = 0.0
        for rank_map in per_query_ranks:
            if cid in rank_map:
                score += 1.0 / (rrf_k + rank_map[cid])
        cross_scores[cid] = score

    ordered = sorted(cross_scores.keys(), key=lambda c: cross_scores[c], reverse=True)
    return [(doc_by_cid[c], cross_scores[c]) for c in ordered]
