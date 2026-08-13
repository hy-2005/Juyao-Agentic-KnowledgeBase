package com.juyao.system.service;

import java.util.List;

import com.juyao.system.domain.RagDocumentHash;

public interface IRagDocumentHashService{
    RagDocumentHash selectByKbAndKey(Long kbId, String docLogicalKey);

    List<RagDocumentHash> selectRagDocumentHashList(RagDocumentHash query);

    int mergeHash(Long kbId, String docLogicalKey, String contentSha256, String fileExt, Long fileSizeBytes);

    int deleteByKbAndKey(Long kbId, String docLogicalKey);

    /** 删除某知识库的全部文档登记（删知识库的级联清理）。 */
    int deleteByKb(Long kbId);
}
