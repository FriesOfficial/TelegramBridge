"""
已弃用的模型定义 - 这些模型已被移除，仅保留定义作为参考
请使用新的模型定义，它们位于单独的文件中：
- user.py - 用户模型
- media_group_message.py - 媒体组消息模型
- formn_status.py - 表单状态模型
- message_map.py - 消息映射模型
"""
from sqlalchemy import Boolean, Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func

from app.database.database import Base

# 已弃用 - 请使用 app.models.user.User
class User(Base):
    __tablename__ = "users"  # 此表已被删除

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    telegram_id = Column(Integer, unique=True, index=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# 已弃用 - 没有直接的替代模型
class Message(Base):
    __tablename__ = "messages"  # 此表已被删除

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    content = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now()) 