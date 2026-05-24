package com.juyao.system.service;

import java.util.List;

import com.juyao.system.domain.RagDocumentHash;

public interface IRagDocumentHashService
{
    RagDocumentHash selectByKbAndKey(Long kbId, String docLogicalKey);

    List<RagDocumentHash> selectRagDocumentHashList(RagDocumentHash query);

    int mergeHash(Long kbId, String docLogicalKey, String contentSha256, String fileExt, Long fileSizeBytes);

    int deleteByKbAndKey(Long kbId, String docLogicalKey);
}
