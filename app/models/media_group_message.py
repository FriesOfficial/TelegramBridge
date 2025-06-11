from sqlalchemy import Column, Integer, String, Boolean, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database.database import Base

class MediaGroupMessage(Base):
    __tablename__ = "media_group_messages"

    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(Integer, index=True)  # 消息所在的聊天ID
    message_id = Column(Integer, index=True)  # 消息ID
    media_group_id = Column(String, index=True)  # 媒体组ID
    is_header = Column(Boolean, default=False)  # 是否是媒体组的第一条消息
    caption = Column(Text, nullable=True)  # 媒体组的标题
    created_at = Column(DateTime(timezone=True), server_default=func.now()) 