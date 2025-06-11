# 集成模块
"""
Telegram Bot 与 FastAPI 集成模块
"""
import os
import asyncio
import threading
from dotenv import load_dotenv

from app.config import telegram_config
from app.telegram.bot import run_bot

# 加载环境变量
load_dotenv()

# 全局变量，跟踪Bot线程
bot_thread = None

def setup_telegram_customer_service():
    """设置Telegram客服系统"""
    global bot_thread
    
    # 检查是否启用Telegram客服功能
    if not telegram_config.enable_customer_service:
        telegram_config.logger.info("Telegram客服功能未启用，跳过初始化")
        return
        
    if not telegram_config.token:
        telegram_config.logger.warning("未设置 TELEGRAM_TOKEN 环境变量，Telegram客服功能将不可用")
        return
        
    if not telegram_config.config_valid:
        telegram_config.logger.error("Telegram客服配置不完整，功能将不可用")
        return
        
    # 确保只有一个Bot线程在运行
    if bot_thread and bot_thread.is_alive():
        telegram_config.logger.warning("Telegram Bot已经在运行，跳过初始化")
        return
        
    telegram_config.logger.info("正在初始化Telegram客服系统...")
    
    # 在单独的线程中启动Bot
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    telegram_config.logger.info("Telegram客服系统初始化完成")

def cleanup_telegram_customer_service():
    """清理Telegram客服系统"""
    global bot_thread
    
    # 检查是否有Bot线程在运行
    if not bot_thread or not bot_thread.is_alive():
        return
    
    telegram_config.logger.info("Telegram Bot线程将在应用退出时自动终止")
    # 由于使用了daemon=True，Bot线程将在主线程退出时自动终止
