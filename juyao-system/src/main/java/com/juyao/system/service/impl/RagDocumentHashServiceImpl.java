package com.juyao.system.service.impl;

import java.util.List;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import com.juyao.system.domain.RagDocumentHash;
import com.juyao.system.mapper.RagDocumentHashMapper;
import com.juyao.system.service.IRagDocumentHashService;

@Service
public class    RagDocumentHashServiceImpl implements IRagDocumentHashService{
    @Autowired
    private RagDocumentHashMapper ragDocumentHashMapper;

    @Override
    public RagDocumentHash selectByKbAndKey(Long kbId, String docLogicalKey){
        return ragDocumentHashMapper.selectByKbAndKey(kbId, docLogicalKey);
    }

    @Override
    public List<RagDocumentHash> selectRagDocumentHashList(RagDocumentHash query){
        return ragDocumentHashMapper.selectRagDocumentHashList(query);
    }

    @Override
    public int mergeHash(Long kbId, String docLogicalKey, String contentSha256, String fileExt, Long fileSizeBytes){
        RagDocumentHash row = new RagDocumentHash();
        row.setKbId(kbId);
        row.setDocLogicalKey(docLogicalKey);
        row.setContentSha256(contentSha256);
        row.setFileExt(fileExt);
        row.setFileSizeBytes(fileSizeBytes);
        return ragDocumentHashMapper.mergeRagDocumentHash(row);
    }

    @Override
    public int deleteByKbAndKey(Long kbId, String docLogicalKey){
        return ragDocumentHashMapper.deleteByKbAndKey(kbId, docLogicalKey);
    }
}
