package com.juyao.system.service.impl;

import java.util.List;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import com.juyao.common.exception.ServiceException;
import com.juyao.system.domain.RagKb;
import com.juyao.system.mapper.RagKbMapper;
import com.juyao.system.service.IRagKbService;

/**
 * 知识库权限服务实现（TENANT_PERMISSION P1-2）。
 */
@Service
public class RagKbServiceImpl implements IRagKbService{

    @Autowired
    private RagKbMapper ragKbMapper;

    @Override
    public void checkAccess(Long kbId, Long userId){
        if (kbId == null || userId == null){
            throw new ServiceException("知识库或用户参数缺失");
        }
        if (ragKbMapper.countById(kbId) == 0){
            throw new ServiceException("知识库不存在: " + kbId);
        }
        String role = ragKbMapper.selectUserAccess(kbId, userId);
        if (role == null){
            throw new ServiceException("无权访问该知识库: " + kbId);
        }
    }

    @Override
    public List<RagKb> listAccessibleKbs(Long userId){
        return ragKbMapper.selectAccessibleKbs(userId);
    }
}
