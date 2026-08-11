# LangGraph Human-in-the-Loop Demo

## 推荐：带 AI 的交互版

AI 根据你的指令**起草邮件**，图在发送前**暂停等你审核**——这才是 Human-in-the-Loop 的感觉。

```bash
cd juyao-agentic-rag
pip install -r demos/langgraph_hitl/requirements.txt
```

在项目根 `.env` 配置 **DeepSeek**（推荐）：

```env
DEEPSEEK_API_KEY=sk-你的key
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat
```

也支持通用写法（base_url 指向 deepseek 时自动识别）：

```env
LLM_API_KEY=sk-你的key
DASHSCOPE_COMPATIBLE_BASE_URL=https://api.deepseek.com/v1
GEN_MODEL=deepseek-chat
```

然后运行：

```bash
python demos/langgraph_hitl/run_ai_hitl.py
```

### 你会体验到

1. 输入任务（如「给客户发延期说明邮件」）
2. **AI 调用 LLM 生成邮件草稿**
3. 图在 `interrupt()` 处**自动暂停** —— 邮件不会发出
4. 你输入：
   - `y` → 批准，AI 确认「已发送」（demo 不真发）
   - `n` → 拒绝，流程结束
   - `edit:语气再正式一点` → AI **重写草稿**，再次暂停等你审
5. 循环直到你批准或拒绝

### 流程图

```
用户任务 → [AI 起草] → [人工审核 interrupt] ──y──→ [发送]
                              │ n
                              └──→ [取消]
                              │ edit:...
                              └──→ [AI 重写] → [人工审核] ...
```

---

## 纯规则版（无 AI，不需 Key）

```bash
python demos/langgraph_hitl/run_interactive.py
```

订外卖 mock，感受 interrupt 暂停/恢复机制。

---

## 其他脚本（自动模拟，非交互）

```bash
python demos/langgraph_hitl/01_basic_approve_reject.py
```
