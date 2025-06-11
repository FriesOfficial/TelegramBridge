"""
Telegram工具函数
"""
import os
import time
import logging
import random
import string
import asyncio
from typing import Dict, List, Optional, Any, Callable, Tuple, Union
from datetime import datetime

from telegram import (
    Update,
    Bot,
    Message,
    User,
    ForumTopic,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatMember,
    ChatPermissions,
    ChatMemberAdministrator,
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaDocument
)
from telegram.ext import ContextTypes
from telegram.error import TelegramError, TimedOut, NetworkError, BadRequest, Forbidden
from telegram.constants import ChatMemberStatus

from app.config.telegram_config import telegram_config
from app.database.database import get_db
from app.models.user import User as UserModel
from app.models.message_map import MessageMap
from app.models.media_group_message import MediaGroupMessage
from app.models.formn_status import FormnStatus
from app.telegram.callbacks import (
    generate_verification_code,
    create_verification_keyboard,
    process_callback_vcode,
    process_callback_query
)

# 设置日志
logger = logging.getLogger(__name__)

# 正在处理的消息组
pending_media_groups = {}

# 系统话题名称常量
UNREAD_TOPIC_NAME = "未读消息"
SPAM_TOPIC_NAME = "垃圾消息"

# 媒体组处理相关参数
MEDIA_GROUP_DELAY = 5.0  # 延迟发送媒体组的时间（秒）

async def retry_with_backoff(func, *args, **kwargs):
    """使用指数退避重试异步函数调用"""
    retry_config = telegram_config.get_retry_config()
    max_retries = retry_config["max_retries"]
    initial_wait = retry_config["initial_wait"]
    max_wait = retry_config["max_wait"]
    
    wait_time = initial_wait
    retries = 0
    
    while True:
        try:
            return await func(*args, **kwargs)
        except BadRequest as e:
            # 检查是否是话题不存在错误
            error_msg = str(e).lower()
            if "message thread not found" in error_msg or "chat not found" in error_msg:
                logger.warning(f"话题不存在错误: {str(e)}")
                # 创建一个特殊的标记，表示需要重新创建话题
                e.requires_topic_recreation = True
                raise e
            else:
                # 其他BadRequest错误不重试
                logger.error(f"BadRequest错误，不进行重试: {str(e)}")
                raise
        except (TimedOut, NetworkError) as e:
            retries += 1
            if retries > max_retries:
                logger.error(f"最大重试次数已达到，放弃重试: {str(e)}")
                raise
                
            wait_time = min(wait_time * 2, max_wait)
            logger.warning(f"操作超时或网络错误，将在 {wait_time} 秒后重试 ({retries}/{max_retries}): {str(e)}")
            await asyncio.sleep(wait_time)
        except Exception as e:
            # 其他错误不重试
            logger.error(f"操作失败: {str(e)}")
            raise

async def initialize_system_topics(bot: Bot) -> bool:
    """初始化系统话题，包括未读消息和垃圾消息话题"""
    try:
        logger.info("开始初始化系统话题...")
        
        # 获取或创建未读消息话题
        unread_topic = await get_system_topic(bot, UNREAD_TOPIC_NAME)
        if not unread_topic:
            logger.error(f"初始化{UNREAD_TOPIC_NAME}话题失败")
            return False
        
        # 获取或创建垃圾消息话题
        spam_topic = await get_system_topic(bot, SPAM_TOPIC_NAME)
        if not spam_topic:
            logger.error(f"初始化{SPAM_TOPIC_NAME}话题失败")
            return False
        
        logger.info("系统话题初始化完成")
        return True
    except Exception as e:
        logger.error(f"初始化系统话题时出错: {str(e)}")
        return False

async def get_system_topic(bot: Bot, topic_name: str) -> Optional[ForumTopic]:
    """获取系统话题，如果不存在则创建"""
    try:
        # 尝试在数据库中查找系统话题记录
        db = next(get_db())
        forum_status = db.query(FormnStatus).filter(
            FormnStatus.topic_name == topic_name,
            FormnStatus.is_system_topic == True
        ).first()
        
        # 系统话题存在，直接返回
        if forum_status:
            # 直接返回话题对象，不进行验证
            # 如果话题不存在，会在后续使用时捕获BadRequest异常
            return ForumTopic(
                message_thread_id=forum_status.topic_id,
                name=forum_status.topic_name,
                icon_color=0x6FB9F0  # 默认颜色
            )
        
        # 系统话题不存在，创建新话题
        # 根据话题名称选择不同的图标颜色
        icon_color = 0x6FB9F0  # 默认蓝色
        if topic_name == UNREAD_TOPIC_NAME:
            icon_color = 16478047  # 红色
        elif topic_name == SPAM_TOPIC_NAME:
            icon_color = 16766777  # 黄色
            
        logger.info(f"创建系统话题: {topic_name}")
        new_topic = await retry_with_backoff(
            bot.create_forum_topic,
            chat_id=telegram_config.admin_group_id,
            name=topic_name,
            icon_color=icon_color
        )
        
        # 创建并保存新的系统话题记录
        new_forum_status = FormnStatus(
            topic_id=new_topic.message_thread_id,
            topic_name=topic_name,
            is_system_topic=True
        )
        db.add(new_forum_status)
        db.commit()
        logger.info(f"系统话题创建成功: {topic_name} (ID: {new_topic.message_thread_id})")
        
        # 发送话题介绍消息
        intro_text = f"这是系统自动创建的{topic_name}话题。"
        if topic_name == UNREAD_TOPIC_NAME:
            intro_text += "未被管理员回复的用户消息将被归类到此话题。"
        elif topic_name == SPAM_TOPIC_NAME:
            intro_text += "被标记为垃圾信息的用户消息将被归类到此话题。"
            
        await retry_with_backoff(
            bot.send_message,
            chat_id=telegram_config.admin_group_id,
            text=intro_text,
            message_thread_id=new_topic.message_thread_id
        )
        
        return new_topic
    except Exception as e:
        logger.error(f"获取或创建系统话题时出错: {str(e)}")
        if 'db' in locals():
            db.rollback()
        return None

async def verify_admin_group(bot: Bot) -> bool:
    """验证管理群组是否有效"""
    try:
        # 检查是否可以获取群组信息
        chat = await retry_with_backoff(
            bot.get_chat,
            chat_id=telegram_config.admin_group_id
        )
        
        # 检查是否是超级群组
        if not chat.type == "supergroup":
            logger.error(f"管理群组 {telegram_config.admin_group_id} 不是超级群组")
            return False
            
        # 检查是否启用了话题功能
        if not chat.is_forum:
            logger.error(f"管理群组 {telegram_config.admin_group_id} 未启用话题功能")
            return False
            
        # 检查机器人权限
        bot_member = await retry_with_backoff(
            bot.get_chat_member,
            chat_id=telegram_config.admin_group_id,
            user_id=bot.id
        )
        
        # 检查是否是管理员
        if bot_member.status != ChatMemberStatus.ADMINISTRATOR:
            logger.error(f"机器人不是管理群组 {telegram_config.admin_group_id} 的管理员")
            return False
            
        # 检查是否有管理话题的权限
        if isinstance(bot_member, ChatMemberAdministrator) and not bot_member.can_manage_topics:
            logger.error(f"机器人没有管理话题的权限")
            return False
            
        return True
    except Exception as e:
        logger.error(f"验证管理群组时出错: {str(e)}")
        return False

async def check_user_ban_status(db, user_id: int) -> bool:
    """检查用户是否被禁止使用系统"""
    try:
        user = await get_user_by_id(db, user_id)
        # 用户被禁用时is_active为False
        return not user.is_active if user else False
    except Exception as e:
        logger.error(f"检查用户禁止状态时出错: {str(e)}")
        return False

async def get_user_by_id(db, user_id: int, create_if_not_exists: bool = False) -> Optional[UserModel]:
    """通过ID获取用户，如果不存在且create_if_not_exists为True则创建"""
    try:
        user = db.query(UserModel).filter(UserModel.id == user_id).first()
        
        if user is None and create_if_not_exists:
            user = UserModel(id=user_id)
            db.add(user)
            db.commit()
            db.refresh(user)
            logger.info(f"创建新用户: {user_id}")
            
        return user
    except Exception as e:
        logger.error(f"获取用户信息时出错: {str(e)}")
        db.rollback()
        return None

async def create_or_get_user_topic(bot: Bot, user: User, from_group: bool = False, source_group_id: int = None, source_group_name: str = None) -> Optional[ForumTopic]:
    """为用户创建话题或获取现有话题
    
    Args:
        bot: Bot实例
        user: 用户对象
        from_group: 是否来自群组消息
        source_group_id: 来源群组ID（如果from_group为True）
        source_group_name: 来源群组名称（如果from_group为True）
        
    Returns:
        ForumTopic: 话题对象
    """
    try:
        db = next(get_db())
        
        # 获取用户的Premium状态
        try:
            user_chat = await bot.get_chat(user.id)
            is_premium = getattr(user_chat, 'is_premium', False)
        except Exception as e:
            logger.error(f"获取用户Premium状态时出错: {str(e)}")
            is_premium = getattr(user, 'is_premium', False)  # 尝试从User对象获取
        
        # 检查用户是否有对应类型的话题（私聊或群组）
        query = db.query(FormnStatus).filter(
            FormnStatus.user_id == user.id,
            FormnStatus.from_group == from_group
        )
        
        # 如果是群组消息，还需匹配群组ID
        if from_group and source_group_id:
            query = query.filter(FormnStatus.source_group_id == source_group_id)
            
        forum_status = query.first()
        
        # 如果数据库中有话题记录，直接返回，无需验证
        # 后续在使用时如果发现话题不存在，会触发BadRequest异常，在外部处理
        if forum_status:
            # 检查话题名称是否需要更新Premium标记
            premium_mark = "💎"
            needs_update = False
            
            # 确定正确的前缀格式
            group_prefix = "[群组] " if from_group else ""
            
            if is_premium and not (forum_status.topic_name.startswith(premium_mark) or 
                                  (from_group and forum_status.topic_name.startswith(f"[群组] {premium_mark}"))):
                # 用户是Premium会员但话题名称中没有钻石标记，需要更新
                if from_group:
                    new_topic_name = f"[群组] {premium_mark}{forum_status.topic_name.replace('[群组] ', '')}"
                else:
                    new_topic_name = f"{premium_mark}{forum_status.topic_name}"
                needs_update = True
            elif not is_premium and premium_mark in forum_status.topic_name:
                # 用户不是Premium会员但话题名称有钻石标记，需要更新
                if from_group:
                    new_topic_name = f"[群组] {forum_status.topic_name.replace('[群组] ', '').replace(premium_mark, '')}"
                else:
                    new_topic_name = forum_status.topic_name.replace(premium_mark, '')
                needs_update = True
            
            if needs_update:
                try:
                    # 更新话题名称
                    await bot.edit_forum_topic(
                        chat_id=telegram_config.admin_group_id,
                        message_thread_id=forum_status.topic_id,
                        name=new_topic_name[:64]  # 确保不超过最大长度
                    )
                    
                    # 更新数据库记录
                    forum_status.topic_name = new_topic_name[:64]
                    db.commit()
                    logger.info(f"已更新用户 {user.id} 的话题名称以反映Premium状态: {new_topic_name[:64]}")
                except BadRequest as e:
                    # 如果是话题不存在错误，标记为需要重新创建
                    if "message thread not found" in str(e).lower() or "chat not found" in str(e).lower():
                        # 删除旧记录
                        db.delete(forum_status)
                        db.commit()
                        # 将在下面重新创建话题
                        forum_status = None
                    else:
                        logger.error(f"更新话题名称时出错: {str(e)}")
                except Exception as update_e:
                    logger.error(f"更新话题名称时出错: {str(update_e)}")
            
            # 如果话题记录存在且没有被标记为需要重新创建，直接返回
            if forum_status:
                return ForumTopic(
                    message_thread_id=forum_status.topic_id,
                    name=forum_status.topic_name,
                    icon_color=0x6FB9F0  # 默认的蓝色图标颜色
                )
        
        # 创建新话题
        premium_mark = "💎" if is_premium else ""
        # 根据来源添加不同前缀
        group_prefix = "[群组] " if from_group else ""
        
        # 构建话题名称，确保不显示None
        topic_name = f"{group_prefix}{premium_mark}{user.first_name}"
        if user.last_name:  # 只有当last_name不为None时才添加
            topic_name += f" {user.last_name}"
        
        # 如果来自群组，添加群组信息
        if from_group and source_group_name:
            topic_name += f" - {source_group_name}"
        
        topic = await retry_with_backoff(
            bot.create_forum_topic,
            chat_id=telegram_config.admin_group_id,
            name=topic_name[:64]  # 话题名称最大长度为64
        )
        
        # 创建新的话题记录
        new_forum_status = FormnStatus(
            user_id=user.id,
            topic_id=topic.message_thread_id,
            topic_name=topic_name[:64],
            from_group=from_group,
            source_group_id=source_group_id if from_group else None,
            source_group_name=source_group_name if from_group else None
        )
        
        # 添加新记录并提交
        db.add(new_forum_status)
        db.commit()
        logger.info(f"为用户 {user.id} 创建话题: {topic.message_thread_id} (来自群组: {from_group})")
        
        # 发送话题介绍消息
        intro_text = f"用户信息:\nID: {user.id}\n"
        if user.username:
            intro_text += f"用户名: @{user.username}\n"
        intro_text += f"昵称: {user.first_name}"
        if user.last_name:
            intro_text += f" {user.last_name}"
        
        # 添加Telegram Premium会员状态信息
        intro_text += f"\n\n🏅 Telegram会员: {'💎 是' if is_premium else '❌ 否'}"
        
        # 如果来自群组，添加群组信息（确保不显示None）
        if from_group:
            group_info = "\n\n📣 来源群组: "
            if source_group_name:
                group_info += source_group_name
            else:
                group_info += "未知群组"
            
            if source_group_id:
                group_info += f" [ID: {source_group_id}]"
            
            intro_text += group_info
        
        # 创建"已读"和"封禁"按钮
        keyboard = [
            [
                InlineKeyboardButton("✅ 标记为已读", callback_data=f"read_all_{user.id}"),
                InlineKeyboardButton("🚫 封禁用户", callback_data=f"ban_{user.id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
            
        await retry_with_backoff(
            bot.send_message,
            chat_id=telegram_config.admin_group_id,
            text=intro_text,
            message_thread_id=topic.message_thread_id,
            reply_markup=reply_markup
        )
        
        return topic
    except Exception as e:
        logger.error(f"创建话题时出错: {str(e)}")
        if 'db' in locals():
            db.rollback()
        return None

async def get_topic_title_by_user(db, topic_id: int) -> Optional[str]:
    """通过话题ID获取话题标题"""
    try:
        forum_status = db.query(FormnStatus).filter(FormnStatus.topic_id == topic_id).first()
        return forum_status.topic_name if forum_status else None
    except Exception as e:
        logger.error(f"获取话题标题时出错: {str(e)}")
        return None

async def get_user_topic_id(db, user_id: int) -> Optional[int]:
    """获取用户的话题ID"""
    try:
        forum_status = db.query(FormnStatus).filter(FormnStatus.user_id == user_id).first()
        return forum_status.topic_id if forum_status else None
    except Exception as e:
        logger.error(f"获取用户话题ID时出错: {str(e)}")
        return None

async def send_message_to_user(context: ContextTypes.DEFAULT_TYPE, message: Message, user_id: int) -> Optional[Message]:
    """将消息发送给指定用户"""
    try:
        # 使用send_copy简化消息发送
        user_chat = await context.bot.get_chat(user_id)
        return await retry_with_backoff(
            user_chat.send_copy,
            from_chat_id=message.chat_id,
            message_id=message.message_id
        )
    except Exception as e:
        logger.error(f"发送消息给用户时出错: {str(e)}")
        return None

async def send_message_to_topic(context: ContextTypes.DEFAULT_TYPE, message: Message, topic_id: int, caption: str = None, user: User = None) -> Optional[Message]:
    """将消息发送到指定话题"""
    try:
        # 获取管理员群组的Chat对象
        admin_chat = await context.bot.get_chat(telegram_config.admin_group_id)
        
        # 使用send_copy简化消息发送
        return await retry_with_backoff(
            admin_chat.send_copy,
            from_chat_id=message.chat_id,
            message_id=message.message_id,
            message_thread_id=topic_id
        )
    except BadRequest as e:
        # 检查是否是"话题不存在"错误
        error_msg = str(e).lower()
        needs_recreation = "message thread not found" in error_msg or "chat not found" in error_msg
        
        if needs_recreation and user:
            logger.warning(f"话题 {topic_id} 不存在，尝试创建新话题")
            
            try:
                # 删除数据库中的旧记录
                db = next(get_db())
                forum_status = db.query(FormnStatus).filter(
                    FormnStatus.topic_id == topic_id
                ).first()
                
                if forum_status:
                    db.delete(forum_status)
                    db.commit()
                
                # 直接创建新话题，内部会处理旧记录的删除
                new_topic = await create_or_get_user_topic(context.bot, user)
                if not new_topic:
                    logger.error(f"为用户 {user.id} 创建新话题失败")
                    raise e  # 重新抛出原始异常
                    
                logger.info(f"已为用户 {user.id} 创建新话题: {new_topic.message_thread_id}")
                
                # 递归调用自身，使用新的话题ID发送消息
                return await send_message_to_topic(context, message, new_topic.message_thread_id, caption, user)
            except Exception as create_error:
                logger.error(f"尝试创建新话题时出错: {str(create_error)}")
                raise create_error
        else:
            # 其他BadRequest错误或无法重建话题
            logger.error(f"BadRequest错误: {str(e)}")
            raise e
    except Exception as e:
        logger.error(f"发送消息到话题时出错: {str(e)}")
        raise e

async def send_to_unread_topic(context: ContextTypes.DEFAULT_TYPE, user: User, message: Message, admin_message: Message, topic, unread_topic):
    """将消息转发到未读话题"""
    if not unread_topic:
        logger.error("未能获取未读消息话题")
        return False
        
    try:
        db = next(get_db())
        # 导入SQLAlchemy的and_函数
        from sqlalchemy import and_
        
        logger.info(f"准备向未读话题发送消息: 用户ID={user.id}, 管理员消息ID={admin_message.message_id}")
        
        # 查找消息映射
        message_map = db.query(MessageMap).filter(
            MessageMap.group_chat_message_id == admin_message.message_id
        ).first()
        
        if not message_map:
            logger.error(f"找不到消息映射: {admin_message.message_id}")
            return False
        
        # 检查消息来源（私聊/群组）- 直接从message_map中获取
        is_from_group = message_map.is_from_group
        group_name = message_map.source_group_name
        group_id = message_map.source_group_id
        
        # 检查该用户是否已经有相同来源的未读消息
        # 如果是群组消息，需要检查是否来自相同群组
        if is_from_group:
            existing_unread = db.query(MessageMap).filter(
                MessageMap.user_telegram_id == user.id,
                MessageMap.is_unread_topic == True,
                MessageMap.is_from_group == True,
                MessageMap.source_group_id == group_id
            ).first()
        else:
            # 如果是私聊消息，只检查是否有私聊未读消息
            existing_unread = db.query(MessageMap).filter(
                MessageMap.user_telegram_id == user.id,
                MessageMap.is_unread_topic == True,
                MessageMap.is_from_group == False
            ).first()
        
        if existing_unread:
            # 用户已有相同来源的未读消息，仅更新当前消息的is_unread_topic标记
            message_map.is_unread_topic = True
            db.commit()
            if is_from_group:
                logger.info(f"用户 {user.id} 已有来自群组 {group_id} 的未读消息，不重复发送到未读话题")
            else:
                logger.info(f"用户 {user.id} 已有私聊未读消息，不重复发送到未读话题")
            return True
            
        # 准备URL链接（从群组ID中去除负号和前面的100）
        group_id_str = str(telegram_config.admin_group_id)
        if group_id_str.startswith('-100'):
            link_chat_id = group_id_str[4:]  # 移除开头的 "-100"
        elif group_id_str.startswith('-'):
            link_chat_id = group_id_str[1:]  # 移除开头的 "-"
        else:
            link_chat_id = group_id_str
            
        # 获取话题ID用于链接跳转
        topic_id = None
        if topic and hasattr(topic, 'message_thread_id'):
            topic_id = topic.message_thread_id
        else:
            # 如果没有提供有效的topic，尝试从数据库中获取用户的话题ID
            # 根据消息来源查找正确的话题
            if is_from_group and group_id:
                # 如果是群组消息，找到对应群组的话题
                user_forum_status = db.query(FormnStatus).filter(
                    FormnStatus.user_id == user.id,
                    FormnStatus.from_group == True,
                    FormnStatus.source_group_id == group_id
                ).first()
            else:
                # 如果是私聊消息，找到私聊话题
                user_forum_status = db.query(FormnStatus).filter(
                    FormnStatus.user_id == user.id,
                    FormnStatus.from_group == False
                ).first()
                
            if user_forum_status:
                topic_id = user_forum_status.topic_id
                
        if not topic_id:
            logger.warning(f"无法获取用户 {user.id} 的话题ID，将使用固定文本")
            view_conversation_text = "💬 对话"
            conversation_url = f"https://t.me/c/{link_chat_id}/"
        else:
            view_conversation_text = f"💬 对话"
            # 构建话题链接并添加参数使其自动跳转到对话底部
            conversation_url = f"https://t.me/c/{link_chat_id}/{topic_id}?single&comment=0"
        
        # 创建操作按钮 - 使用直接URL跳转
        keyboard = [
            [
                InlineKeyboardButton(view_conversation_text, url=conversation_url)
            ],
            [
                InlineKeyboardButton("✅ 标记为已读", callback_data=f"read_{admin_message.message_id}"),
                InlineKeyboardButton("🚫 封禁用户", callback_data=f"ban_{user.id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # 检查用户是否是Telegram Premium会员
        try:
            user_chat = await context.bot.get_chat(user.id)
            is_premium = getattr(user_chat, 'is_premium', False)
        except Exception as e:
            logger.error(f"获取用户Premium状态时出错: {str(e)}")
            is_premium = getattr(user, 'is_premium', False)  # 尝试从User对象获取
        
        # 准备消息文本 - 使用更清晰的格式
        premium_mark = "💎" if is_premium else ""
        message_text = "📝 *新消息通知*\n"
        message_text += "━━━━━━━━━━━━━━━\n"
        
        # 添加消息来源信息 - 使用更醒目的标识
        if is_from_group:
            message_text += "📢 *来源*: *群组消息*\n"
            if group_name:
                message_text += f"• 群组: `{group_name}`\n"
            if group_id:
                message_text += f"• 群组ID: `{group_id}`\n"
        else:
            message_text += "💬 *来源*: *私聊消息*\n"
            
        message_text += "━━━━━━━━━━━━━━━\n"
        message_text += "👤 *用户信息*\n"

        # 用户名称部分
        if premium_mark:
            message_text += f"• 昵称: {premium_mark} {user.first_name}"
        else:
            message_text += f"• 昵称: {user.first_name}"
        
        if user.last_name:
            message_text += f" {user.last_name}"
        message_text += "\n"

        # 用户名和ID部分
        if user.username:
            message_text += f"• 用户名: @{user.username}\n"
        message_text += f"• ID: `{user.id}`\n"

        # 会员状态信息
        message_text += f"• 会员: {'✅ 是' if is_premium else '❌ 否'}\n"

        # 添加语言信息
        language_code = getattr(user, 'language_code', None)
        if language_code:
            message_text += f"• 语言: {language_code}"

        # 发送到未读消息话题
        logger.debug(f"准备发送消息到未读话题 ID={unread_topic.message_thread_id}, 群组ID={telegram_config.admin_group_id}")
        
        try:
            unread_message = await retry_with_backoff(
                context.bot.send_message,
                chat_id=telegram_config.admin_group_id,
                text=message_text,
                reply_markup=reply_markup,
                message_thread_id=unread_topic.message_thread_id,
                parse_mode="Markdown"  # 启用Markdown格式
            )
            
            # 更新消息映射
            message_map.is_unread_topic = True
            message_map.unread_topic_message_id = unread_message.message_id  # 保存未读话题消息ID
            db.commit()
            
            logger.info(f"用户消息已转发到未读话题: {user.id} -> {unread_topic.message_thread_id}")
            return True
            
        except BadRequest as e:
            # 检查是否是"话题不存在"错误
            error_msg = str(e).lower()
            needs_recreation = "message thread not found" in error_msg or "chat not found" in error_msg
            
            if needs_recreation:
                logger.warning(f"未读话题 {unread_topic.message_thread_id} 不存在，尝试重新获取")
                
                # 首先在数据库中删除旧的系统话题记录
                old_forum_status = db.query(FormnStatus).filter(
                    FormnStatus.topic_id == unread_topic.message_thread_id,
                    FormnStatus.is_system_topic == True
                ).first()
                
                if old_forum_status:
                    logger.info(f"删除旧的未读话题记录: {old_forum_status.topic_id}")
                    db.delete(old_forum_status)
                    db.commit()
                
                # 重新获取未读话题
                new_unread_topic = await get_system_topic(context.bot, UNREAD_TOPIC_NAME)
                if not new_unread_topic:
                    logger.error("无法重新获取未读话题")
                    return False
                
                # 使用新话题重试
                try:
                    retry_message = await context.bot.send_message(
                        chat_id=telegram_config.admin_group_id,
                        text=message_text,
                        reply_markup=reply_markup,
                        message_thread_id=new_unread_topic.message_thread_id,
                        parse_mode="Markdown"  # 启用Markdown格式
                    )
                    
                    # 更新消息映射，确保设置unread_topic_message_id
                    message_map.is_unread_topic = True
                    message_map.unread_topic_message_id = retry_message.message_id  # 保存新的未读话题消息ID
                    db.commit()
                    
                    logger.info(f"成功重试发送到新的未读话题: {user.id} -> {new_unread_topic.message_thread_id}")
                    logger.info(f"设置未读话题消息ID: {retry_message.message_id}")
                    return True
                except Exception as retry_error:
                    logger.error(f"重试发送到新未读话题时出错: {str(retry_error)}")
                    return False
            else:
                # 其他BadRequest错误
                logger.error(f"发送到未读话题时出错: {str(e)}")
                return False
    except Exception as e:
        logger.error(f"转发到未读消息话题失败: {str(e)}")
        return False

async def forward_message_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """将用户消息转发到管理群组"""
    try:
        user = update.effective_user
        message = update.message
        
        # 如果是forum_topic_created类型的消息，直接忽略
        if hasattr(message, 'forum_topic_created') and message.forum_topic_created:
            logger.debug(f"忽略话题创建消息: {message.message_id}")
            return
            
        # 获取用户话题
        topic = await create_or_get_user_topic(context.bot, user)
        if not topic:
            await message.reply_text("消息发送失败，请联系管理员")
            return
            
        # 获取未读消息话题
        unread_topic = await get_system_topic(context.bot, UNREAD_TOPIC_NAME)
        if not unread_topic:
            logger.error("未能获取未读消息话题")
            # 继续处理，即使未读话题不可用
        
        # 根据消息类型转发到用户话题
        admin_message = None
        
        # 使用辅助函数发送消息到用户话题
        try:
            admin_message = await send_message_to_topic(context, message, topic.message_thread_id, user=user)
            if not admin_message:
                await message.reply_text("不支持的消息类型")
                return
        except BadRequest as e:
            # 检查是否是话题不存在错误
            error_msg = str(e).lower()
            if "message thread not found" in error_msg or "chat not found" in error_msg:
                logger.warning(f"用户话题 {topic.message_thread_id} 不存在，重新创建")
                # 重新创建话题
                topic = await create_or_get_user_topic(context.bot, user)
                if not topic:
                    await message.reply_text("消息发送失败，请联系管理员")
                    return
                
                # 重试发送消息
                admin_message = await send_message_to_topic(context, message, topic.message_thread_id, user=user)
                if not admin_message:
                    await message.reply_text("不支持的消息类型")
                    return
            else:
                # 其他API错误
                raise
                
        # 保存消息映射
        if admin_message:
            db = next(get_db())
            message_map = MessageMap(
                user_telegram_id=user.id,
                user_chat_message_id=message.message_id,
                group_chat_message_id=admin_message.message_id,
                created_at=datetime.now(),
                is_from_group=False  # 标记为私聊消息
            )
            db.add(message_map)
            db.commit()
            
            logger.info(f"用户消息已转发到话题: {user.id} -> {topic.message_thread_id}")
            
            # 转发到未读话题，无需提前检查，让send_to_unread_topic函数自己判断是否需要发送
            await send_to_unread_topic(context, user, message, admin_message, topic, unread_topic)
    except Exception as e:
        logger.error(f"转发消息到管理群组时出错: {str(e)}")
        if update and update.message:
            await update.message.reply_text("消息发送失败，请稍后重试")

async def forward_message_to_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """将管理员的回复转发给用户"""
    try:
        if not update.message.is_topic_message:
            return
            
        # 获取话题ID
        topic_id = update.message.message_thread_id
        
        # 查询用户ID
        db = next(get_db())
        forum_status = db.query(FormnStatus).filter(FormnStatus.topic_id == topic_id).first()
        
        if not forum_status:
            logger.warning(f"找不到话题 {topic_id} 对应的用户")
            await update.message.reply_text("找不到对应的用户，无法转发消息")
            return
            
            
        user_id = forum_status.user_id
        message = update.message
        
        # 根据消息类型转发
        user_message = None
        
        try:
            # 使用辅助函数发送消息给用户
            user_message = await send_message_to_user(context, message, user_id)
            if not user_message:
                await message.reply_text("不支持的消息类型，无法转发")
                return
        except (BadRequest, Forbidden) as e:
            # 检查是否是聊天不存在或被阻止的错误
            if "chat not found" in str(e).lower() or "blocked" in str(e).lower() or "user is deactivated" in str(e).lower():
                logger.warning(f"无法发送消息给用户 {user_id}，可能已被阻止或用户已注销")
                await update.message.reply_text("无法发送消息给该用户，可能已被阻止或用户已注销")
                return
            else:
                # 其他API错误，抛出异常
                raise
            
        # 保存消息映射
        if user_message:
            message_map = MessageMap(
                user_telegram_id=user_id,
                user_chat_message_id=user_message.message_id,
                group_chat_message_id=message.message_id,
                created_at=datetime.now(),
                is_from_group=forum_status.from_group,  # 根据话题来源设置
                source_group_id=forum_status.source_group_id,  # 记录群组ID
                source_group_name=forum_status.source_group_name  # 记录群组名称
            )
            db.add(message_map)
            db.commit()
            
            # 自动将该用户的对应来源的未读消息标记为已读
            try:
                # 判断当前消息的来源类型
                is_from_group = forum_status.from_group
                source_group_id = forum_status.source_group_id
                
                # 根据来源类型查找对应的未读消息
                if is_from_group:
                    # 如果是群组消息，只标记来自相同群组的未读消息为已读
                    unread_messages = db.query(MessageMap).filter(
                        MessageMap.user_telegram_id == user_id,
                        MessageMap.is_unread_topic == True,
                        MessageMap.is_from_group == True,
                        MessageMap.source_group_id == source_group_id
                    ).all()
                else:
                    # 如果是私聊消息，只标记私聊的未读消息为已读
                    unread_messages = db.query(MessageMap).filter(
                        MessageMap.user_telegram_id == user_id,
                        MessageMap.is_unread_topic == True,
                        MessageMap.is_from_group == False
                    ).all()
                
                if unread_messages:
                    # 标记所有未读消息为已读
                    now = datetime.now()
                    for unread_msg in unread_messages:
                        unread_msg.is_unread_topic = False
                        unread_msg.handled_by_user_id = context.bot.id  # 使用bot ID作为处理人
                        unread_msg.handled_time = now
                        
                        # 尝试删除未读话题中的消息
                        if unread_msg.unread_topic_message_id:
                            try:
                                await context.bot.delete_message(
                                    chat_id=telegram_config.admin_group_id,
                                    message_id=unread_msg.unread_topic_message_id
                                )
                                logger.info(f"已删除未读话题中的消息: {unread_msg.unread_topic_message_id}")
                            except Exception as del_error:
                                logger.error(f"删除未读话题消息时出错: {str(del_error)}")
                    
                    # 提交更改
                    db.commit()
                    source_type = "群组" if is_from_group else "私聊"
                    source_info = f" ({forum_status.source_group_name})" if is_from_group and forum_status.source_group_name else ""
                    logger.info(f"用户 {user_id} 回复了管理员消息，已自动将{source_type}{source_info}未读消息({len(unread_messages)}条)标记为已读")
            except Exception as e:
                logger.error(f"自动标记用户未读消息时出错: {str(e)}")
            
            logger.info(f"管理员消息已转发: {topic_id} -> {user_id}")
    except Exception as e:
        logger.error(f"转发消息到用户时出错: {str(e)}")
        if update and update.message:
            await update.message.reply_text("消息转发失败，请稍后重试。")

async def handle_media_group(update: Update, context: ContextTypes.DEFAULT_TYPE, forward_func: Callable) -> None:
    """处理媒体组消息"""
    try:
        message = update.message
        media_group_id = message.media_group_id
        user = message.from_user
        
        # 保存媒体组消息到数据库
        db = next(get_db())
        media_group_msg = MediaGroupMessage(
            media_group_id=media_group_id,
            message_id=message.message_id,
            chat_id=message.chat.id,
            created_at=datetime.now()
        )
        db.add(media_group_msg)
        db.commit()
        
        # 检查job_queue是否可用
        if not hasattr(context, 'job_queue') or context.job_queue is None:
            logger.warning("JobQueue未配置，无法处理媒体组消息。请安装python-telegram-bot[job-queue]")
            # 直接转发单条消息
            if forward_func == forward_message_to_admin:
                await forward_message_to_admin(update, context)
            elif forward_func == forward_message_to_user:
                await forward_message_to_user(update, context)
            return
        
        # 判断是用户到管理员还是管理员到用户的转发
        if forward_func == forward_message_to_admin:
            # 用户发送到管理员
            job_name = f"media_group_{media_group_id}_{user.id}_u2a"
            
            # 检查是否已经有相同ID的媒体组任务
            jobs = context.job_queue.get_jobs_by_name(job_name)
            if jobs:
                logger.debug(f"媒体组 {media_group_id} 已有发送任务，添加新消息")
                # 不再直接返回，让所有消息都能被保存到数据库中
            else:
                # 创建定时任务，延迟发送媒体组
                context.job_queue.run_once(
                    send_media_group_to_admin,
                    MEDIA_GROUP_DELAY,
                    data={
                        "media_group_id": media_group_id,
                        "user_id": user.id
                    },
                    name=job_name
                )
                logger.debug(f"为媒体组 {media_group_id} 创建发送任务，将在 {MEDIA_GROUP_DELAY} 秒后发送")
            
        elif forward_func == forward_message_to_user:
            # 管理员发送到用户
            topic_id = message.message_thread_id
            
            # 查询用户ID
            forum_status = db.query(FormnStatus).filter(FormnStatus.topic_id == topic_id).first()
            if not forum_status:
                logger.warning(f"找不到话题 {topic_id} 对应的用户")
                return
                
            user_id = forum_status.user_id
            job_name = f"media_group_{media_group_id}_{topic_id}_a2u"
            
            # 检查是否已经有相同ID的媒体组任务
            jobs = context.job_queue.get_jobs_by_name(job_name)
            if jobs:
                logger.debug(f"媒体组 {media_group_id} 已有发送任务，添加新消息")
                # 不再直接返回，让所有消息都能被保存到数据库中
            else:
                # 创建定时任务，延迟发送媒体组
                context.job_queue.run_once(
                    send_media_group_to_user,
                    MEDIA_GROUP_DELAY,
                    data={
                        "media_group_id": media_group_id,
                        "user_id": user_id,
                        "topic_id": topic_id
                    },
                    name=job_name
                )
                logger.debug(f"为媒体组 {media_group_id} 创建发送任务，将在 {MEDIA_GROUP_DELAY} 秒后发送")
            
    except Exception as e:
        logger.error(f"处理媒体组消息时出错: {str(e)}")

async def send_media_group_to_admin(context: ContextTypes.DEFAULT_TYPE) -> None:
    """将媒体组消息发送到管理员群组"""
    job = context.job
    data = job.data
    media_group_id = data["media_group_id"]
    user_id = data["user_id"]
    
    try:
        logger.info(f"开始处理媒体组 {media_group_id}，发送到管理员群组")
        
        # 从数据库获取媒体组消息
        db = next(get_db())
        media_group_msgs = db.query(MediaGroupMessage).filter(
            MediaGroupMessage.media_group_id == media_group_id,
            MediaGroupMessage.chat_id == user_id
        ).all()
        
        if not media_group_msgs:
            logger.warning(f"未找到媒体组 {media_group_id} 的消息")
            return
            
        # 获取用户信息
        user = await context.bot.get_chat(user_id)
        
        # 获取用户话题
        topic = await create_or_get_user_topic(context.bot, user)
        if not topic:
            logger.error(f"无法获取或创建用户 {user_id} 的话题")
            return
            
        # 获取未读消息话题
        unread_topic = await get_system_topic(context.bot, UNREAD_TOPIC_NAME)
        
        # 获取管理员群组的Chat对象
        admin_chat = await context.bot.get_chat(telegram_config.admin_group_id)
        
        # 排序消息（根据消息ID）
        media_group_msgs.sort(key=lambda m: m.message_id)
        
        # 使用send_copies方法直接转发媒体组
        message_ids = [msg.message_id for msg in media_group_msgs]
        
        try:
            # 使用send_copies方法批量转发消息
            admin_messages = await admin_chat.send_copies(
                from_chat_id=user_id,
                message_ids=message_ids,
                message_thread_id=topic.message_thread_id
            )
            
            # 保存消息映射
            for i, admin_message in enumerate(admin_messages):
                if i < len(media_group_msgs):
                    message_map = MessageMap(
                        user_telegram_id=user_id,
                        user_chat_message_id=media_group_msgs[i].message_id,
                        group_chat_message_id=admin_message.message_id,
                        created_at=datetime.now(),
                        is_from_group=False  # 标记为私聊消息
                    )
                    db.add(message_map)
            
            db.commit()
            logger.info(f"用户 {user_id} 的媒体组已转发到话题 {topic.message_thread_id}")
            
            # 只转发第一条消息到未读话题，无需提前检查，让send_to_unread_topic函数自己判断是否需要发送
            if admin_messages:
                first_admin_msg = admin_messages[0]
                if first_admin_msg:
                    # 传递私聊媒体消息到未读话题
                    await send_to_unread_topic(context, user, None, first_admin_msg, topic, unread_topic)
        
        except Exception as e:
            logger.error(f"发送媒体组到管理员话题时出错: {str(e)}")
                
    except Exception as e:
        logger.error(f"处理媒体组发送到管理员时出错: {str(e)}")

async def send_media_group_to_user(context: ContextTypes.DEFAULT_TYPE) -> None:
    """将媒体组消息发送到用户"""
    job = context.job
    data = job.data
    media_group_id = data["media_group_id"]
    user_id = data["user_id"]
    topic_id = data["topic_id"]
    
    try:
        logger.info(f"开始处理媒体组 {media_group_id}，发送到用户 {user_id}")
        
        # 从数据库获取媒体组消息
        db = next(get_db())
        media_group_msgs = db.query(MediaGroupMessage).filter(
            MediaGroupMessage.media_group_id == media_group_id,
            MediaGroupMessage.chat_id == telegram_config.admin_group_id
        ).all()
        
        if not media_group_msgs:
            logger.warning(f"未找到媒体组 {media_group_id} 的消息")
            return
            
        # 获取话题信息，判断是否来自群组
        forum_status = db.query(FormnStatus).filter(FormnStatus.topic_id == topic_id).first()
        if not forum_status:
            logger.warning(f"找不到话题 {topic_id} 对应的用户")
            return
            
        # 如果是群组话题，转发到群组而不是用户私聊
        if forum_status.from_group and forum_status.source_group_id:
            # 引用group_handlers模块中的send_topic_media_to_group函数
            from app.telegram.group_handlers import send_topic_media_to_group
            await send_topic_media_to_group(context, media_group_id, topic_id, forum_status)
            return
            
        # 获取用户的Chat对象
        user_chat = await context.bot.get_chat(user_id)
        
        # 排序消息（根据消息ID）
        media_group_msgs.sort(key=lambda m: m.message_id)
        
        # 使用send_copies方法直接转发媒体组
        message_ids = [msg.message_id for msg in media_group_msgs]
        
        try:
            # 使用send_copies方法批量转发消息
            user_messages = await user_chat.send_copies(
                from_chat_id=telegram_config.admin_group_id,
                message_ids=message_ids
            )
            
            # 保存消息映射
            for i, user_message in enumerate(user_messages):
                if i < len(media_group_msgs):
                    message_map = MessageMap(
                        user_telegram_id=user_id,
                        user_chat_message_id=user_message.message_id,
                        group_chat_message_id=media_group_msgs[i].message_id,
                        created_at=datetime.now(),
                        is_from_group=forum_status.from_group,  # 根据话题来源设置
                        source_group_id=forum_status.source_group_id,  # 记录群组ID
                        source_group_name=forum_status.source_group_name  # 记录群组名称
                    )
                    db.add(message_map)
            
            db.commit()
            logger.info(f"管理员消息已转发: {topic_id} -> {user_id}")
            
            # 自动将该用户的对应来源的未读消息标记为已读
            try:
                # 判断当前消息的来源类型
                is_from_group = forum_status.from_group
                source_group_id = forum_status.source_group_id
                
                # 根据来源类型查找对应的未读消息
                if is_from_group:
                    # 如果是群组消息，只标记来自相同群组的未读消息为已读
                    unread_messages = db.query(MessageMap).filter(
                        MessageMap.user_telegram_id == user_id,
                        MessageMap.is_unread_topic == True,
                        MessageMap.is_from_group == True,
                        MessageMap.source_group_id == source_group_id
                    ).all()
                else:
                    # 如果是私聊消息，只标记私聊的未读消息为已读
                    unread_messages = db.query(MessageMap).filter(
                        MessageMap.user_telegram_id == user_id,
                        MessageMap.is_unread_topic == True,
                        MessageMap.is_from_group == False
                    ).all()
                
                if unread_messages:
                    # 标记所有未读消息为已读
                    now = datetime.now()
                    for unread_msg in unread_messages:
                        unread_msg.is_unread_topic = False
                        unread_msg.handled_by_user_id = context.bot.id  # 使用bot ID作为处理人
                        unread_msg.handled_time = now
                        
                        # 尝试删除未读话题中的消息
                        if unread_msg.unread_topic_message_id:
                            try:
                                await context.bot.delete_message(
                                    chat_id=telegram_config.admin_group_id,
                                    message_id=unread_msg.unread_topic_message_id
                                )
                                logger.info(f"已删除未读话题中的消息: {unread_msg.unread_topic_message_id}")
                            except Exception as del_error:
                                logger.error(f"删除未读话题消息时出错: {str(del_error)}")
                    
                    # 提交更改
                    db.commit()
                    source_type = "群组" if is_from_group else "私聊"
                    source_info = f" ({forum_status.source_group_name})" if is_from_group and forum_status.source_group_name else ""
                    logger.info(f"用户 {user_id} 回复了管理员消息，已自动将{source_type}{source_info}未读消息({len(unread_messages)}条)标记为已读")
            except Exception as e:
                logger.error(f"自动标记用户未读消息时出错: {str(e)}")
        
        except Exception as e:
            logger.error(f"发送媒体组到用户时出错: {str(e)}")
            # 发送简单的文本消息作为备用
            await context.bot.send_message(
                chat_id=user_id,
                text="收到媒体消息，但由于技术原因无法显示。请联系客服获取更多信息。"
            )
                
    except Exception as e:
        logger.error(f"处理媒体组发送到用户时出错: {str(e)}")

async def forwarding_message_u2a(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理用户发送的消息并转发到管理群组"""
    try:
        # 忽略话题创建消息
        if hasattr(update.message, 'forum_topic_created') and update.message.forum_topic_created:
            logger.debug(f"忽略用户发送的话题创建消息: {update.message.message_id}")
            return
            
        # 检查用户是否被禁止
        user = update.effective_user
        db = next(get_db())
        if await check_user_ban_status(db, user.id):
            await update.message.reply_text("您已被禁止使用客服系统，如有疑问请联系管理员。")
            return
            
        # 检查用户回复的消息是否是管理员发送的消息（如果这是一条回复消息）
        is_reply_to_admin = False
        if update.message.reply_to_message:
            reply_msg = update.message.reply_to_message
            # 查询这条消息是否是管理员发送的
            admin_message_map = db.query(MessageMap).filter(
                MessageMap.user_telegram_id == user.id,
                MessageMap.user_chat_message_id == reply_msg.message_id
            ).first()
            
            if admin_message_map:
                is_reply_to_admin = True
                
                # 如果用户回复的是管理员的消息，标记对应来源的未读消息为已读
                try:
                    # 确定消息来源（私聊/群组）
                    is_from_group = admin_message_map.is_from_group
                    source_group_id = admin_message_map.source_group_id
                    
                    # 根据来源类型查找对应的未读消息
                    if is_from_group:
                        # 如果是群组消息，只标记来自相同群组的未读消息为已读
                        unread_messages = db.query(MessageMap).filter(
                            MessageMap.user_telegram_id == user.id,
                            MessageMap.is_unread_topic == True,
                            MessageMap.is_from_group == True,
                            MessageMap.source_group_id == source_group_id
                        ).all()
                    else:
                        # 如果是私聊消息，只标记私聊的未读消息为已读
                        unread_messages = db.query(MessageMap).filter(
                            MessageMap.user_telegram_id == user.id,
                            MessageMap.is_unread_topic == True,
                            MessageMap.is_from_group == False
                        ).all()
                    
                    if unread_messages:
                        # 标记所有未读消息为已读
                        now = datetime.now()
                        for unread_msg in unread_messages:
                            unread_msg.is_unread_topic = False
                            unread_msg.handled_by_user_id = context.bot.id  # 使用bot ID作为处理人
                            unread_msg.handled_time = now
                        
                            # 尝试删除未读话题中的消息
                            if unread_msg.unread_topic_message_id:
                                try:
                                    await context.bot.delete_message(
                                        chat_id=telegram_config.admin_group_id,
                                        message_id=unread_msg.unread_topic_message_id
                                    )
                                    logger.info(f"已删除未读话题中的消息: {unread_msg.unread_topic_message_id}")
                                except Exception as del_error:
                                    logger.error(f"删除未读话题消息时出错: {str(del_error)}")
                    
                        # 提交更改
                        db.commit()
                        source_type = "群组" if is_from_group else "私聊"
                        source_info = f" ({admin_message_map.source_group_name})" if is_from_group and admin_message_map.source_group_name else ""
                        logger.info(f"用户 {user.id} 回复了管理员消息，已自动将{source_type}{source_info}未读消息({len(unread_messages)}条)标记为已读")
                except Exception as e:
                    logger.error(f"自动标记用户未读消息时出错: {str(e)}")

        # 处理媒体组消息
        if update.message.media_group_id:
            await handle_media_group(update, context, forward_message_to_admin)
            return
            
        # 转发普通消息
        await forward_message_to_admin(update, context)
    except Exception as e:
        logger.error(f"转发用户消息时出错: {str(e)}")
        await update.message.reply_text("消息发送失败，请稍后重试。")

async def forwarding_message_a2u(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理管理员在群组中回复的消息并转发给用户"""
    try:
        # 检查消息是否在话题中发送
        if not update.message.is_topic_message:
            return
            
        # 忽略话题创建消息
        if hasattr(update.message, 'forum_topic_created') and update.message.forum_topic_created:
            logger.debug(f"忽略管理员发送的话题创建消息: {update.message.message_id}")
            return

        # 获取话题ID
        topic_id = update.message.message_thread_id
            
        # 查询用户ID和话题信息
        db = next(get_db())
        forum_status = db.query(FormnStatus).filter(FormnStatus.topic_id == topic_id).first()
        
        if not forum_status:
            logger.warning(f"找不到话题 {topic_id} 对应的用户")
            return
        
        # 如果是群组话题，不再跳过，而是使用group_handlers中的实现
        if forum_status.from_group and forum_status.source_group_id:
            # 引入group_handlers中的send_admin_reply_to_group_topic函数
            from app.telegram.group_handlers import forward_message_to_group
            
            # 调用群组话题回复处理函数
            await forward_message_to_group(update, context, forum_status)
            return

        # 处理媒体组消息
        if update.message.media_group_id:
            await handle_media_group(update, context, forward_message_to_user)
            return
            
        # 转发普通消息
        await forward_message_to_user(update, context)
        
        # 自动将该用户的对应来源的未读消息标记为已读
        try:
            # 获取用户ID
            user_id = forum_status.user_id
            
            # 判断当前消息的来源类型
            is_from_group = forum_status.from_group
            source_group_id = forum_status.source_group_id
                
            # 根据来源类型查找对应的未读消息
            if is_from_group:
                # 如果是群组消息，只标记来自相同群组的未读消息为已读
                unread_messages = db.query(MessageMap).filter(
                    MessageMap.user_telegram_id == user_id,
                    MessageMap.is_unread_topic == True,
                    MessageMap.is_from_group == True,
                    MessageMap.source_group_id == source_group_id
                ).all()
            else:
                # 如果是私聊消息，只标记私聊的未读消息为已读
                unread_messages = db.query(MessageMap).filter(
                    MessageMap.user_telegram_id == user_id,
                    MessageMap.is_unread_topic == True,
                    MessageMap.is_from_group == False
                ).all()
                
            if unread_messages:
                # 标记所有未读消息为已读
                now = datetime.now()
                for unread_msg in unread_messages:
                    unread_msg.is_unread_topic = False
                    unread_msg.handled_by_user_id = context.bot.id  # 使用bot ID作为处理人
                    unread_msg.handled_time = now
                    
                    # 尝试删除未读话题中的消息
                    if unread_msg.unread_topic_message_id:
                        try:
                            await context.bot.delete_message(
                                chat_id=telegram_config.admin_group_id,
                                message_id=unread_msg.unread_topic_message_id
                            )
                            logger.info(f"已删除未读话题中的消息: {unread_msg.unread_topic_message_id}")
                        except Exception as del_error:
                            logger.error(f"删除未读话题消息时出错: {str(del_error)}")
                    
                # 提交所有更改
                db.commit()
                source_type = "群组" if is_from_group else "私聊"
                source_info = f" ({forum_status.source_group_name})" if is_from_group and forum_status.source_group_name else ""
                logger.info(f"已自动将用户 {user_id} 的{source_type}{source_info}未读消息({len(unread_messages)}条)标记为已读")
        except Exception as e:
            logger.error(f"自动标记用户未读消息时出错: {str(e)}")
    except Exception as e:
        logger.error(f"转发管理员消息时出错: {str(e)}")
        await update.message.reply_text("消息转发失败，请稍后重试。") 