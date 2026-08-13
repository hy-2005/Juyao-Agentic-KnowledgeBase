package com.juyao.system.mapper;

import java.util.List;

import org.apache.ibatis.annotations.Param;
import com.juyao.system.domain.RagDocumentHash;

/**
 * RAG 文档 Hash 表数据层
 */
public interface RagDocumentHashMapper{
    RagDocumentHash selectByKbAndKey(@Param("kbId") Long kbId, @Param("docLogicalKey") String docLogicalKey);

    List<RagDocumentHash> selectRagDocumentHashList(RagDocumentHash query);

    int mergeRagDocumentHash(RagDocumentHash row);

    int deleteByKbAndKey(@Param("kbId") Long kbId, @Param("docLogicalKey") String docLogicalKey);

    /** 删除某知识库的全部文档登记（删知识库的级联清理）。 */
    int deleteByKb(@Param("kbId") Long kbId);
}
