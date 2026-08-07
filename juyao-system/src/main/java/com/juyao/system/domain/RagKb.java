package com.juyao.system.domain;

import java.util.Date;

/**
 * 知识库实体（TENANT_PERMISSION P1-2：kb 级数据权限）。
 * 与 rag_kb 表对应；权限判定见 RagKbMapper.selectUserAccess。
 */
public class RagKb{
    private Long id;
    private String name;
    private Long ownerId;
    private Date createTime;

    public Long getId(){
        return id;
    }

    public void setId(Long id){
        this.id = id;
    }

    public String getName(){
        return name;
    }

    public void setName(String name){
        this.name = name;
    }

    public Long getOwnerId(){
        return ownerId;
    }

    public void setOwnerId(Long ownerId){
        this.ownerId = ownerId;
    }

    public Date getCreateTime(){
        return createTime;
    }

    public void setCreateTime(Date createTime){
        this.createTime = createTime;
    }
}
