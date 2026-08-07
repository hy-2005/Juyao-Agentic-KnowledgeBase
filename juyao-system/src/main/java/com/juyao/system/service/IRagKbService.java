package com.juyao.system.service;

import java.util.List;

import com.juyao.system.domain.RagKb;

/**
 * 知识库权限服务（TENANT_PERMISSION P1-2）。
 */
public interface IRagKbService{

    /**
     * 校验用户对知识库的访问权限；无权限抛 ServiceException。
     */
    void checkAccess(Long kbId, Long userId);

    /**
     * 用户可访问的知识库列表（供前端展示）。
     */
    List<RagKb> listAccessibleKbs(Long userId);

    /**
     * 校验用户为 owner 或 admin 角色（管理操作：上传/删除文档、授权）。
     */
    void checkAdmin(Long kbId, Long userId);

    /**
     * 创建知识库（创建人 = owner）。
     */
    Long createKb(String name, Long ownerId);

    /**
     * 授权用户访问知识库（需当前用户为 owner 或 admin 角色）。
     */
    void grantUser(Long kbId, Long userId, String role, Long operatorId);

    /**
     * 删除知识库（需 owner；先调 Python 清空数据，再删授权与 kb）。
     */
    void deleteKb(Long kbId, Long operatorId);
}
