package com.juyao.system.domain;

import java.io.Serial;

import com.juyao.common.annotation.Excel;
import com.juyao.common.annotation.Excel.ColumnType;
import com.juyao.common.core.domain.BaseEntity;

/**
 * RAG 文档注册行（表 rag_document_hash）：幂等 Hash + 管理台列表字段。
 */
public class RagDocumentHash extends BaseEntity{
    @Serial
    private static final long serialVersionUID = 1L;

    @Excel(name = "编号", cellType = ColumnType.NUMERIC)
    private Long id;

    @Excel(name = "知识库ID", cellType = ColumnType.NUMERIC)
    private Long kbId;

    @Excel(name = "逻辑文件名")
    private String docLogicalKey;

    @Excel(name = "类型")
    private String fileExt;

    @Excel(name = "大小(字节)", cellType = ColumnType.NUMERIC)
    private Long fileSizeBytes;

    @Excel(name = "内容SHA256")
    private String contentSha256;

    public Long getId(){
        return id;
    }

    public void setId(Long id){
        this.id = id;
    }

    public Long getKbId(){
        return kbId;
    }

    public void setKbId(Long kbId){
        this.kbId = kbId;
    }

    public String getDocLogicalKey(){
        return docLogicalKey;
    }

    public void setDocLogicalKey(String docLogicalKey){
        this.docLogicalKey = docLogicalKey;
    }

    public String getFileExt(){
        return fileExt;
    }

    public void setFileExt(String fileExt){
        this.fileExt = fileExt;
    }

    public Long getFileSizeBytes(){
        return fileSizeBytes;
    }

    public void setFileSizeBytes(Long fileSizeBytes){
        this.fileSizeBytes = fileSizeBytes;
    }

    public String getContentSha256(){
        return contentSha256;
    }

    public void setContentSha256(String contentSha256){
        this.contentSha256 = contentSha256;
    }
}
