package com.juyao.web.controller.rag;

import java.util.Map;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import com.juyao.common.core.controller.BaseController;
import com.juyao.common.core.domain.AjaxResult;
import com.juyao.common.core.page.TableDataInfo;
import com.juyao.rag.RagAdminClient;

/**
 * RAG 切片只读管理：转发至 Python FastAPI /api/v1/admin/chunks。
 */
@RestController
@RequestMapping("/rag/chunks")
public class RagChunkController extends BaseController{
    @Autowired
    private RagAdminClient ragAdminClient;

    @GetMapping("/list")
    public TableDataInfo list(
            @RequestParam(value = "sourceName", required = false) String sourceName,
            @RequestParam(value = "keyword", required = false) String keyword,
            @RequestParam(value = "pageNum", defaultValue = "1") Integer pageNum,
            @RequestParam(value = "pageSize", defaultValue = "20") Integer pageSize){
        try{
            return ragAdminClient.getTable(
                    "/api/v1/admin/chunks",
                    RagAdminClient.params(
                            "sourceName", sourceName,
                            "keyword", keyword, 
                            "pageNum", String.valueOf(pageNum),
                            "pageSize", String.valueOf(pageSize)));
        } catch (Exception e){
            TableDataInfo empty = new TableDataInfo();
            empty.setCode(500);
            empty.setMsg("查询切片失败: " + e.getMessage());
            return empty;
        }
    }

    @GetMapping("/stats")
    public AjaxResult stats(@RequestParam(value = "sourceName", required = false) String sourceName){
        try{
            Map<String, Object> data = ragAdminClient.getJson(
                    "/api/v1/admin/chunks/stats",
                    RagAdminClient.params("sourceName", sourceName));
            return success(data);
        } catch (Exception e){
            return error("查询切片统计失败: " + e.getMessage());
        }
    }

    @GetMapping("/{chunkId}")
    public AjaxResult detail(@PathVariable String chunkId){
        try{
            Map<String, Object> data = ragAdminClient.getJson(
                    "/api/v1/admin/chunks/" + chunkId,
                    RagAdminClient.params());
            return success(data);
        } catch (Exception e){
            return error("查询切片详情失败: " + e.getMessage());
        }
    }
}
