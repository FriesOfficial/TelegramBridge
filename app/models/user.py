from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from app.database.database import Base

class User(Base):
    __tablename__ = "user"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, unique=True, index=True)  # Telegram用户ID
    username = Column(String, nullable=True)
    first_name = Column(String)
    last_name = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    message_thread_id = Column(Integer, default=0)  # 对应在管理群组中的话题ID
    is_premium = Column(Boolean, default=False)  # 是否是高级用户
    last_group_id = Column(Integer, nullable=True)  # 最后一次发送@消息的群组ID
    last_group_name = Column(String, nullable=True)  # 最后一次发送@消息的群组名称
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now()) 