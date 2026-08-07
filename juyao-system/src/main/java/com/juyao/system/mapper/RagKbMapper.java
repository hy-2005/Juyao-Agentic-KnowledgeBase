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

    /**
     * 创建知识库（返回自增 id）。
     */
    int insertKb(RagKb kb);

    /**
     * 授权用户访问知识库。
     */
    int insertKbUser(@Param("kbId") Long kbId, @Param("userId") Long userId, @Param("role") String role);

    /**
     * 删除知识库（连带清授权；数据清理由 Python purge_kb 完成）。
     */
    int deleteKb(@Param("kbId") Long kbId);

    /**
     * 删除知识库的全部授权记录。
     */
    int deleteKbUsers(@Param("kbId") Long kbId);
}
