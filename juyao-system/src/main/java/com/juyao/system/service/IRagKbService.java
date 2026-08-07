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
}
