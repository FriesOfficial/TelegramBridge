from pydantic import BaseModel
from typing import Optional
from datetime import datetime

# 用户模式
class UserBase(BaseModel):
    username: Optional[str] = None
    telegram_id: int
    first_name: str
    last_name: Optional[str] = None

class UserCreate(UserBase):
    pass

class User(UserBase):
    id: int
    user_id: int
    is_active: bool
    is_premium: Optional[bool] = False
    message_thread_id: Optional[int] = 0
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# 表单状态模式
class FormnStatusBase(BaseModel):
    user_id: Optional[int] = None
    topic_id: int
    topic_name: str
    status: Optional[str] = "opened"
    is_system_topic: Optional[bool] = False

class FormnStatusCreate(FormnStatusBase):
    pass

class FormnStatus(FormnStatusBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# 消息映射模式
class MessageMapBase(BaseModel):
    user_chat_message_id: int
    group_chat_message_id: int
    user_telegram_id: int
    is_unread_topic: Optional[bool] = False
    unread_topic_message_id: Optional[int] = None

class MessageMapCreate(MessageMapBase):
    pass

class MessageMap(MessageMapBase):
    id: int
    created_at: datetime
    handled_by_user_id: Optional[int] = None
    handled_time: Optional[datetime] = None

    class Config:
        from_attributes = True

# 媒体组消息模式
class MediaGroupMessageBase(BaseModel):
    chat_id: int
    message_id: int
    media_group_id: str
    is_header: Optional[bool] = False
    caption: Optional[str] = None

class MediaGroupMessageCreate(MediaGroupMessageBase):
    pass

class MediaGroupMessage(MediaGroupMessageBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True 