package com.juyao.web.controller.rag;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.juyao.common.core.controller.BaseController;
import com.juyao.common.core.domain.AjaxResult;
import com.juyao.rag.RagChatClient;
import com.juyao.system.domain.RagKb;
import com.juyao.system.service.IRagDocumentHashService;
import com.juyao.system.service.IRagKbService;

/**
 * 知识库管理接口（TENANT_PERMISSION P2）：创建 / 列表 / 授权 / 删除。
 * 删除知识库时级联调 Python 清空该 kb 的三库数据。
 */
@RestController
@RequestMapping("/rag/kbs")
public class RagKbController extends BaseController{
    @Autowired
    private IRagKbService ragKbService;

    @Autowired
    private RagChatClient ragChatClient;

    @Autowired
    private IRagDocumentHashService ragDocumentHashService;

    @GetMapping
    public AjaxResult list(){
        List<RagKb> kbs = ragKbService.listAccessibleKbs(getUserId());
        return success(kbs);
    }

    @PostMapping
    public AjaxResult create(@RequestBody CreateKbBody body){
        if (body == null || body.name() == null || body.name().isBlank()){
            return error("知识库名称不能为空");
        }
        Long kbId = ragKbService.createKb(body.name(), getUserId());
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("kbId", kbId);
        return success(data);
    }

    @PostMapping("/{kbId}/users")
    public AjaxResult grant(@PathVariable Long kbId, @RequestBody GrantBody body){
        if (body == null || body.userId() == null){
            return error("被授权用户不能为空");
        }
        ragKbService.grantUser(kbId, body.userId(), body.role(), getUserId());
        return success();
    }

    @DeleteMapping("/{kbId}")
    public AjaxResult delete(@PathVariable Long kbId){
        try{
            // 先清 Python 侧数据（Qdrant/ES/Neo4j/MySQL 切片+图谱快照），失败不阻塞库记录删除（数据残留可重灌）
            ragChatClient.purgeKb(kbId);
        } catch (Exception e){
            logger.warn("清空知识库数据失败（继续删除库记录）: {}", e.getMessage());
        }
        // 文档登记表由 Java 侧维护（监听器幂等登记），删 kb 时一并清掉，否则管理台文档列表留孤儿行
        ragDocumentHashService.deleteByKb(kbId);
        ragKbService.deleteKb(kbId, getUserId());
        return success();
    }

    public record CreateKbBody(String name){
    }

    public record GrantBody(Long userId, String role){
    }
}
