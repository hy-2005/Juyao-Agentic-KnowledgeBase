package com.juyao.web.controller.rag;

import java.util.List;
import java.util.Map;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import com.juyao.common.annotation.Log;
import com.juyao.common.core.controller.BaseController;
import com.juyao.common.core.domain.AjaxResult;
import com.juyao.common.core.page.TableDataInfo;
import com.juyao.common.enums.BusinessType;
import com.juyao.common.utils.poi.ExcelUtil;
import com.juyao.rag.ingest.RagDocIngestService;
import com.juyao.system.domain.RagDocumentHash;
import com.juyao.system.service.IRagDocumentHashService;

import jakarta.servlet.http.HttpServletResponse;

/**
 * RAG 文档管理：列表/导出/上传/删除；异步入库走 Kafka。
 */
@RestController
@RequestMapping("/rag/documents")
public class RagDocIngestController extends BaseController{
    @Autowired
    private RagDocIngestService ragDocIngestService;

    @Autowired
    private IRagDocumentHashService ragDocumentHashService;

    @GetMapping("/list")
    public TableDataInfo list(RagDocumentHash query){
        startPage();
        List<RagDocumentHash> list = ragDocumentHashService.selectRagDocumentHashList(query);
        return getDataTable(list);
    }

    @Log(title = "RAG文档管理", businessType = BusinessType.EXPORT)
    @PostMapping("/export")
    public void export(HttpServletResponse response, RagDocumentHash query){
        List<RagDocumentHash> list = ragDocumentHashService.selectRagDocumentHashList(query);
        ExcelUtil<RagDocumentHash> util = new ExcelUtil<>(RagDocumentHash.class);
        util.exportExcel(response, list, "RAG文档登记");
    }

    @PostMapping("/upload")
    public AjaxResult upload(
            @RequestParam("file") MultipartFile file,
            @RequestParam(value = "kbId", required = false, defaultValue = "0") Long kbId,
            @RequestParam(value = "logicalKey", required = false) String logicalKey){
        try{
            Map<String, Object> data = ragDocIngestService.upload(file, kbId, logicalKey);
            return success(data);
        } catch (Exception e){
            return error(e.getMessage());
        }
    }

    @DeleteMapping
    public AjaxResult delete(
            @RequestParam(value = "kbId", required = false, defaultValue = "0") Long kbId,
            @RequestParam("logicalKey") String logicalKey){
        try{
            return success(ragDocIngestService.deleteAndNotify(kbId, logicalKey));
        } catch (Exception e){
            return error(e.getMessage());
        }
    }
}
