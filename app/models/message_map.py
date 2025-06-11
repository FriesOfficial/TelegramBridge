from sqlalchemy import Column, Integer, String, DateTime, Boolean
from sqlalchemy.sql import func
from app.database.database import Base

class MessageMap(Base):
    __tablename__ = "message_map"

    id = Column(Integer, primary_key=True, index=True)
    user_chat_message_id = Column(Integer, index=True)  # 用户聊天中的消息ID
    group_chat_message_id = Column(Integer, index=True)  # 群组聊天中的消息ID
    user_telegram_id = Column(Integer, index=True)  # 用户的Telegram ID
    is_unread_topic = Column(Boolean, default=False)  # 是否是未读消息话题
    unread_topic_message_id = Column(Integer, nullable=True)  # 未读话题中的消息ID
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    handled_by_user_id = Column(Integer, nullable=True)  # 处理人的Telegram ID
    handled_time = Column(DateTime(timezone=True), nullable=True)  # 处理时间 