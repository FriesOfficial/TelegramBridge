"""
处理Telegram文件相关的功能
"""
import logging
from typing import Optional

from telegram import Update, Message, Bot
from telegram.ext import ContextTypes

from app.config.telegram_config import telegram_config

# 设置日志
logger = logging.getLogger(__name__)

async def delete_message_later(context: ContextTypes.DEFAULT_TYPE) -> None:
    """延迟删除消息的回调函数"""
    job = context.job
    chat_id, message_id = job.data
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logger.error(f"延迟删除消息时出错: {str(e)}")

async def handle_file_sharing(bot: Bot, chat_id: int, thread_id: int, update: Update) -> Optional[Message]:
    """处理文件分享消息，转发到管理群组"""
    try:
        message = update.message
        
        # 处理不同类型的媒体文件
        if message.photo:
            # 发送最大尺寸的照片
            photo = message.photo[-1]
            return await bot.send_photo(
                chat_id=chat_id,
                message_thread_id=thread_id,
                photo=photo.file_id,
                caption=f"{update.effective_user.first_name} 发送了一张照片: {message.caption or ''}"
            )
            
        elif message.video:
            return await bot.send_video(
                chat_id=chat_id,
                message_thread_id=thread_id,
                video=message.video.file_id,
                caption=f"{update.effective_user.first_name} 发送了一个视频: {message.caption or ''}"
            )
            
        elif message.document:
            return await bot.send_document(
                chat_id=chat_id,
                message_thread_id=thread_id,
                document=message.document.file_id,
                caption=f"{update.effective_user.first_name} 发送了一个文件: {message.caption or ''}"
            )
            
        elif message.voice:
            return await bot.send_voice(
                chat_id=chat_id,
                message_thread_id=thread_id,
                voice=message.voice.file_id,
                caption=f"{update.effective_user.first_name} 发送了一条语音消息"
            )
            
        elif message.audio:
            return await bot.send_audio(
                chat_id=chat_id,
                message_thread_id=thread_id,
                audio=message.audio.file_id,
                caption=f"{update.effective_user.first_name} 发送了一个音频文件: {message.caption or ''}"
            )
            
        else:
            logger.warning(f"未知的媒体类型: {message}")
            return None
            
    except Exception as e:
        logger.error(f"处理文件分享时出错: {str(e)}")
        return None

async def send_media_to_user(bot: Bot, user_id: int, update: Update) -> Optional[Message]:
    """将媒体消息从管理群组转发给用户"""
    try:
        message = update.message
        
        # 处理不同类型的媒体文件
        if message.photo:
            # 发送最大尺寸的照片
            photo = message.photo[-1]
            return await bot.send_photo(
                chat_id=user_id,
                photo=photo.file_id,
                caption=message.caption or ''
            )
            
        elif message.video:
            return await bot.send_video(
                chat_id=user_id,
                video=message.video.file_id,
                caption=message.caption or ''
            )
            
        elif message.document:
            return await bot.send_document(
                chat_id=user_id,
                document=message.document.file_id,
                caption=message.caption or ''
            )
            
        elif message.voice:
            return await bot.send_voice(
                chat_id=user_id,
                voice=message.voice.file_id
            )
            
        elif message.audio:
            return await bot.send_audio(
                chat_id=user_id,
                audio=message.audio.file_id,
                caption=message.caption or ''
            )
            
        else:
            logger.warning(f"未知的媒体类型: {message}")
            return None
            
    except Exception as e:
        logger.error(f"发送媒体给用户时出错: {str(e)}")
        return None

async def get_reply_to_message_id(db, update: Update) -> Optional[int]:
    """获取回复消息的ID"""
    try:
        # 如果是回复消息，获取原始消息在用户端的ID
        if update.message.reply_to_message:
            reply_msg = update.message.reply_to_message
            
            from app.models.message_map import MessageMap
            
            # 查询消息映射
            message_map = db.query(MessageMap).filter(
                MessageMap.group_chat_message_id == reply_msg.message_id
            ).first()
            
            if message_map:
                return message_map.user_chat_message_id
                
        return None
    except Exception as e:
        logger.error(f"获取回复消息ID时出错: {str(e)}")
        return None 