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

    @Override
    public Long createKb(String name, Long ownerId){
        if (name == null || name.isBlank()){
            throw new ServiceException("知识库名称不能为空");
        }
        RagKb kb = new RagKb();
        kb.setName(name.trim());
        kb.setOwnerId(ownerId);
        ragKbMapper.insertKb(kb);
        return kb.getId();
    }

    @Override
    public void grantUser(Long kbId, Long userId, String role, Long operatorId){
        checkAdmin(kbId, operatorId);
        if (userId == null || userId <= 0L){
            throw new ServiceException("被授权用户无效");
        }
        String r = (role == null || role.isBlank()) ? "member" : role.trim();
        if (!"admin".equals(r) && !"member".equals(r)){
            throw new ServiceException("角色仅支持 admin/member");
        }
        ragKbMapper.insertKbUser(kbId, userId, r);
    }

    @Override
    public void deleteKb(Long kbId, Long operatorId){
        checkOwner(kbId, operatorId);
        ragKbMapper.deleteKbUsers(kbId);
        ragKbMapper.deleteKb(kbId);
    }

    @Override
    public void checkAdmin(Long kbId, Long operatorId){
        checkAccess(kbId, operatorId);
        String role = ragKbMapper.selectUserAccess(kbId, operatorId);
        if (role == null || !"admin".equals(role)){
            throw new ServiceException("需要 admin 角色才能执行该操作");
        }
    }

    /** 校验当前用户为 owner（删除知识库）。 */
    private void checkOwner(Long kbId, Long operatorId){
        if (ragKbMapper.countById(kbId) == 0){
            throw new ServiceException("知识库不存在: " + kbId);
        }
        RagKb kb = null;
        for (RagKb k : ragKbMapper.selectAccessibleKbs(operatorId)){
            if (k.getId().equals(kbId)){
                kb = k;
                break;
            }
        }
        if (kb == null || !kb.getOwnerId().equals(operatorId)){
            throw new ServiceException("仅知识库创建者可删除");
        }
    }
}
