"""对话编排共享类型。"""

from dataclasses import dataclass

from langchain_core.documents import Document


@dataclass
class ExecuteResult:
    observation: str
    max_score: float
    documents: dict[str, Document]
    is_empty: bool
