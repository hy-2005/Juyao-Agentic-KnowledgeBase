"""FastAPI 请求/响应模型。"""

from pydantic import BaseModel, Field


class ChatStreamRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    session_id: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)


class SessionCreateRequest(BaseModel):
    user_id: str = Field(..., min_length=1)


class SessionTitleUpdate(BaseModel):
    user_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1, max_length=200)
