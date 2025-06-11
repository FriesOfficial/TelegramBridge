"""
数据模型初始化文件
"""

from app.models.user import User
from app.models.message_map import MessageMap
from app.models.media_group_message import MediaGroupMessage
from app.models.formn_status import FormnStatus

__all__ = ["User", "MessageMap", "MediaGroupMessage", "FormnStatus"]
