"""
处理Telegram群组中的消息
"""
import logging
from datetime import datetime
from typing import Optional, List

from telegram import Update, User, Message, Chat, ForumTopic, InputMediaPhoto, InputMediaVideo, InputMediaDocument
from telegram.ext import ContextTypes
from telegram.error import BadRequest

from app.config.telegram_config import telegram_config
from app.database.database import get_db
from app.models.user import User as UserModel
from app.models.message_map import MessageMap
from app.models.media_group_message import MediaGroupMessage
from app.models.formn_status import FormnStatus
from app.telegram.utils import (
    check_user_ban_status,
    get_user_by_id,
    create_or_get_user_topic,
    get_system_topic,
    UNREAD_TOPIC_NAME,
    retry_with_backoff,
    send_to_unread_topic,
    MEDIA_GROUP_DELAY
)

# 设置日志
logger = logging.getLogger(__name__)

async def handle_group_mention(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理群组中@机器人的消息"""
    try:
        message = update.message
        user = update.effective_user
        chat = update.effective_chat
        
        # 获取机器人信息
        bot_me = await context.bot.get_me()
        bot_username = bot_me.username
        
        # 检查消息文本或标题是否包含@机器人
        text = message.text or message.caption or ""
        is_mentioned = f"@{bot_username}" in text
        
        # 处理媒体组消息 - 先保存所有媒体组消息
        if message.media_group_id:
            # 保存媒体组消息到数据库
            db = next(get_db())
            media_group_msg = MediaGroupMessage(
                media_group_id=message.media_group_id,
                message_id=message.message_id,
                chat_id=message.chat.id,
                caption=message.caption,
                created_at=datetime.now()
            )
            db.add(media_group_msg)
            db.commit()
            logger.debug(f"已保存群组媒体组消息: ID={message.message_id}, 组ID={message.media_group_id}")
            
            # 检查该媒体组是否已经有消息@了机器人
            if not is_mentioned:
                # 查询数据库，检查同一媒体组中是否有其他消息@了机器人
                has_mention = db.query(MediaGroupMessage).filter(
                    MediaGroupMessage.media_group_id == message.media_group_id,
                    MediaGroupMessage.chat_id == message.chat.id,
                    MediaGroupMessage.caption.contains(f"@{bot_username}")
                ).first()
                
                # 如果没有消息@机器人，仅保存数据不做其他处理
                if not has_mention:
                    return
                
                # 有其他消息@了机器人，继续处理
                logger.debug(f"媒体组 {message.media_group_id} 中有消息@了机器人，处理当前消息")
            
        # 如果不是媒体组消息且没有@机器人，不处理
        elif not is_mentioned:
            return
        
        logger.info(f"收到群组 {chat.id} 中用户 {user.id} (@{user.username or user.first_name}) 的@消息")
        
        # 检查用户是否被禁止
        db = next(get_db())
        if await check_user_ban_status(db, user.id):
            await message.reply_text("您已被禁止使用客服系统，如有疑问请联系管理员。")
            return
            
        # 记录群组信息到用户数据中
        user_model = await get_user_by_id(db, user.id, create_if_not_exists=True)
        if user_model:
            user_model.last_group_id = chat.id
            user_model.last_group_name = chat.title
            db.commit()
        
        # 获取或创建用户的话题
        try:
            topic = await create_or_get_user_topic(
                context.bot, 
                user, 
                from_group=True, 
                source_group_id=chat.id, 
                source_group_name=chat.title if hasattr(chat, "title") else f"群组ID:{chat.id}"
            )
            if not topic:
                await message.reply_text("消息处理失败，请稍后重试。")
                return
        except BadRequest as e:
            # 检查是否是话题不存在错误
            error_msg = str(e).lower()
            if "message thread not found" in error_msg or "chat not found" in error_msg:
                logger.warning(f"话题不存在，尝试重新创建")
                # 删除数据库中的旧记录
                forum_status = db.query(FormnStatus).filter(
                    FormnStatus.user_id == user.id,
                    FormnStatus.from_group == True,
                    FormnStatus.source_group_id == chat.id
                ).first()
                
                if forum_status:
                    db.delete(forum_status)
                    db.commit()
                    logger.info(f"已删除旧的话题记录: {forum_status.topic_id}")
                
                # 重新创建话题
                topic = await create_or_get_user_topic(
                    context.bot, 
                    user, 
                    from_group=True, 
                    source_group_id=chat.id, 
                    source_group_name=chat.title if hasattr(chat, "title") else f"群组ID:{chat.id}"
                )
                if not topic:
                    await message.reply_text("消息处理失败，请稍后重试。")
                    return
                logger.info(f"已为用户 {user.id} 重新创建话题: {topic.message_thread_id}")
            else:
                # 其他API错误
                logger.error(f"创建话题时出错: {str(e)}")
                await message.reply_text("消息处理失败，请稍后重试。")
                return
        
        # 处理媒体组消息
        if message.media_group_id:
            # 检查job_queue是否可用
            if hasattr(context, 'job_queue') and context.job_queue:
                # 创建job名称
                job_name = f"group_media_{message.media_group_id}_{user.id}_{chat.id}"
                
                # 检查是否已经有相同ID的媒体组任务
                jobs = context.job_queue.get_jobs_by_name(job_name)
                if jobs:
                    logger.debug(f"群组媒体组 {message.media_group_id} 已有发送任务，添加新消息")
                else:
                    # 创建定时任务，延迟发送媒体组
                    context.job_queue.run_once(
                        send_group_media_to_admin,
                        MEDIA_GROUP_DELAY,
                        data={
                            "media_group_id": message.media_group_id,
                            "user_id": user.id,
                            "chat_id": chat.id,
                            "topic_id": topic.message_thread_id
                        },
                        name=job_name
                    )
                    logger.debug(f"为群组媒体组 {message.media_group_id} 创建发送任务，将在 {MEDIA_GROUP_DELAY} 秒后发送")
                return  # 媒体组消息已经处理，直接返回
            else:
                logger.warning("JobQueue未配置，无法处理媒体组消息。请安装python-telegram-bot[job-queue]")
                # 继续处理单条消息
        
        # 转发消息到管理群组
        admin_message = None
        
        try:
            # 获取管理员群组的Chat对象
            admin_chat = await context.bot.get_chat(telegram_config.admin_group_id)
            
            # 使用send_copy简化消息发送
            admin_message = await retry_with_backoff(
                admin_chat.send_copy,
                from_chat_id=message.chat_id,
                message_id=message.message_id,
                message_thread_id=topic.message_thread_id
            )
            
        except BadRequest as e:
            # 检查是否是话题不存在错误
            error_msg = str(e).lower()
            if "message thread not found" in error_msg or "chat not found" in error_msg:
                logger.warning(f"话题 {topic.message_thread_id} 不存在，尝试重新创建")
                
                # 删除数据库中的旧记录
                forum_status = db.query(FormnStatus).filter(
                    FormnStatus.topic_id == topic.message_thread_id
                ).first()
                
                if forum_status:
                    db.delete(forum_status)
                    db.commit()
                    logger.info(f"已删除旧的话题记录: {topic.message_thread_id}")
                
                # 重新创建话题
                new_topic = await create_or_get_user_topic(
                    context.bot, 
                    user, 
                    from_group=True, 
                    source_group_id=chat.id,
                    source_group_name=forum_status.source_group_name if forum_status else None
                )
                
                if not new_topic:
                    await message.reply_text("消息处理失败，请稍后重试。")
                    return
                    
                logger.info(f"已为用户 {user.id} 重新创建话题: {new_topic.message_thread_id}")
                
                # 使用新话题ID重试发送消息
                admin_messages = await admin_chat.send_copies(
                    from_chat_id=chat.id,
                    message_ids=message.message_id,
                    message_thread_id=new_topic.message_thread_id
                )
                
                # 重新查询forum_status，使用新创建的话题
                forum_status = db.query(FormnStatus).filter(
                    FormnStatus.topic_id == new_topic.message_thread_id
                ).first()
                
                # 保存消息映射
                if admin_messages:
                    try:
                        message_map = MessageMap(
                            user_telegram_id=user.id,
                            user_chat_message_id=message.message_id,
                            group_chat_message_id=admin_messages[0].message_id,
                            created_at=datetime.now(),
                            is_from_group=True,  # 标记为群组消息
                            source_group_id=chat.id,  # 记录群组ID
                            source_group_name=chat.title if hasattr(chat, "title") else f"群组ID:{chat.id}"  # 记录群组名称
                        )
                        db.add(message_map)
                        db.commit()
                        
                        logger.info(f"群组消息已转发到话题: {user.id} -> {topic.message_thread_id}")
                        
                        # 获取未读消息话题
                        unread_topic = await get_system_topic(context.bot, UNREAD_TOPIC_NAME)
                        
                        # 转发到未读话题，无需提前检查，让send_to_unread_topic函数自己判断是否需要发送
                        if unread_topic and admin_messages:
                            # 创建一个话题对象传递给send_to_unread_topic
                            forum_topic = ForumTopic(
                                message_thread_id=topic.message_thread_id,
                                name="",
                                icon_color=0
                            )
                            # 传递群组媒体消息到未读话题
                            await send_to_unread_topic(context, user, None, admin_messages[0], forum_topic, unread_topic)
                    except Exception as e:
                        logger.error(f"保存消息映射或处理未读消息时出错: {str(e)}")
            else:
                # 其他API错误
                logger.error(f"转发群组消息到管理员时出错: {str(e)}")
                await message.reply_text("消息处理失败，请稍后重试。")
                return
        except Exception as e:
            logger.error(f"转发群组消息到管理员时出错: {str(e)}")
            await message.reply_text("消息处理失败，请稍后重试。")
            return
            
        # 保存消息映射
        if admin_message:
            try:
                message_map = MessageMap(
                    user_telegram_id=user.id,
                    user_chat_message_id=admin_message.message_id,
                    group_chat_message_id=message.message_id,
                    created_at=datetime.now(),
                    is_from_group=True,  # 标记为群组消息
                    source_group_id=chat.id,  # 记录群组ID
                    source_group_name=chat.title if hasattr(chat, "title") else f"群组ID:{chat.id}"  # 记录群组名称
                )
                db.add(message_map)
                db.commit()
                
                logger.info(f"群组消息已转发到话题: {user.id} -> {topic.message_thread_id}")
                
                # 获取未读消息话题
                unread_topic = await get_system_topic(context.bot, UNREAD_TOPIC_NAME)
                
                # 转发到未读话题，无需提前检查，让send_to_unread_topic函数自己判断是否需要发送
                if unread_topic and admin_message:
                    # 创建一个话题对象传递给send_to_unread_topic
                    forum_topic = ForumTopic(
                        message_thread_id=topic.message_thread_id,
                        name="",
                        icon_color=0
                    )
                    # 传递群组媒体消息到未读话题
                    await send_to_unread_topic(context, user, None, admin_message, forum_topic, unread_topic)
            except Exception as e:
                logger.error(f"保存消息映射或处理未读消息时出错: {str(e)}")
        
    except Exception as e:
        logger.error(f"处理群组@消息时出错: {str(e)}")
        if update.message:
            await update.message.reply_text("消息处理失败，请稍后重试。")

async def send_group_media_to_admin(context: ContextTypes.DEFAULT_TYPE) -> None:
    """将群组媒体组消息发送到管理员群组"""
    job = context.job
    data = job.data
    media_group_id = data["media_group_id"]
    user_id = data["user_id"]
    chat_id = data["chat_id"]
    topic_id = data["topic_id"]
    
    try:
        logger.info(f"开始处理群组媒体组 {media_group_id}，发送到管理员群组")
        
        # 从数据库获取媒体组消息
        db = next(get_db())
        media_group_msgs = db.query(MediaGroupMessage).filter(
            MediaGroupMessage.media_group_id == media_group_id,
            MediaGroupMessage.chat_id == chat_id
        ).all()
        
        if not media_group_msgs:
            logger.warning(f"未找到群组媒体组 {media_group_id} 的消息")
            return
            
        # 获取用户信息
        user = await context.bot.get_chat(user_id)
        
        # 排序消息（根据消息ID）
        media_group_msgs.sort(key=lambda m: m.message_id)
        message_ids = [msg.message_id for msg in media_group_msgs]
        
        # 获取群组信息
        try:
            group_chat = await context.bot.get_chat(chat_id)
            group_name = group_chat.title if hasattr(group_chat, "title") else f"群组ID:{chat_id}"
        except Exception as e:
            logger.error(f"获取群组信息失败: {str(e)}")
            group_name = f"群组ID:{chat_id}"
        
        # 查找话题信息
        forum_status = db.query(FormnStatus).filter(
            FormnStatus.topic_id == topic_id
        ).first()
        
        # 获取管理员群组的Chat对象
        admin_chat = await context.bot.get_chat(telegram_config.admin_group_id)
        
        try:
            # 使用send_copies方法批量转发消息
            admin_messages = await admin_chat.send_copies(
                from_chat_id=chat_id,
                message_ids=message_ids,
                message_thread_id=topic_id
            )
            
            # 保存消息映射
            try:
                for i, admin_message in enumerate(admin_messages):
                    if i < len(media_group_msgs):
                        message_map = MessageMap(
                            user_telegram_id=user_id,
                            user_chat_message_id=media_group_msgs[i].message_id,
                            group_chat_message_id=admin_message.message_id,
                            created_at=datetime.now(),
                            is_from_group=True,  # 标记为群组消息
                            source_group_id=chat_id,  # 记录群组ID
                            source_group_name=group_name  # 记录群组名称
                        )
                        db.add(message_map)
                
                db.commit()
                logger.info(f"用户 {user_id} 的群组媒体组已转发到话题 {topic_id}")
                
                # 获取未读消息话题
                unread_topic = await get_system_topic(context.bot, UNREAD_TOPIC_NAME)
                
                # 转发到未读话题，无需提前检查，让send_to_unread_topic函数自己判断是否需要发送
                if unread_topic and admin_messages:
                    # 转发第一条消息到未读话题
                    first_admin_msg = admin_messages[0]
                    # 创建一个话题对象传递给send_to_unread_topic
                    forum_topic = ForumTopic(
                        message_thread_id=topic_id,
                        name="",
                        icon_color=0
                    )
                    # 传递群组媒体消息到未读话题
                    await send_to_unread_topic(context, user, None, first_admin_msg, forum_topic, unread_topic)
            except Exception as e:
                logger.error(f"保存消息映射或处理未读消息时出错: {str(e)}")
        
        except BadRequest as e:
            # 检查是否是话题不存在错误
            error_msg = str(e).lower()
            if "message thread not found" in error_msg or "chat not found" in error_msg:
                logger.warning(f"话题 {topic_id} 不存在，尝试重新创建")
                
                # 删除数据库中的旧记录
                if forum_status:
                    db.delete(forum_status)
                    db.commit()
                    logger.info(f"已删除旧的话题记录: {topic_id}")
                
                # 重新创建话题
                new_topic = await create_or_get_user_topic(
                    context.bot, 
                    user, 
                    from_group=True, 
                    source_group_id=chat_id,
                    source_group_name=group_name
                )
                
                if not new_topic:
                    logger.error(f"重新创建话题失败")
                    return
                    
                logger.info(f"已为用户 {user_id} 重新创建话题: {new_topic.message_thread_id}")
                
                # 使用新话题ID重试发送消息
                admin_messages = await admin_chat.send_copies(
                    from_chat_id=chat_id,
                    message_ids=message_ids,
                    message_thread_id=new_topic.message_thread_id
                )
                
                # 保存消息映射
                for i, admin_message in enumerate(admin_messages):
                    if i < len(media_group_msgs):
                        message_map = MessageMap(
                            user_telegram_id=user_id,
                            user_chat_message_id=media_group_msgs[i].message_id,
                            group_chat_message_id=admin_message.message_id,
                            created_at=datetime.now(),
                            is_from_group=True,  # 标记为群组消息
                            source_group_id=chat_id,  # 记录群组ID
                            source_group_name=group_name  # 记录群组名称
                        )
                        db.add(message_map)
                
                db.commit()
                logger.info(f"用户 {user_id} 的群组媒体组已转发到新话题 {new_topic.message_thread_id}")
                
                # 获取未读消息话题
                unread_topic = await get_system_topic(context.bot, UNREAD_TOPIC_NAME)
                
                # 转发到未读话题，无需提前检查，让send_to_unread_topic函数自己判断是否需要发送
                if unread_topic and admin_messages:
                    # 转发第一条消息到未读话题
                    first_admin_msg = admin_messages[0]
                    # 创建一个话题对象传递给send_to_unread_topic
                    forum_topic = ForumTopic(
                        message_thread_id=new_topic.message_thread_id,
                        name="",
                        icon_color=0
                    )
                    # 传递群组媒体消息到未读话题
                    await send_to_unread_topic(context, user, None, first_admin_msg, forum_topic, unread_topic)
            else:
                # 其他API错误
                logger.error(f"发送媒体组到管理员群组失败: {str(e)}")
        except Exception as e:
            logger.error(f"发送媒体组到管理员群组失败: {str(e)}")
                
    except Exception as e:
        logger.error(f"处理群组媒体组发送到管理员时出错: {str(e)}")

async def forward_message_to_group(update: Update, context: ContextTypes.DEFAULT_TYPE, forum_status: FormnStatus) -> None:
    """将管理员在话题中的回复转发回原始群组
    
    Args:
        update: Telegram更新对象
        context: 回调上下文
        forum_status: 话题状态对象，包含群组信息
    """
    try:
        message = update.message
        source_group_id = forum_status.source_group_id
        user_id = forum_status.user_id
        
        if not source_group_id:
            logger.error(f"话题 {forum_status.topic_id} 的来源群组ID为空")
            await message.reply_text("找不到原始群组信息，无法转发回群组")
            return
        
        # 检查是否是媒体组消息
        if message.media_group_id:
            logger.info(f"检测到媒体组消息，转交给send_admin_media_to_group处理")
            # 保存媒体组消息到数据库
            db = next(get_db())
            media_group_msg = MediaGroupMessage(
                media_group_id=message.media_group_id,
                message_id=message.message_id,
                chat_id=message.chat.id,
                caption=message.caption,
                created_at=datetime.now()
            )
            db.add(media_group_msg)
            db.commit()
            
            # 检查job_queue是否可用
            if hasattr(context, 'job_queue') and context.job_queue:
                # 创建job名称
                job_name = f"admin_media_{message.media_group_id}_{update.effective_user.id}_{source_group_id}"
                
                # 检查是否已经有相同ID的媒体组任务
                jobs = context.job_queue.get_jobs_by_name(job_name)
                if jobs:
                    logger.debug(f"管理员媒体组 {message.media_group_id} 已有发送任务，添加新消息")
                else:
                    # 创建定时任务，延迟发送媒体组
                    context.job_queue.run_once(
                        send_admin_media_to_group,
                        MEDIA_GROUP_DELAY,
                        data={
                            "media_group_id": message.media_group_id,
                            "admin_id": update.effective_user.id,
                            "chat_id": message.chat.id,
                            "admin_name": update.effective_user.full_name,
                            "topic_id": forum_status.topic_id
                        },
                        name=job_name
                    )
                    logger.debug(f"为管理员媒体组 {message.media_group_id} 创建发送任务，将在 {MEDIA_GROUP_DELAY} 秒后发送")
                return  # 媒体组消息已经处理，直接返回
            else:
                logger.warning("JobQueue未配置，无法处理媒体组消息")
                # 继续处理单条消息
            
        # 查找原始消息ID以便回复
        db = next(get_db())
        # 检查是否是回复消息
        original_msg_id = None
        if message.reply_to_message:
            # 获取被回复消息在管理群组中的ID
            reply_group_msg_id = message.reply_to_message.message_id
            
            # 查找对应的原始群组消息ID
            message_map = db.query(MessageMap).filter(
                MessageMap.group_chat_message_id == reply_group_msg_id,
                MessageMap.user_telegram_id == user_id
            ).first()
            
            if message_map:
                original_msg_id = message_map.user_chat_message_id
                logger.debug(f"找到原始群组消息ID: {original_msg_id}")
        
        # 获取用户信息以便@
        try:
            user = await context.bot.get_chat(user_id)
            # 准备@用户的文本
            user_mention = f"@{user.username}" if user.username else user.first_name
            # 添加@用户前缀到消息文本或caption
            if message.text:
                message_text = f"{user_mention} {message.text}"
            else:
                message_text = user_mention
                
            caption_text = None
            if message.caption:
                caption_text = f"{user_mention} {message.caption}"
        except Exception as e:
            logger.error(f"获取用户信息失败: {str(e)}")
            message_text = message.text or ""
            caption_text = message.caption
        
        # 发送消息到群组
        group_message = None
        try:
            # 发送到群组，使用原始消息ID进行回复
            if message.photo:
                # 发送最大尺寸的照片
                photo = message.photo[-1]
                group_message = await context.bot.send_photo(
                    chat_id=source_group_id,
                    photo=photo.file_id,
                    caption=caption_text,
                    reply_to_message_id=original_msg_id
                )
            elif message.video:
                group_message = await context.bot.send_video(
                    chat_id=source_group_id,
                    video=message.video.file_id,
                    caption=caption_text,
                    reply_to_message_id=original_msg_id
                )
            elif message.document:
                group_message = await context.bot.send_document(
                    chat_id=source_group_id,
                    document=message.document.file_id,
                    caption=caption_text,
                    reply_to_message_id=original_msg_id
                )
            elif message.voice:
                group_message = await context.bot.send_voice(
                    chat_id=source_group_id,
                    voice=message.voice.file_id,
                    caption=caption_text,
                    reply_to_message_id=original_msg_id
                )
            elif message.audio:
                group_message = await context.bot.send_audio(
                    chat_id=source_group_id,
                    audio=message.audio.file_id,
                    caption=caption_text,
                    reply_to_message_id=original_msg_id
                )
            elif message.text:
                group_message = await context.bot.send_message(
                    chat_id=source_group_id,
                    text=message_text,
                    reply_to_message_id=original_msg_id
                )
            else:
                await message.reply_text("不支持的消息类型，无法转发到群组")
                return
                
        except Exception as e:
            logger.error(f"发送消息到群组 {source_group_id} 失败: {str(e)}")
            await message.reply_text(f"发送消息到群组失败: {str(e)}")
            return
            
        # 保存消息映射
        if group_message:
            message_map = MessageMap(
                user_telegram_id=user_id,
                user_chat_message_id=group_message.message_id,
                group_chat_message_id=message.message_id,
                created_at=datetime.now(),
                is_from_group=True,  # 标记为群组消息
                source_group_id=source_group_id,  # 记录群组ID
                source_group_name=forum_status.source_group_name if forum_status and forum_status.source_group_name else f"群组ID:{source_group_id}"  # 记录群组名称
            )
            db.add(message_map)
            db.commit()
            
            # 自动将该用户的来自相同群组的未读消息标记为已读
            try:
                # 查找该用户在未读话题中来自相同群组的未读消息
                unread_messages = db.query(MessageMap).filter(
                    MessageMap.user_telegram_id == user_id,
                    MessageMap.is_unread_topic == True,
                    MessageMap.is_from_group == True,
                    MessageMap.source_group_id == source_group_id
                ).all()
                
                if unread_messages:
                    handler_user = update.effective_user
                    now = datetime.now()
                    
                    # 更新所有未读消息状态
                    for unread_msg in unread_messages:
                        unread_msg.is_unread_topic = False
                        unread_msg.handled_by_user_id = handler_user.id
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
                    group_info = f" ({forum_status.source_group_name})" if forum_status.source_group_name else f" (ID: {source_group_id})"
                    logger.info(f"已自动将用户 {user_id} 的群组{group_info}未读消息({len(unread_messages)}条)标记为已读")
            except Exception as e:
                logger.error(f"自动标记用户未读消息时出错: {str(e)}")
            
            logger.info(f"管理员消息已转发到群组: {forum_status.topic_id} -> {source_group_id}")
    except Exception as e:
        logger.error(f"转发消息到群组时出错: {str(e)}")
        if update and update.message:
            await update.message.reply_text(f"消息转发到群组失败: {str(e)}")


async def send_topic_media_to_group(context: ContextTypes.DEFAULT_TYPE, media_group_id: str, topic_id: int, forum_status: FormnStatus) -> None:
    """将话题中的媒体组消息发送到群组
    
    Args:
        context: 回调上下文
        media_group_id: 媒体组ID
        topic_id: 话题ID
        forum_status: 话题状态对象，包含群组信息
    """
    try:
        source_group_id = forum_status.source_group_id
        user_id = forum_status.user_id
        
        if not source_group_id:
            logger.error(f"话题 {topic_id} 的来源群组ID为空")
            return
            
        # 从数据库获取媒体组消息
        db = next(get_db())
        media_group_msgs = db.query(MediaGroupMessage).filter(
            MediaGroupMessage.media_group_id == media_group_id,
            MediaGroupMessage.chat_id == telegram_config.admin_group_id
        ).all()
        
        if not media_group_msgs:
            logger.warning(f"未找到媒体组 {media_group_id} 的消息")
            return
            
        # 排序消息（根据消息ID）
        media_group_msgs.sort(key=lambda m: m.message_id)
        message_ids = [msg.message_id for msg in media_group_msgs]
        
        # 获取用户信息以便@
        user_mention = ""
        try:
            user = await context.bot.get_chat(user_id)
            # 准备@用户的文本
            user_mention = f"@{user.username}" if user.username else user.first_name
        except Exception as e:
            logger.error(f"获取用户信息失败: {str(e)}")
            
        try:
            # 获取群组的Chat对象
            group_chat = await context.bot.get_chat(source_group_id)
            
            # 首先发送一条@用户的消息
            if user_mention:
                mention_msg = await context.bot.send_message(
                    chat_id=source_group_id,
                    text=f"{user_mention}"
                )
            
            # 使用send_copies方法批量转发消息
            group_messages = await group_chat.send_copies(
                from_chat_id=telegram_config.admin_group_id,
                message_ids=message_ids
            )
            
            # 保存消息映射
            for i, group_message in enumerate(group_messages):
                if i < len(media_group_msgs):
                    message_map = MessageMap(
                        user_telegram_id=user_id,
                        user_chat_message_id=group_message.message_id,
                        group_chat_message_id=media_group_msgs[i].message_id,
                        created_at=datetime.now(),
                        is_from_group=True,  # 标记为群组消息
                        source_group_id=source_group_id,  # 记录群组ID
                        source_group_name=forum_status.source_group_name if forum_status and forum_status.source_group_name else f"群组ID:{source_group_id}"  # 记录群组名称
                    )
                    db.add(message_map)
            
            db.commit()
            logger.info(f"管理员媒体组已转发到群组: {topic_id} -> {source_group_id}")
            
            # 自动将该用户的来自相同群组的未读消息标记为已读
            try:
                # 查找该用户在未读话题中来自相同群组的未读消息
                unread_messages = db.query(MessageMap).filter(
                    MessageMap.user_telegram_id == user_id,
                    MessageMap.is_unread_topic == True,
                    MessageMap.is_from_group == True,
                    MessageMap.source_group_id == source_group_id
                ).all()
                
                if unread_messages:
                    now = datetime.now()
                    
                    # 更新所有未读消息状态
                    for unread_msg in unread_messages:
                        unread_msg.is_unread_topic = False
                        if hasattr(context, 'user_data') and context.user_data:
                            admin_user = context.user_data.get('user')
                            if admin_user:
                                unread_msg.handled_by_user_id = admin_user.id
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
                    group_info = f" ({forum_status.source_group_name})" if forum_status.source_group_name else f" (ID: {source_group_id})"
                    logger.info(f"已自动将用户 {user_id} 的群组{group_info}未读消息({len(unread_messages)}条)标记为已读")
            except Exception as e:
                logger.error(f"自动标记用户未读消息时出错: {str(e)}")
            
            # 不再发送确认消息到管理群组
                
        except Exception as e:
            logger.error(f"发送媒体组到群组失败: {str(e)}")
            # 发送简单的文本消息作为备用
            try:
                await context.bot.send_message(
                    chat_id=source_group_id,
                    text="收到媒体消息，但由于技术原因无法显示。请联系客服获取更多信息。"
                )
                
                # 发送确认消息到管理群组
                group_name = "未知群组"
                if forum_status.source_group_name:
                    group_name = forum_status.source_group_name
                else:
                    group_name = f"群组(ID: {source_group_id})"

                if topic_id:
                    await context.bot.send_message(
                        chat_id=telegram_config.admin_group_id,
                        text=f"⚠️ 无法发送完整媒体组，已向 {group_name} 发送提示消息",
                        message_thread_id=topic_id
                    )
                logger.info(f"已发送媒体消息通知到群组 {source_group_id}")
            except Exception as notify_error:
                logger.error(f"发送备用通知消息失败: {str(notify_error)}")
            
    except Exception as e:
        logger.error(f"处理话题媒体组发送到群组时出错: {str(e)}")


async def send_admin_media_to_group(context: ContextTypes.DEFAULT_TYPE) -> None:
    """将管理员媒体组消息发送到群组"""
    job = context.job
    data = job.data
    media_group_id = data["media_group_id"]
    admin_id = data["admin_id"]
    chat_id = data["chat_id"]
    admin_name = data["admin_name"]
    topic_id = data.get("topic_id")  # 使用get方法，如果不存在返回None
    
    try:
        logger.info(f"开始处理管理员媒体组 {media_group_id}，发送到群组")
        
        # 从数据库获取媒体组消息
        db = next(get_db())
        media_group_msgs = db.query(MediaGroupMessage).filter(
            MediaGroupMessage.media_group_id == media_group_id,
            MediaGroupMessage.chat_id == chat_id
        ).all()
        
        if not media_group_msgs:
            logger.warning(f"未找到管理员媒体组 {media_group_id} 的消息")
            return
            
        # 排序消息（根据消息ID）
        media_group_msgs.sort(key=lambda m: m.message_id)
        message_ids = [msg.message_id for msg in media_group_msgs]
        
        # 查找用户信息 - 获取正在处理的话题信息
        try:
            # 直接使用job.data中的topic_id
            if topic_id:
                forum_status = db.query(FormnStatus).filter(
                    FormnStatus.topic_id == topic_id
                ).first()
            else:
                # 如果仍然获取不到话题ID，尝试使用群组ID查找最近更新的话题
                forum_status = db.query(FormnStatus).filter(
                    FormnStatus.source_group_id != None
                ).order_by(FormnStatus.updated_at.desc()).first()
                
            if not forum_status:
                logger.error(f"无法确定要发送到哪个群组，未找到相关话题信息")
                return
                
            user_id = forum_status.user_id
            source_group_id = forum_status.source_group_id
            
            if not source_group_id:
                logger.error(f"找不到目标群组ID")
                return
                
            logger.info(f"找到目标群组ID: {source_group_id}，用户ID: {user_id}")
            
            # 获取用户信息以便@
            user_mention = ""
            try:
                user = await context.bot.get_chat(user_id)
                # 准备@用户的文本
                user_mention = f"@{user.username}" if user.username else user.first_name
            except Exception as e:
                logger.error(f"获取用户信息失败: {str(e)}")
            
        except Exception as e:
            logger.error(f"获取话题信息失败: {str(e)}")
            # 如果无法获取话题信息，不应继续发送
            return
        
        try:
            # 获取源聊天对象和目标聊天对象
            source_chat = await context.bot.get_chat(chat_id)
            target_chat = await context.bot.get_chat(source_group_id)
            
            # 首先发送一条@用户的消息
            if user_mention:
                mention_msg = await context.bot.send_message(
                    chat_id=source_group_id,
                    text=f"{user_mention}"
                )
            
            # 使用copy_messages方法直接复制媒体组消息
            # 这个方法不需要先获取消息内容，直接通过消息ID复制
            group_messages = await source_chat.copy_messages(
                chat_id=source_group_id,
                message_ids=message_ids
            )
            
            # 保存消息映射
            for i, msg_id in enumerate(group_messages):
                if i < len(message_ids):
                    message_map = MessageMap(
                        user_telegram_id=user_id,
                        user_chat_message_id=msg_id.message_id,
                        group_chat_message_id=message_ids[i],
                        created_at=datetime.now(),
                        is_from_group=True,  # 标记为群组消息
                        source_group_id=source_group_id,  # 记录群组ID
                        source_group_name=forum_status.source_group_name if forum_status and forum_status.source_group_name else f"群组ID:{source_group_id}"  # 记录群组名称
                    )
                    db.add(message_map)
            
            db.commit()
            logger.info(f"管理员 {admin_id} 的媒体组已成功发送到群组 {source_group_id}")
            
            # 不再发送确认消息到管理员群组
            
            # 自动将该用户的来自相同群组的未读消息标记为已读
            try:
                # 查找该用户在未读话题中来自相同群组的未读消息
                unread_messages = db.query(MessageMap).filter(
                    MessageMap.user_telegram_id == user_id,
                    MessageMap.is_unread_topic == True,
                    MessageMap.is_from_group == True,
                    MessageMap.source_group_id == source_group_id
                ).all()
                
                if unread_messages:
                    now = datetime.now()
                    
                    # 更新所有未读消息状态
                    for unread_msg in unread_messages:
                        unread_msg.is_unread_topic = False
                        unread_msg.handled_by_user_id = admin_id
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
                    group_info = f" ({forum_status.source_group_name})" if forum_status.source_group_name else f" (ID: {source_group_id})"
                    logger.info(f"已自动将用户 {user_id} 的群组{group_info}未读消息({len(unread_messages)}条)标记为已读")
            except Exception as e:
                logger.error(f"自动标记用户未读消息时出错: {str(e)}")
            
        except Exception as e:
            logger.error(f"发送媒体组到群组失败: {str(e)}")
            # 发送备用消息
            try:
                await context.bot.send_message(
                    chat_id=source_group_id,
                    text="收到媒体消息，但由于技术原因无法显示。请联系客服获取更多信息。"
                )
                
                # 在管理员群组中发送确认消息
                group_name = "未知群组"
                if forum_status.source_group_name:
                    group_name = forum_status.source_group_name
                else:
                    group_name = f"群组(ID: {source_group_id})"

                if topic_id:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"⚠️ 无法发送完整媒体组，已向 {group_name} 发送提示消息",
                        message_thread_id=topic_id
                    )
                logger.info(f"已发送媒体消息通知到群组 {source_group_id}")
            except Exception as notify_error:
                logger.error(f"发送备用通知消息失败: {str(notify_error)}")
            
    except Exception as e:
        logger.error(f"处理管理员媒体组发送到群组时出错: {str(e)}") 