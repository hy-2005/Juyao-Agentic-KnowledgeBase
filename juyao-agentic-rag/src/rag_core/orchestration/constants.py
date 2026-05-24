"""对话编排常量：免责声明与图谱展示限制。"""

DISCLAIMER = "提示：本回答仅基于当前知识库检索结果生成，请结合权威来源进行核验。"

DISCLAIMER_NO_KB_REFERENCES = (
    "提示：知识库未提供可引用的检索片段，上述内容为模型通用知识生成，"
    "请务必向权威或官方渠道核实。"
)

NO_KB_STREAM_PREFIX = (
    "【说明】知识库未检索到可供引用的参考资料，以下为模型基于通用知识的说明，"
    "请勿当作内部权威依据。\n\n"
)

GRAPH_LOG_SLICE_LEN = 8000
GRAPH_FOOTER_PER_QUERY_MAX = 14000
GRAPH_FOOTER_TOTAL_MAX = 48000
