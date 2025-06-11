"""
处理文件和媒体消息的相关函数
"""
import logging
import asyncio
from typing import Optional, Dict, Any, List, Union

from telegram import Update, Bot, Message
from telegram.ext import ContextTypes
from telegram.error import BadRequest, TelegramError

from app.database.database import get_db
from app.models.message_map import MessageMap

# 设置日志
logger = logging.getLogger(__name__)

async def delete_message_later(bot: Bot, chat_id: int, message_id: int, delay: float = 5.0) -> None:
    """延迟删除消息
    
    Args:
        bot: 机器人实例
        chat_id: 聊天ID
        message_id: 消息ID
        delay: 延迟时间（秒）
    """
    try:
        await asyncio.sleep(delay)
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logger.error(f"延迟删除消息时出错: {str(e)}")

async def handle_file_sharing(bot: Bot, chat_id: int, topic_id: int, update: Update) -> Optional[Message]:
    """处理文件分享，将用户发送的文件转发到管理群组
    
    Args:
        bot: 机器人实例
        chat_id: 目标聊天ID（管理群组ID）
        topic_id: 话题ID
        update: 更新对象
        
    Returns:
        Message: 发送的消息对象，如果失败则返回None
    """
    try:
        message = update.message
        user = update.effective_user
        
        # 根据消息类型处理不同的媒体
        if message.photo:
            # 获取最大尺寸的照片
            photo = message.photo[-1]
            sent_message = await bot.send_photo(
                chat_id=chat_id,
                photo=photo.file_id,
                caption=message.caption or '',
                message_thread_id=topic_id
            )
            return sent_message
            
        elif message.video:
            sent_message = await bot.send_video(
                chat_id=chat_id,
                video=message.video.file_id,
                caption=message.caption or '',
                message_thread_id=topic_id
            )
            return sent_message
            
        elif message.audio:
            sent_message = await bot.send_audio(
                chat_id=chat_id,
                audio=message.audio.file_id,
                caption=message.caption or '',
                message_thread_id=topic_id
            )
            return sent_message
            
        elif message.voice:
            sent_message = await bot.send_voice(
                chat_id=chat_id,
                voice=message.voice.file_id,
                caption=message.caption or '',
                message_thread_id=topic_id
            )
            return sent_message
            
        elif message.document:
            sent_message = await bot.send_document(
                chat_id=chat_id,
                document=message.document.file_id,
                caption=message.caption or '',
                message_thread_id=topic_id
            )
            return sent_message
            
        elif message.sticker:
            sent_message = await bot.send_sticker(
                chat_id=chat_id,
                sticker=message.sticker.file_id,
                message_thread_id=topic_id
            )
            return sent_message
            
        elif message.animation:
            sent_message = await bot.send_animation(
                chat_id=chat_id,
                animation=message.animation.file_id,
                caption=message.caption or '',
                message_thread_id=topic_id
            )
            return sent_message
            
        elif message.video_note:
            sent_message = await bot.send_video_note(
                chat_id=chat_id,
                video_note=message.video_note.file_id,
                message_thread_id=topic_id
            )
            return sent_message
            
        else:
            # 不支持的媒体类型
            logger.warning(f"不支持的媒体类型: {message}")
            return None
            
    except Exception as e:
        logger.error(f"处理文件分享时出错: {str(e)}")
        return None

async def send_media_to_user(bot: Bot, user_id: int, update: Update) -> Optional[Message]:
    """将管理员发送的媒体消息转发给用户
    
    Args:
        bot: 机器人实例
        user_id: 用户ID
        update: 更新对象
        
    Returns:
        Message: 发送的消息对象，如果失败则返回None
    """
    try:
        message = update.message
        
        # 获取回复消息ID
        db = next(get_db())
        reply_to_message_id = await get_reply_to_message_id(db, update)
        
        # 根据消息类型处理不同的媒体
        if message.photo:
            # 获取最大尺寸的照片
            photo = message.photo[-1]
            sent_message = await bot.send_photo(
                chat_id=user_id,
                photo=photo.file_id,
                caption=message.caption or '',
                reply_to_message_id=reply_to_message_id
            )
            return sent_message
            
        elif message.video:
            sent_message = await bot.send_video(
                chat_id=user_id,
                video=message.video.file_id,
                caption=message.caption or '',
                reply_to_message_id=reply_to_message_id
            )
            return sent_message
            
        elif message.audio:
            sent_message = await bot.send_audio(
                chat_id=user_id,
                audio=message.audio.file_id,
                caption=message.caption or '',
                reply_to_message_id=reply_to_message_id
            )
            return sent_message
            
        elif message.voice:
            sent_message = await bot.send_voice(
                chat_id=user_id,
                voice=message.voice.file_id,
                caption=message.caption or '',
                reply_to_message_id=reply_to_message_id
            )
            return sent_message
            
        elif message.document:
            sent_message = await bot.send_document(
                chat_id=user_id,
                document=message.document.file_id,
                caption=message.caption or '',
                reply_to_message_id=reply_to_message_id
            )
            return sent_message
            
        elif message.sticker:
            sent_message = await bot.send_sticker(
                chat_id=user_id,
                sticker=message.sticker.file_id,
                reply_to_message_id=reply_to_message_id
            )
            return sent_message
            
        elif message.animation:
            sent_message = await bot.send_animation(
                chat_id=user_id,
                animation=message.animation.file_id,
                caption=message.caption or '',
                reply_to_message_id=reply_to_message_id
            )
            return sent_message
            
        elif message.video_note:
            sent_message = await bot.send_video_note(
                chat_id=user_id,
                video_note=message.video_note.file_id,
                reply_to_message_id=reply_to_message_id
            )
            return sent_message
            
        else:
            # 不支持的媒体类型
            logger.warning(f"不支持的媒体类型: {message}")
            return None
            
    except Exception as e:
        logger.error(f"发送媒体消息给用户时出错: {str(e)}")
        return None

async def get_reply_to_message_id(db, update: Update) -> Optional[int]:
    """获取回复消息的ID
    
    如果管理员回复了一条消息，查找对应的用户消息ID
    
    Args:
        db: 数据库会话
        update: 更新对象
        
    Returns:
        int: 用户端消息ID，如果没有则返回None
    """
    try:
        # 如果是回复消息，获取原始消息在用户端的ID
        if update.message.reply_to_message:
            reply_msg = update.message.reply_to_message
            
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