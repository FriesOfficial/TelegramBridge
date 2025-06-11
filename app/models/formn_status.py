from sqlalchemy import Column, Integer, String, DateTime, Boolean
from sqlalchemy.sql import func

from app.database.database import Base

class FormnStatus(Base):
    __tablename__ = "formn_status"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)  # 用户ID，系统话题可以为空
    topic_id = Column(Integer, unique=True, index=True)  # 话题ID
    topic_name = Column(String, index=True)  # 话题名称
    status = Column(String, default="opened")  # 状态：opened, closed
    is_system_topic = Column(Boolean, default=False)  # 是否为系统话题
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now()) 