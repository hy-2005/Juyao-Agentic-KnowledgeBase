package com.juyao.web.controller.rag;

import java.util.Map;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import com.juyao.common.annotation.Log;
import com.juyao.common.core.controller.BaseController;
import com.juyao.common.core.domain.AjaxResult;
import com.juyao.common.core.page.TableDataInfo;
import com.juyao.common.enums.BusinessType;
import com.juyao.rag.RagAdminClient;

/**
 * RAG 知识图谱管理：转发至 Python FastAPI /api/v1/admin/graph。
 */
@RestController
@RequestMapping("/rag/graph")
public class RagGraphController extends BaseController{
    @Autowired
    private RagAdminClient ragAdminClient;

    @GetMapping("/stats")
    public AjaxResult stats(@RequestParam(value = "topN", defaultValue = "10") Integer topN){
        try{
            Map<String, Object> data = ragAdminClient.getJson(
                    "/api/v1/admin/graph/stats",
                    RagAdminClient.params("topN", String.valueOf(topN)));
            return success(data);
        } catch (Exception e){
            return error("查询图谱统计失败: " + e.getMessage());
        }
    }

    @GetMapping("/edges")
    public TableDataInfo edges(
            @RequestParam(value = "sourceName", required = false) String sourceName,
            @RequestParam(value = "entity", required = false) String entity,
            @RequestParam(value = "relation", required = false) String relation,
            @RequestParam(value = "pageNum", defaultValue = "1") Integer pageNum,
            @RequestParam(value = "pageSize", defaultValue = "20") Integer pageSize){
        try{
            return ragAdminClient.getTable(
                    "/api/v1/admin/graph/edges",
                    RagAdminClient.params(
                            "sourceName", sourceName,
                            "entity", entity,
                            "relation", relation,
                            "pageNum", String.valueOf(pageNum),
                            "pageSize", String.valueOf(pageSize)));
        } catch (Exception e){
            TableDataInfo empty = new TableDataInfo();
            empty.setCode(500);
            empty.setMsg("查询关系失败: " + e.getMessage());
            return empty;
        }
    }

    @GetMapping("/entities")
    public TableDataInfo entities(
            @RequestParam(value = "keyword", required = false) String keyword,
            @RequestParam(value = "pageNum", defaultValue = "1") Integer pageNum,
            @RequestParam(value = "pageSize", defaultValue = "20") Integer pageSize){
        try{
            return ragAdminClient.getTable(
                    "/api/v1/admin/graph/entities",
                    RagAdminClient.params(
                            "keyword", keyword,
                            "pageNum", String.valueOf(pageNum),
                            "pageSize", String.valueOf(pageSize)));
        } catch (Exception e){
            TableDataInfo empty = new TableDataInfo();
            empty.setCode(500);
            empty.setMsg("查询实体失败: " + e.getMessage());
            return empty;
        }
    }

    @GetMapping("/subgraph")
    public AjaxResult subgraph(
            @RequestParam("seed") String seed,
            @RequestParam(value = "hops", defaultValue = "1") Integer hops,
            @RequestParam(value = "limit", defaultValue = "0") Integer limit){
        try{
            Map<String, Object> data = ragAdminClient.getJson(
                    "/api/v1/admin/graph/subgraph",
                    RagAdminClient.params(
                            "seed", seed,
                            "hops", String.valueOf(hops),
                            "limit", String.valueOf(limit)));
            return success(data);
        } catch (Exception e){
            return error("查询子图失败: " + e.getMessage());
        }
    }

    @GetMapping("/full")
    public AjaxResult fullGraph(@RequestParam(value = "limit", defaultValue = "0") Integer limit){
        try{
            Map<String, Object> data = ragAdminClient.getJson(
                    "/api/v1/admin/graph/full",
                    RagAdminClient.params("limit", String.valueOf(limit)));
            return success(data);
        } catch (Exception e){
            return error("查询全图失败: " + e.getMessage());
        }
    }

    @GetMapping("/edges/all")
    public TableDataInfo allEdges(){
        try{
            return ragAdminClient.getTable("/api/v1/admin/graph/edges/all", RagAdminClient.params());
        } catch (Exception e){
            TableDataInfo empty = new TableDataInfo();
            empty.setCode(500);
            empty.setMsg("查询全部关系失败: " + e.getMessage());
            return empty;
        }
    }

    @Log(title = "知识图谱", businessType = BusinessType.INSERT)
    @PostMapping("/entities")
    public AjaxResult createEntity(@RequestBody Map<String, String> body){
        try{
            Map<String, Object> data = ragAdminClient.postJson("/api/v1/admin/graph/entities", body);
            return success(data);
        } catch (Exception e){
            return error("新增实体失败: " + e.getMessage());
        }
    }

    @Log(title = "知识图谱", businessType = BusinessType.UPDATE)
    @PutMapping("/entities")
    public AjaxResult renameEntity(@RequestBody Map<String, String> body){
        try{
            Map<String, Object> data = ragAdminClient.putJson("/api/v1/admin/graph/entities", body);
            return success(data);
        } catch (Exception e){
            return error("修改实体失败: " + e.getMessage());
        }
    }

    @Log(title = "知识图谱", businessType = BusinessType.DELETE)
    @DeleteMapping("/entities")
    public AjaxResult deleteEntity(@RequestParam("name") String name){
        try{
            Map<String, Object> data = ragAdminClient.deleteJson(
                    "/api/v1/admin/graph/entities",
                    RagAdminClient.params("name", name));
            return success(data);
        } catch (Exception e){
            return error("删除实体失败: " + e.getMessage());
        }
    }

    @Log(title = "知识图谱", businessType = BusinessType.INSERT)
    @PostMapping("/edges")
    public AjaxResult createEdge(@RequestBody Map<String, String> body){
        try{
            Map<String, Object> data = ragAdminClient.postJson("/api/v1/admin/graph/edges", body);
            return success(data);
        } catch (Exception e){
            return error("新增关系失败: " + e.getMessage());
        }
    }

    @Log(title = "知识图谱", businessType = BusinessType.UPDATE)
    @PutMapping("/edges")
    public AjaxResult updateEdge(@RequestBody Map<String, Object> body){
        try{
            Map<String, Object> data = ragAdminClient.putJson("/api/v1/admin/graph/edges", body);
            return success(data);
        } catch (Exception e){
            return error("修改关系失败: " + e.getMessage());
        }
    }

    @Log(title = "知识图谱", businessType = BusinessType.DELETE)
    @DeleteMapping("/edges")
    public AjaxResult deleteEdge(
            @RequestParam("headName") String headName,
            @RequestParam("relationPredicate") String relationPredicate,
            @RequestParam("tailName") String tailName){
        try{
            Map<String, Object> data = ragAdminClient.deleteJson(
                    "/api/v1/admin/graph/edges",
                    RagAdminClient.params(
                            "headName", headName,
                            "relationPredicate", relationPredicate,
                            "tailName", tailName));
            return success(data);
        } catch (Exception e){
            return error("删除关系失败: " + e.getMessage());
        }
    }
}
