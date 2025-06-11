"""
Telegram相关功能模块初始化文件
"""

# 导入子模块
from app.telegram import (
    utils,
    callbacks,
    bot,
    file_handlers
)

# 暴露主要功能
__all__ = ["utils", "callbacks", "bot", "file_handlers"]
