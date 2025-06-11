# Bot模块
"""
Telegram Bot 客服系统实现
"""
import os
import random
import time
import logging
from datetime import datetime, timedelta
from string import ascii_letters as letters

import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    PicklePersistence,
    filters,
)
from telegram.helpers import mention_html

from app.database.database import SessionLocal, get_db
from app.models.media_group_message import MediaGroupMessage
from app.models.formn_status import FormnStatus
from app.models.message_map import MessageMap
from app.models.user import User
from app.config import telegram_config
from app.telegram.callbacks import (
    process_callback_query,
    process_callback_vcode,
    generate_verification_code,
    create_verification_keyboard
)

# 设置日志
logger = logging.getLogger(__name__)

# 创建数据库会话
db = SessionLocal()

# 用户状态检查
async def check_user_ban_status(db, user_id):
    """检查用户是否被禁止使用客服系统"""
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        return False
    return not user.is_active

# 延时发送媒体组消息的回调
async def _send_media_group_later(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    media_group_id = job.data
    _, from_chat_id, target_id, dir = job.name.split("_")

    # 数据库内查找对应的媒体组消息。
    media_group_msgs = (
        db.query(MediaGroupMessage)
        .filter(
            MediaGroupMessage.media_group_id == media_group_id,
            MediaGroupMessage.chat_id == from_chat_id,
        )
        .all()
    )
    chat = await context.bot.get_chat(target_id)
    if dir == "u2a":
        # 发送给群组
        u = db.query(User).filter(User.user_id == from_chat_id).first()
        message_thread_id = u.message_thread_id
        sents = await chat.send_copies(
            from_chat_id,
            [m.message_id for m in media_group_msgs],
            message_thread_id=message_thread_id,
        )
        for sent, msg in zip(sents, media_group_msgs):
            msg_map = MessageMap(
                user_chat_message_id=msg.message_id,
                group_chat_message_id=sent.message_id,
                user_telegram_id=u.user_id,
            )
            db.add(msg_map)
            db.commit()
    else:
        # 发送给用户
        sents = await chat.send_copies(
            from_chat_id, [m.message_id for m in media_group_msgs]
        )
        for sent, msg in zip(sents, media_group_msgs):
            msg_map = MessageMap(
                user_chat_message_id=sent.message_id,
                group_chat_message_id=msg.message_id,
                user_telegram_id=target_id,
            )
            db.add(msg_map)
            db.commit()


# 延时发送媒体组消息
async def send_media_group_later(
    delay: float,
    chat_id,
    target_id,
    media_group_id: int,
    dir,
    context: ContextTypes.DEFAULT_TYPE,
):
    name = f"sendmediagroup_{chat_id}_{target_id}_{dir}"
    context.job_queue.run_once(
        _send_media_group_later, delay, chat_id=chat_id, name=name, data=media_group_id
    )
    return name


def update_user_db(user: telegram.User):
    """更新用户数据库"""
    u = db.query(User).filter(User.user_id == user.id).first()
    if u:
        return u
    
    # 创建新用户
    u = User(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        is_active=True
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


async def send_contact_card(
    chat_id, message_thread_id, user: User, update: Update, context: ContextTypes
):
    """发送联系人卡片"""
    # 检查用户是否是Telegram Premium会员
    try:
        tg_user = await context.bot.get_chat(user.user_id)
        is_premium = getattr(tg_user, 'is_premium', False)
    except Exception as e:
        logger.error(f"获取用户Premium状态时出错: {str(e)}")
        is_premium = getattr(user, 'is_premium', False)
    
    buttons = []
    buttons.append(
        [
            InlineKeyboardButton(
                f"{'💎 Telegram Premium 会员' if is_premium else '👤 普通用户'}",
                url=f"https://github.com/MiHaKun/Telegram-interactive-bot",
            )
        ]
    )
    if user.username:
        buttons.append(
            [InlineKeyboardButton("👤 直接联络", url=f"https://t.me/{user.username}")]
        )

    user_photo = await context.bot.get_user_profile_photos(user.user_id)

    premium_tag = "💎 " if is_premium else ""
    
    if user_photo.total_count:
        pic = user_photo.photos[0][-1].file_id
        await context.bot.send_photo(
            chat_id,
            photo=pic,
            caption=f"{premium_tag}👤 {mention_html(user.user_id, user.first_name)}\n\n📱 {user.user_id}\n\n🔗 @{user.username if user.username else '无'}\n\n🏅 会员状态: {'💎 Telegram Premium 用户' if is_premium else '普通用户'}",
            message_thread_id=message_thread_id,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML",
        )
    else:
        await context.bot.send_contact(
            chat_id,
            phone_number="11111",
            first_name=f"{premium_tag}{user.first_name}",
            last_name=user.last_name or "",
            message_thread_id=message_thread_id,
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        # 发送额外信息
        await context.bot.send_message(
            chat_id,
            text=f"👤 {mention_html(user.user_id, user.first_name)}\n\n📱 {user.user_id}\n\n🔗 @{user.username if user.username else '无'}\n\n🏅 会员状态: {'💎 Telegram Premium 用户' if is_premium else '普通用户'}",
            message_thread_id=message_thread_id,
            parse_mode="HTML",
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理/start命令"""
    user = update.effective_user
    db_user = update_user_db(user)
    
    # 检查是否是管理员
    if user.id in telegram_config.admin_user_ids:
        logger.info(f"{user.first_name}({user.id}) is admin")
        try:
            bg = await context.bot.get_chat(telegram_config.admin_group_id)
            if bg.type == "supergroup" or bg.type == "group":
                logger.info(f"admin group is {bg.title}")
        except Exception as e:
            logger.error(f"admin group error {e}")
            await update.message.reply_html(
                f"⚠️⚠️后台管理群组设置错误，请检查配置。⚠️⚠️\n你需要确保已经将机器人 @{context.bot.username} 邀请入管理群组并且给与了管理员权限。\n错误细节：{e}\n"
            )
            return ConversationHandler.END
        await update.message.reply_html(
            f"你好管理员 {user.first_name}({user.id})\n\n欢迎使用 {telegram_config.app_name} 机器人。\n\n 目前你的配置完全正确。可以在群组 <b> {bg.title} </b> 中使用机器人。"
        )
    else:
        await update.message.reply_html(
            f"{mention_html(user.id, user.full_name)} 同学：\n\n{telegram_config.welcome_message}"
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理/help命令"""
    user = update.effective_user
    
    help_text = (
        f"欢迎使用 {telegram_config.app_name} 客服系统！\n\n"
        "可用命令:\n"
        "/start - 开始使用客服系统\n"
        "/help - 显示此帮助信息\n\n"
        "直接发送消息即可与客服人员沟通。"
    )
    
    # 如果是管理员，添加管理员命令
    if str(user.id) in telegram_config.admin_user_ids:
        admin_help = (
            "\n\n管理员命令 (仅在管理群组中有效):\n"
            "/clear - 清除当前话题\n"
            "/broadcast - 向所有用户广播消息 (需回复要广播的消息)"
        )
        help_text += admin_help
    
    await update.message.reply_text(help_text)


async def check_human(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """检查用户是否是人类"""
    user = update.effective_user
    if context.user_data.get("is_human", False) == False:
        if context.user_data.get("is_human_error_time", 0) > time.time() - 120:
            # 2分钟内禁言
            await update.message.reply_html("你已经被禁言,请稍后再尝试。")
            return False
            
        # 检查是否有验证码图片
        if not os.path.exists("./assets/imgs"):
            os.makedirs("./assets/imgs", exist_ok=True)
            
        # 如果没有验证码图片，跳过验证
        files = os.listdir("./assets/imgs")
        if not files:
            context.user_data["is_human"] = True
            return True
            
        # 生成验证码
        code, identifier = await generate_verification_code()
        
        # 保存验证码信息到用户上下文
        context.user_data["verification"] = {
            "code": code,
            "identifier": identifier
        }
        
        # 创建验证码键盘
        keyboard = await create_verification_keyboard(code, identifier)
        
        # 发送验证消息
        sent = await update.message.reply_text(
            f"{mention_html(user.id, user.first_name)} 请选择正确的验证码",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        # 60秒后删除消息
        await delete_message_later(60, sent.chat.id, sent.message_id, context)
        return False
    return True


async def forwarding_message_u2a(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """将用户消息转发到管理群组"""
    if not telegram_config.disable_captcha:
        if not await check_human(update, context):
            return
    if telegram_config.message_interval:
        if context.user_data.get("last_message_time", 0) > time.time() - telegram_config.message_interval:
            await update.message.reply_html("请不要频繁发送消息。")
            return
        context.user_data["last_message_time"] = time.time()
    user = update.effective_user
    db_user = update_user_db(user)
    chat_id = telegram_config.admin_group_id
    
    # 从数据库获取用户信息
    u = db.query(User).filter(User.user_id == user.id).first()
    message_thread_id = u.message_thread_id
    
    # 检查话题状态
    if (
        f := db.query(FormnStatus)
        .filter(FormnStatus.message_thread_id == message_thread_id)
        .first()
    ):
        if f.status == "closed":
            await update.message.reply_html(
                "客服已经关闭对话。如需联系，请利用其他途径联络客服回复和你的对话。"
            )
            return
            
    # 如果用户没有话题，创建一个
    if not message_thread_id:
        # 检查用户是否是Telegram Premium会员
        try:
            tg_user = await context.bot.get_chat(user.id)
            is_premium = getattr(tg_user, 'is_premium', False)
        except Exception as e:
            logger.error(f"获取用户Premium状态时出错: {str(e)}")
            is_premium = False
            
        # 添加Premium标记到话题名称
        premium_mark = "💎" if is_premium else ""
        topic_name = f"{premium_mark}{user.full_name}|{user.id}"
            
        formn = await context.bot.create_forum_topic(
            chat_id,
            name=topic_name[:64],  # 话题名称最大长度为64
        )
        message_thread_id = formn.message_thread_id
        u.message_thread_id = message_thread_id
        
        # 发送带有Premium状态的新用户通知
        premium_status = "💎 Telegram Premium用户" if is_premium else "普通用户"
        await context.bot.send_message(
            chat_id,
            f"新的用户 {mention_html(user.id, user.full_name)} ({premium_status}) 开始了一个新的会话。",
            message_thread_id=message_thread_id,
            parse_mode="HTML",
        )
        await send_contact_card(chat_id, message_thread_id, u, update, context)
        db.add(u)
        db.commit()

    # 构筑下发送参数
    params = {"message_thread_id": message_thread_id}
    if update.message.reply_to_message:
        # 用户引用了一条消息。我们需要找到这条消息在群组中的id
        reply_in_user_chat = update.message.reply_to_message.message_id
        if (
            msg_map := db.query(MessageMap)
            .filter(MessageMap.user_chat_message_id == reply_in_user_chat)
            .first()
        ):
            params["reply_to_message_id"] = msg_map.group_chat_message_id
    try:
        if update.message.media_group_id:
            msg = MediaGroupMessage(
                chat_id=update.message.chat.id,
                message_id=update.message.message_id,
                media_group_id=update.message.media_group_id,
                is_header=False,
                caption=update.message.caption_html if update.message.caption else None,
            )
            db.add(msg)
            db.commit()
            if update.message.media_group_id != context.user_data.get(
                "current_media_group_id", 0
            ):
                context.user_data["current_media_group_id"] = (
                    update.message.media_group_id
                )
                await send_media_group_later(
                    5, user.id, chat_id, update.message.media_group_id, "u2a", context
                )
            return
        else:
            chat = await context.bot.get_chat(chat_id)
            sent_msg = await chat.send_copy(
                from_chat_id=update.effective_chat.id, 
                message_id=update.message.id, 
                **params
            )

        msg_map = MessageMap(
            user_chat_message_id=update.message.id,
            group_chat_message_id=sent_msg.message_id,
            user_telegram_id=user.id,
        )
        db.add(msg_map)
        db.commit()

    except BadRequest as e:
        if telegram_config.is_delete_topic_as_ban_forever:
            await update.message.reply_html(
                f"发送失败，你的对话已经被客服删除。请联系客服重新打开对话。"
            )
        else:
            u.message_thread_id = 0
            db.add(u)
            db.commit()
            await update.message.reply_html(
                f"发送失败，你的对话已经被客服删除。请再发送一条消息用来激活对话。"
            )
    except Exception as e:
        await update.message.reply_html(
            f"发送失败: {e}\n"
        )


async def forwarding_message_a2u(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """将管理群组消息转发到用户"""
    update_user_db(update.effective_user)
    message_thread_id = update.message.message_thread_id
    if not message_thread_id:
        # 普通消息，忽略
        return
        
    # 查找对应的用户
    user_id = 0
    if u := db.query(User).filter(User.message_thread_id == message_thread_id).first():
        user_id = u.user_id
    if not user_id:
        logger.debug(update.message)
        return
        
    # 处理话题状态变化
    if update.message.forum_topic_created:
        f = FormnStatus(
            message_thread_id=update.message.message_thread_id, 
            status="opened"
        )
        db.add(f)
        db.commit()
        return
    if update.message.forum_topic_closed:
        await context.bot.send_message(
            user_id, "对话已经结束。对方已经关闭了对话。你的留言将被忽略。"
        )
        if (
            f := db.query(FormnStatus)
            .filter(FormnStatus.message_thread_id == update.message.message_thread_id)
            .first()
        ):
            f.status = "closed"
            db.add(f)
            db.commit()
        return
    if update.message.forum_topic_reopened:
        await context.bot.send_message(user_id, "对方重新打开了对话。可以继续对话了。")
        if (
            f := db.query(FormnStatus)
            .filter(FormnStatus.message_thread_id == update.message.message_thread_id)
            .first()
        ):
            f.status = "opened"
            db.add(f)
            db.commit()
        return
        
    # 检查话题状态
    if (
        f := db.query(FormnStatus)
        .filter(FormnStatus.message_thread_id == message_thread_id)
        .first()
    ):
        if f.status == "closed":
            await update.message.reply_html(
                "对话已经结束。希望和对方联系，需要打开对话。"
            )
            return
            
    chat_id = user_id
    # 构筑下发送参数
    params = {}
    if update.message.reply_to_message:
        # 群组中，客服回复了一条消息。我们需要找到这条消息在用户中的id
        reply_in_admin = update.message.reply_to_message.message_id
        if (
            msg_map := db.query(MessageMap)
            .filter(MessageMap.group_chat_message_id == reply_in_admin)
            .first()
        ):
            params["reply_to_message_id"] = msg_map.user_chat_message_id
    try:
        if update.message.media_group_id:
            msg = MediaGroupMessage(
                chat_id=update.message.chat.id,
                message_id=update.message.message_id,
                media_group_id=update.message.media_group_id,
                is_header=False,
                caption=update.message.caption_html if update.message.caption else None,
            )
            db.add(msg)
            db.commit()
            if update.message.media_group_id != context.application.user_data.get(user_id, {}).get("current_media_group_id", 0):
                if not user_id in context.application.user_data:
                    context.application.user_data[user_id] = {}
                context.application.user_data[user_id]["current_media_group_id"] = update.message.media_group_id
                await send_media_group_later(
                    5,
                    update.effective_chat.id,
                    user_id,
                    update.message.media_group_id,
                    "a2u",
                    context,
                )
            return
        else:
            chat = await context.bot.get_chat(chat_id)
            sent_msg = await chat.send_copy(
                from_chat_id=update.effective_chat.id, 
                message_id=update.message.id, 
                **params
            )
        msg_map = MessageMap(
            group_chat_message_id=update.message.id,
            user_chat_message_id=sent_msg.message_id,
            user_telegram_id=user_id,
        )
        db.add(msg_map)
        db.commit()

    except Exception as e:
        await update.message.reply_html(
            f"发送失败: {e}\n"
        )


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """清除话题并可选择删除用户消息"""
    user = update.effective_user
    if not user.id in telegram_config.admin_user_ids:
        await update.message.reply_html("你没有权限执行此操作。")
        return
    await context.bot.delete_forum_topic(
        update.effective_chat.id, update.message.message_thread_id
    )
    if not telegram_config.is_delete_user_messages:
        return
    if (
        target_user := db.query(User)
        .filter(User.message_thread_id == update.message.message_thread_id)
        .first()
    ):
        all_messages_in_user_chat = (
            db.query(MessageMap).filter(MessageMap.user_telegram_id == target_user.user_id).all()
        )
        await context.bot.delete_messages(
            target_user.user_id,
            [msg.user_chat_message_id for msg in all_messages_in_user_chat],
        )


async def _broadcast(context: ContextTypes.DEFAULT_TYPE):
    """广播消息给所有用户"""
    users = db.query(User).all()
    msg_id, chat_id = context.job.data.split("_")
    success = 0
    failed = 0
    for u in users:
        try:
            chat = await context.bot.get_chat(u.user_id)
            await chat.send_copy(chat_id, msg_id)
            success += 1
        except Exception as e:
            failed += 1


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """广播消息"""
    user = update.effective_user
    if not user.id in telegram_config.admin_user_ids:
        await update.message.reply_html("你没有权限执行此操作。")
        return

    if not update.message.reply_to_message:
        await update.message.reply_html(
            "这条指令需要回复一条消息，被回复的消息将被广播。"
        )
        return

    context.job_queue.run_once(
        _broadcast,
        0,
        data=f"{update.message.reply_to_message.id}_{update.effective_chat.id}",
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理错误"""
    logger.error(f"Exception while handling an update: {context.error} ")
    logger.debug(f"Exception detail is :", exc_info=context.error)


class TelegramCustomerServiceBot:
    """Telegram客服机器人"""
    
    def __init__(self):
        """初始化机器人"""
        self.application = ApplicationBuilder().token(telegram_config.token).build()
        
        # 设置处理程序
        setup_handlers(self.application)
        
        # 待处理的消息组
        self.pending_media_groups = {}
    
    async def start(self):
        """启动机器人"""
        try:
            # 启动轮询
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling()
            
            logger.info("Telegram客服机器人已启动")
        except Exception as e:
            logger.error(f"启动Telegram客服机器人时出错: {str(e)}")
    
    async def stop(self):
        """停止机器人"""
        if self.application:
            await self.application.stop()
            await self.application.shutdown()
            logger.info("Telegram客服机器人已停止")

# 全局机器人实例
bot_instance = None

async def verify_admin_group(bot):
    """验证管理群组配置是否正确"""
    try:
        # 尝试获取管理群组信息
        group_id = int(telegram_config.admin_group_id)
        chat = await bot.get_chat(group_id)
        
        # 检查是否是群组
        if chat.type not in ["group", "supergroup"]:
            logger.error(f"管理群组ID配置错误: {group_id} 不是群组")
            return False
            
        # 检查是否是超级群组
        if chat.type != "supergroup":
            logger.warning(f"管理群组不是超级群组，可能无法使用话题功能")
            
        # 检查Bot是否有管理员权限
        bot_member = await bot.get_chat_member(group_id, bot.id)
        if bot_member.status != "administrator":
            logger.error(f"Bot在管理群组中不是管理员，无法创建话题")
            return False
            
        # 检查机器人是否有管理话题的权限
        if not getattr(bot_member, "can_manage_topics", False):
            logger.error(f"Bot在管理群组中没有管理话题的权限")
            return False
        
        # 检查群组是否启用了话题功能
        if not getattr(chat, "is_forum", False):
            logger.error(f"管理群组未启用话题功能，请在群组设置中启用")
            return False
            
        logger.info(f"管理群组 {chat.title} 配置正确")
        return True
    except Exception as e:
        logger.error(f"验证管理群组时出错: {str(e)}")
        return False

async def start_bot():
    """启动机器人"""
    global bot_instance
    bot_instance = TelegramCustomerServiceBot()
    
    # 验证管理群组
    is_valid = await verify_admin_group(bot_instance.application.bot)
    if not is_valid:
        logger.error("管理群组配置错误，客服系统将无法正常工作")
        logger.error("请确保：")
        logger.error("1. TELEGRAM_ADMIN_GROUP_ID 配置正确")
        logger.error("2. 群组已启用话题功能")
        logger.error("3. Bot是群组的管理员")
    
    # 启动Bot
    await bot_instance.start()
    
    # 返回应用实例以便调用者可以选择不同的运行方式
    return bot_instance.application
    
async def stop_bot():
    """停止机器人"""
    global bot_instance
    if bot_instance:
        await bot_instance.stop()
        bot_instance = None
        
# 提供同步方式运行机器人的函数
def run_bot():
    """同步方式运行机器人，适合直接从命令行启动"""
    from telegram.ext import ApplicationBuilder
    
    # 创建应用
    application = ApplicationBuilder().token(telegram_config.token).build()
    
    # 设置处理程序
    setup_handlers(application)
    
    # 运行轮询 - 这是最可靠的方式
    application.run_polling(allowed_updates=Update.ALL_TYPES)
    
def setup_handlers(application):
    """为应用添加消息处理程序"""
    # 命令处理
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    
    # 用户和管理群组消息处理
    application.add_handler(
        MessageHandler(
            ~filters.COMMAND & filters.ChatType.PRIVATE,
            forwarding_message_u2a
        )
    )
    
    application.add_handler(
        MessageHandler(
            ~filters.COMMAND & filters.Chat([int(telegram_config.admin_group_id)]), 
            forwarding_message_a2u
        )
    )
    
    # 管理命令
    application.add_handler(
        CommandHandler("clear", clear, filters.Chat([int(telegram_config.admin_group_id)]))
    )
    application.add_handler(
        CommandHandler("broadcast", broadcast, filters.Chat([int(telegram_config.admin_group_id)]))
    )
    
    # 回调处理
    import re
    # 验证码回调处理
    application.add_handler(
        CallbackQueryHandler(process_callback_vcode, pattern=re.compile(r"^vcode_"))
    )
    
    # 标记已读回调处理 - 确保这个模式匹配read_数字格式
    application.add_handler(
        CallbackQueryHandler(process_callback_query, pattern=re.compile(r"^read_\d+$"))
    )
    
    # 其他回调处理
    application.add_handler(
        CallbackQueryHandler(process_callback_query, pattern=re.compile(r"^reply_\d+$"))
    )
    application.add_handler(
        CallbackQueryHandler(process_callback_query, pattern=re.compile(r"^spam_\d+$"))
    )
    application.add_handler(
        CallbackQueryHandler(process_callback_query, pattern=re.compile(r"^view_\d+$"))
    )
    
    # 添加调试处理程序
    async def debug_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """调试回调查询"""
        query = update.callback_query
        logger.error(f"DEBUG: 收到未捕获的回调查询: {query.data}")
        await query.answer("暂不支持此操作")
        
    # 添加通用处理器，捕获所有未被其他处理器捕获的回调
    application.add_handler(
        CallbackQueryHandler(debug_callback)
    )
    
    # 错误处理
    application.add_error_handler(error_handler)

# 如果直接运行此文件，启动机器人
if __name__ == "__main__":
    # 使用同步方式运行机器人，更稳定
    run_bot()

async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理用户私聊消息"""
    # 记录消息
    user = update.effective_user
    logger.info(f"收到用户消息: {user.id} ({user.username or user.first_name})")
    
    # 检查是否是管理员
    if user.id in telegram_config.admin_user_ids:
        logger.info(f"管理员 {user.username or user.first_name} 直接对机器人发送消息，不处理")
        return
        
    # 检查用户是否被禁止
    db = next(get_db())
    if await check_user_ban_status(db, user.id):
        await update.message.reply_text("您已被禁止使用客服系统，如有疑问请联系管理员。")
        return
        
    # 处理媒体组消息
    if update.message.media_group_id:
        # 获取全局待处理媒体组
        global bot_instance
        pending_media_groups = getattr(bot_instance, 'pending_media_groups', {}) if bot_instance else {}
        await handle_media_group(update, context, pending_media_groups)
        return
        
    # 转发消息到管理群组
    await forward_to_admin_group(update, context)

async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理管理员回复"""
    # 只处理话题中的消息
    if not update.message.message_thread_id:
        return
        
    # 获取对应的用户ID
    db = next(get_db())
    user_query = db.query(User).filter(User.message_thread_id == update.message.message_thread_id)
    user = user_query.first()
    
    if not user:
        logger.warning(f"找不到对应的用户，话题ID: {update.message.message_thread_id}")
        await update.message.reply_text("找不到对应的用户，可能已被删除。")
        return
        
    # 转发管理员消息给用户
    try:
        # 处理媒体消息
        message = update.message
        if message.photo or message.video or message.document or message.voice or message.audio:
            await send_media_to_user(context.bot, user.user_id, update)
        else:
            # 处理文本消息
            reply_to_message_id = await get_reply_to_message_id(db, update)
            await context.bot.send_message(
                chat_id=user.user_id,
                text=message.text or message.caption or "消息内容为空",
                reply_to_message_id=reply_to_message_id
            )
            
        # 保存消息映射
        new_map = MessageMap(
            user_message_id=None,
            admin_message_id=update.message.message_id,
            user_id=user.user_id,
            admin_id=update.effective_user.id,
            direction="admin_to_user"
        )
        db.add(new_map)
        db.commit()
        
    except Exception as e:
        logger.error(f"转发管理员消息时出错: {str(e)}")
        await update.message.reply_text(f"发送失败: {str(e)}")
        
async def forward_to_admin_group(update: Update, context: ContextTypes.DEFAULT_TYPE, user_obj=None) -> None:
    """将用户消息转发到管理员群组"""
    message = update.effective_message
    user = update.effective_user
    
    # 创建或获取用户的话题
    db = next(get_db())
    try:
        # 详细记录过程
        logger.info(f"正在为用户 {user.id} 创建或获取话题...")
        logger.info(f"管理群组ID: {telegram_config.admin_group_id}")
        
        topic_id = await create_or_get_user_topic(db, context.bot, user, int(telegram_config.admin_group_id))
        
        if not topic_id:
            logger.error(f"无法为用户 {user.id} 创建话题")
            await message.reply_text("无法创建客服会话，请稍后再试或联系管理员。")
            return
            
        logger.info(f"成功获取话题ID: {topic_id}")
    except Exception as e:
        logger.error(f"创建或获取用户话题时出错: {str(e)}")
        await message.reply_text("创建客服会话时出错，请稍后再试。")
        return
        
    try:
        # 处理媒体消息
        if message.photo or message.video or message.document or message.voice or message.audio:
            admin_message = await handle_file_sharing(
                context.bot, 
                int(telegram_config.admin_group_id), 
                topic_id, 
                update
            )
        else:
            # 处理文本消息
            admin_message = await context.bot.send_message(
                chat_id=int(telegram_config.admin_group_id),
                message_thread_id=topic_id,
                text=f"{user.first_name} 说: {message.text or message.caption or ''}",
            )
            
        # 保存消息映射
        new_map = MessageMap(
            user_message_id=message.message_id,
            admin_message_id=admin_message.message_id,
            user_id=user.id,
            admin_id=None,
            direction="user_to_admin"
        )
        db.add(new_map)
        db.commit()
        
        # 通知用户消息已收到
        await message.reply_text("消息已发送给客服，请等待回复。")
        
    except Exception as e:
        logger.error(f"转发用户消息时出错: {str(e)}")
        await message.reply_text("消息发送失败，请稍后重试。")
