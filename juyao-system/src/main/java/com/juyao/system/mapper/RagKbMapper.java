package com.juyao.system.mapper;

import java.util.List;

import org.apache.ibatis.annotations.Param;

import com.juyao.system.domain.RagKb;

/**
 * 知识库与授权查询（TENANT_PERMISSION P1-2）。
 */
public interface RagKbMapper{

    /**
     * 用户对知识库的访问角色：owner 返回 admin，授权表命中返回其角色，无权限返回 null。
     */
    String selectUserAccess(@Param("kbId") Long kbId, @Param("userId") Long userId);

    /**
     * 知识库是否存在。
     */
    int countById(@Param("kbId") Long kbId);

    /**
     * 用户可访问的知识库列表（owner 或授权命中）。
     */
    List<RagKb> selectAccessibleKbs(@Param("userId") Long userId);
}
