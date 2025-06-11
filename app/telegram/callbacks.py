"""
Telegram回调处理相关函数
"""
import logging
import random
import string
from typing import Dict, Optional, Tuple
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    User
)
from telegram.ext import ContextTypes

from app.config.telegram_config import telegram_config
from app.database.database import get_db
from app.models.message_map import MessageMap
from app.models.formn_status import FormnStatus
from app.models.user import User as UserModel

# 设置日志
logger = logging.getLogger(__name__)

# 系统话题名称常量
UNREAD_TOPIC_NAME = "未读消息"
SPAM_TOPIC_NAME = "垃圾消息"

async def generate_verification_code() -> Tuple[str, str]:
    """生成验证码"""
    # 生成随机验证码
    code = ''.join(random.choices(string.digits, k=4))
    # 生成随机标识符
    identifier = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    return code, identifier

async def create_verification_keyboard(code: str, identifier: str) -> InlineKeyboardMarkup:
    """创建验证码键盘"""
    # 创建正确答案和干扰项
    correct_code = code
    options = [correct_code]
    
    # 添加3个干扰项
    while len(options) < 4:
        fake_code = ''.join(random.choices(string.digits, k=4))
        if fake_code not in options:
            options.append(fake_code)
            
    # 打乱选项顺序
    random.shuffle(options)
    
    # 创建键盘
    keyboard = []
    row = []
    for option in options:
        callback_data = f"vcode_{identifier}_{option}"
        row.append(InlineKeyboardButton(option, callback_data=callback_data))
        
        if len(row) == 2:
            keyboard.append(row)
            row = []
            
    if row:
        keyboard.append(row)
        
    return InlineKeyboardMarkup(keyboard)

async def process_callback_vcode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理验证码回调查询"""
    query = update.callback_query
    data = query.data
    
    # 解析回调数据
    parts = data.split("_")
    if len(parts) != 3:
        await query.answer("无效的验证码")
        return
        
    _, identifier, code = parts
    
    # 从上下文中获取验证信息
    verification_data = context.user_data.get("verification", {})
    expected_code = verification_data.get("code")
    expected_identifier = verification_data.get("identifier")
    
    if not expected_code or not expected_identifier:
        await query.answer("验证已过期，请重新发起验证")
        return
        
    if identifier != expected_identifier:
        await query.answer("验证已过期，请重新发起验证")
        return
        
    # 检查验证码是否正确
    if code == expected_code:
        # 验证成功
        await query.answer("验证成功")
        await query.edit_message_text("验证通过，您现在可以使用客服系统了")
        
        # 清除验证数据
        if "verification" in context.user_data:
            del context.user_data["verification"]
            
        # 记录验证成功
        db = next(get_db())
        user = await get_user_by_id(db, update.effective_user.id, create_if_not_exists=True)
        if user:
            user.is_verified = True
            db.commit()
    else:
        # 验证失败
        await query.answer("验证失败，请重试")

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

async def process_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理回调查询"""
    try:
        query = update.callback_query
        data = query.data
        
        # 根据回调数据类型分发处理
        if data.startswith("vcode_"):
            await process_callback_vcode(update, context)
        elif data.startswith("read_"):
            # 处理标记已读回调
            if data.startswith("read_all_"):
                # 处理标记用户所有消息为已读
                await process_callback_read_all(update, context)
            else:
                # 处理标记单条消息为已读
                await process_callback_read(update, context)
        elif data.startswith("ban_"):
            # 处理封禁用户回调
            await process_callback_ban(update, context)
        elif data.startswith("spam_"):
            # 处理举报垃圾消息回调
            await process_callback_spam(update, context)
        else:
            await query.answer("未知的回调类型")
    except Exception as e:
        logger.error(f"处理回调查询时出错: {str(e)}")
        await update.callback_query.answer("处理失败，请重试")

async def process_callback_read_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理标记用户所有消息为已读的回调"""
    try:
        query = update.callback_query
        data = query.data
        user_id = int(data.split("_")[2])  # 格式: read_all_USER_ID
        
        # 获取数据库连接
        db = next(get_db())
        
        # 查找发起按钮操作的消息所在的话题
        forum_status = None
        if query.message and query.message.is_topic_message:
            topic_id = query.message.message_thread_id
            forum_status = db.query(FormnStatus).filter(
                FormnStatus.topic_id == topic_id
            ).first()
        
        # 根据话题来源决定要标记的消息
        if forum_status:
            is_from_group = forum_status.from_group
            source_group_id = forum_status.source_group_id
            
            # 根据来源类型查找对应的未读消息
            if is_from_group and source_group_id:
                # 如果是群组话题，只标记来自同一群组的未读消息
                unread_messages = db.query(MessageMap).filter(
                    MessageMap.user_telegram_id == user_id,
                    MessageMap.is_unread_topic == True,
                    MessageMap.is_from_group == True,
                    MessageMap.source_group_id == source_group_id
                ).all()
                source_desc = f"群组({forum_status.source_group_name or source_group_id})"
            else:
                # 如果是私聊话题，只标记私聊的未读消息
                unread_messages = db.query(MessageMap).filter(
                    MessageMap.user_telegram_id == user_id,
                    MessageMap.is_unread_topic == True,
                    MessageMap.is_from_group == False
                ).all()
                source_desc = "私聊"
        else:
            # 如果找不到话题信息，默认标记所有未读消息
            unread_messages = db.query(MessageMap).filter(
                MessageMap.user_telegram_id == user_id,
                MessageMap.is_unread_topic == True
            ).all()
            source_desc = "所有渠道"
        
        if not unread_messages:
            await query.answer("该用户没有未读消息")
            return
            
        # 更新所有未读消息状态
        handler_user = update.effective_user
        now = datetime.now()
        
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
                except Exception as del_error:
                    logger.error(f"删除未读话题消息时出错: {str(del_error)}")
        
        # 提交所有更改
        db.commit()
        
        # 更新按钮文本
        keyboard = [
            [
                InlineKeyboardButton("✅ 已标记为已读", callback_data="done"),
                InlineKeyboardButton("🚫 封禁用户", callback_data=f"ban_{user_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_reply_markup(reply_markup=reply_markup)
        await query.answer(f"已将用户 {user_id} 的{source_desc}未读消息({len(unread_messages)}条)标记为已读")
        logger.info(f"管理员 {handler_user.id} 已将用户 {user_id} 的{source_desc}未读消息({len(unread_messages)}条)标记为已读")
    except Exception as e:
        logger.error(f"处理标记所有已读回调时出错: {str(e)}")
        await update.callback_query.answer("处理失败，请重试")

async def process_callback_ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理封禁/解封用户的回调"""
    try:
        query = update.callback_query
        data = query.data
        user_id = int(data.split("_")[1])  # 格式: ban_USER_ID
        
        # 获取数据库连接
        db = next(get_db())
        
        # 查找用户
        from app.models.user import User
        user = db.query(User).filter(User.id == user_id).first()
        
        if not user:
            # 用户不存在，创建新记录并设置为封禁状态
            user = User(id=user_id, is_active=False)
            db.add(user)
            db.commit()
            await query.answer(f"已封禁用户 {user_id}")
            
            # 更新按钮文本 - 显示为"解除封禁"
            keyboard = [
                [
                    InlineKeyboardButton("✅ 标记为已读", callback_data=f"read_all_{user_id}"),
                    InlineKeyboardButton("✅ 解除封禁", callback_data=f"ban_{user_id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # 记录日志
            handler_user = update.effective_user
            logger.info(f"管理员 {handler_user.id} 已封禁用户 {user_id}")
        else:
            # 用户存在，切换封禁/解封状态
            if user.is_active:
                # 当前是活跃状态，执行封禁
                user.is_active = False
                db.commit()
                await query.answer(f"已封禁用户 {user_id}")
                
                # 更新按钮文本 - 显示为"解除封禁"
                keyboard = [
                    [
                        InlineKeyboardButton("✅ 标记为已读", callback_data=f"read_all_{user_id}"),
                        InlineKeyboardButton("✅ 解除封禁", callback_data=f"ban_{user_id}")
                    ]
                ]
                
                # 记录日志
                handler_user = update.effective_user
                logger.info(f"管理员 {handler_user.id} 已封禁用户 {user_id}")
            else:
                # 当前是封禁状态，执行解封
                user.is_active = True
                db.commit()
                await query.answer(f"已解封用户 {user_id}")
                
                # 更新按钮文本 - 显示为"封禁用户"
                keyboard = [
                    [
                        InlineKeyboardButton("✅ 标记为已读", callback_data=f"read_all_{user_id}"),
                        InlineKeyboardButton("🚫 封禁用户", callback_data=f"ban_{user_id}")
                    ]
                ]
                
                # 记录日志
                handler_user = update.effective_user
                logger.info(f"管理员 {handler_user.id} 已解封用户 {user_id}")
            
            reply_markup = InlineKeyboardMarkup(keyboard)
        
        # 更新消息的按钮
        await query.edit_message_reply_markup(reply_markup=reply_markup)
        
    except Exception as e:
        logger.error(f"处理封禁/解封用户回调时出错: {str(e)}")
        await update.callback_query.answer("处理失败，请重试")

async def process_callback_read(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理标记单条消息为已读的回调"""
    try:
        query = update.callback_query
        data = query.data
        message_id = int(data.split("_")[1])  # 格式: read_MESSAGE_ID
        
        # 获取数据库连接
        db = next(get_db())
        
        # 查找消息记录
        message_map = db.query(MessageMap).filter(
            MessageMap.group_chat_message_id == message_id
        ).first()
        
        if not message_map:
            logger.warning(f"未找到消息ID {message_id} 的记录")
            await query.answer(f"未找到消息记录，请重试")
            return
            
        logger.info(f"找到消息映射: 用户ID={message_map.user_telegram_id}")
        
        # 获取用户ID
        user_id = message_map.user_telegram_id
        
        # 确定消息来源（私聊/群组）
        is_from_group = message_map.is_from_group
        source_group_id = message_map.source_group_id
        source_group_name = message_map.source_group_name
        
        # 根据来源类型查找对应的未读消息
        if is_from_group and source_group_id:
            # 如果是群组消息，只标记来自相同群组的未读消息为已读
            unread_messages = db.query(MessageMap).filter(
                MessageMap.user_telegram_id == user_id,
                MessageMap.is_unread_topic == True,
                MessageMap.is_from_group == True,
                MessageMap.source_group_id == source_group_id
            ).all()
            source_desc = f"群组({source_group_name or source_group_id})"
        else:
            # 如果是私聊消息，只标记私聊的未读消息为已读
            unread_messages = db.query(MessageMap).filter(
                MessageMap.user_telegram_id == user_id,
                MessageMap.is_unread_topic == True,
                MessageMap.is_from_group == False
            ).all()
            source_desc = "私聊"
        
        # 获取管理群组ID
        admin_group_id = telegram_config.admin_group_id
        
        # 标记为已读并删除未读话题中的消息
        handler = update.effective_user
        now = datetime.now()
        count = 0
        
        for msg in unread_messages:
            # 保存未读话题中的消息ID，以便删除
            unread_topic_message_id = msg.unread_topic_message_id
            
            # 标记为已读
            msg.is_unread_topic = False
            msg.handled_by_user_id = handler.id
            msg.handled_time = now
            count += 1
            
            # 如果有未读话题消息ID，尝试删除该消息
            if unread_topic_message_id:
                try:
                    await context.bot.delete_message(
                        chat_id=admin_group_id,
                        message_id=unread_topic_message_id
                    )
                    logger.info(f"已删除未读话题中的消息: {unread_topic_message_id}")
                except Exception as e:
                    logger.error(f"删除未读话题消息失败: {str(e)}")
        
        # 提交更改
        db.commit()
        
        # 提供反馈
        if count > 0:
            await query.answer(f"已标记 {count} 条{source_desc}消息为已读并清理未读提醒")
            logger.info(f"已将用户 {user_id} 的{source_desc}未读消息({count}条)标记为已读")
        else:
            await query.answer("没有需要标记的未读消息")
    except Exception as e:
        logger.error(f"标记已读时出错: {str(e)}")
        await query.answer(f"处理失败: {str(e)[:50]}")

async def process_callback_spam(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理举报垃圾消息的回调"""
    query = update.callback_query
    data = query.data
    
    logger.info(f"处理spam_回调: {data}")
    
    # 解析消息ID
    parts = data.split("_")
    if len(parts) != 2:
        await query.answer("无效的操作格式")
        return
        
    try:
        message_id = int(parts[1])
        logger.info(f"准备举报消息ID {message_id} 为垃圾消息")
        
        # 查找消息记录
        db = next(get_db())
        message_map = db.query(MessageMap).filter(
            MessageMap.group_chat_message_id == message_id
        ).first()
        
        if not message_map:
            logger.warning(f"未找到消息ID {message_id} 的记录")
            await query.answer(f"未找到消息记录，请重试")
            return
            
        logger.info(f"找到消息映射: 用户ID={message_map.user_telegram_id}")
        
        # 获取用户ID
        user_id = message_map.user_telegram_id
        
        # 确定消息来源（私聊/群组）
        is_from_group = message_map.is_from_group
        source_group_id = message_map.source_group_id
        source_group_name = message_map.source_group_name
        
        # 根据来源类型查找对应的未读消息
        if is_from_group and source_group_id:
            # 如果是群组消息，只标记来自相同群组的未读消息为垃圾消息
            unread_messages = db.query(MessageMap).filter(
                MessageMap.user_telegram_id == user_id,
                MessageMap.is_unread_topic == True,
                MessageMap.is_from_group == True,
                MessageMap.source_group_id == source_group_id
            ).all()
            source_desc = f"群组({source_group_name or source_group_id})"
        else:
            # 如果是私聊消息，只标记私聊的未读消息为垃圾消息
            unread_messages = db.query(MessageMap).filter(
                MessageMap.user_telegram_id == user_id,
                MessageMap.is_unread_topic == True,
                MessageMap.is_from_group == False
            ).all()
            source_desc = "私聊"
        
        # 获取管理群组ID
        admin_group_id = telegram_config.admin_group_id
        
        # 标记为垃圾消息并删除未读话题中的消息
        handler = update.effective_user
        now = datetime.now()
        count = 0
        
        for msg in unread_messages:
            # 保存未读话题中的消息ID，以便删除
            unread_topic_message_id = msg.unread_topic_message_id
            
            # 标记为垃圾消息
            msg.is_unread_topic = False
            msg.handled_by_user_id = handler.id
            msg.handled_time = now
            count += 1
            
            # 如果有未读话题消息ID，尝试删除该消息
            if unread_topic_message_id:
                try:
                    await context.bot.delete_message(
                        chat_id=admin_group_id,
                        message_id=unread_topic_message_id
                    )
                    logger.info(f"已删除未读话题中的消息: {unread_topic_message_id}")
                except Exception as e:
                    logger.error(f"删除未读话题消息失败: {str(e)}")
        
        # 提交更改
        db.commit()
        
        # 提供反馈
        if count > 0:
            await query.answer(f"已标记 {count} 条{source_desc}消息为垃圾消息并清理未读提醒")
            logger.info(f"已将用户 {user_id} 的{source_desc}未读消息({count}条)标记为垃圾消息")
        else:
            await query.answer("没有需要标记的未读消息")
    except Exception as e:
        logger.error(f"标记垃圾消息时出错: {str(e)}")
        await query.answer(f"处理失败: {str(e)[:50]}") 