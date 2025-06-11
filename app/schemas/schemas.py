from pydantic import BaseModel
from typing import Optional
from datetime import datetime

# 用户模式
class UserBase(BaseModel):
    username: str
    telegram_id: int

class UserCreate(UserBase):
    pass

class User(UserBase):
    id: int
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True

# 消息模式
class MessageBase(BaseModel):
    content: str
    user_id: int

class MessageCreate(MessageBase):
    pass

class Message(MessageBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True 