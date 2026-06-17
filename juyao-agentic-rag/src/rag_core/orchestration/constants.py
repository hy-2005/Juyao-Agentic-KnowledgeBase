"""对话编排常量：免责声明与图谱展示限制。"""

DISCLAIMER = (
    "\n\n---\n\n"
    "> **【重要提示 · 知识库依据】** 本回答主要依据**当前知识库检索结果**生成，"
    "具体条款、数据与结论请以原始文档或权威来源为准。"
)

DISCLAIMER_NO_KB_REFERENCES = (
    "\n\n---\n\n"
    "> **【重要提示 · 通用知识】** 知识库**未提供**可引用的检索片段，"
    "上述内容为模型通用知识生成，请务必向权威或官方渠道核实。"
)

KB_ANSWER_PREFIX = "## 📚 知识库依据回答\n\n"

NO_KB_STREAM_PREFIX = "## 🌐 通用知识说明\n\n"

GRAPH_LOG_SLICE_LEN = 8000
GRAPH_FOOTER_PER_QUERY_MAX = 14000
GRAPH_FOOTER_TOTAL_MAX = 48000
