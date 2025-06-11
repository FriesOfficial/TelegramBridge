#!/usr/bin/env python3
"""
Telegram客服系统 - 单一入口脚本

基于python-telegram-bot官方推荐方式实现的Telegram客服系统
使用官方的application.run_polling()方法运行Bot，解决"terminated by other getUpdates request"错误

使用方法:
1. 安装依赖：pip install -r requirements.txt
2. 配置环境变量或创建.env文件设置以下变量：
   - TELEGRAM_TOKEN: 机器人令牌
   - TELEGRAM_ADMIN_GROUP_ID: 管理员群组ID（必须为超级群组且启用话题功能）
   - TELEGRAM_ADMIN_USER_IDS: 管理员用户ID，逗号分隔
3. 运行：python telegram_bot.py [--debug] [--db-only]

命令参数:
  --debug    启用调试模式，输出更详细的日志
  --db-only  仅初始化数据库，不启动机器人

参考文档：https://docs.python-telegram-bot.org/en/stable/
"""
import os
import sys
import logging
import asyncio
import argparse
import signal
from dotenv import load_dotenv
from datetime import datetime

from telegram import Update, ForumTopic
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
    JobQueue
)
from telegram.error import (
    TelegramError, 
    Forbidden, 
    NetworkError,
    BadRequest,
    TimedOut
)


# 设置日志
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    stream=sys.stdout  # 输出到标准输出而不是文件
)

# 设置更多详细日志
logging.getLogger('telegram').setLevel(logging.DEBUG)
logging.getLogger('telegram.ext').setLevel(logging.DEBUG)
logging.getLogger('app.telegram').setLevel(logging.DEBUG)

logger = logging.getLogger('telegram-bot')

# 加载环境变量
# 修改这一行
load_dotenv()

# 改为下面的代码
# 优先加载当前目录的.env文件
if os.path.exists(".env"):
    load_dotenv(override=True)
    logger.info("已加载当前目录中的.env文件")
else:
    load_dotenv()
    logger.info("使用默认环境变量配置")

# 确保目录存在
os.makedirs("assets/imgs", exist_ok=True)

# 导入配置和工具函数
from app.config.telegram_config import telegram_config
from app.database.database import get_db
from app.telegram.utils import (
    check_user_ban_status,
    create_or_get_user_topic,
    get_topic_title_by_user,
    get_user_by_id,
    verify_admin_group,
    forward_message_to_user,
    forward_message_to_admin,
    handle_media_group,
    forwarding_message_u2a,
    forwarding_message_a2u,
    initialize_system_topics
)


# 全局变量
bot_instance = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理/start命令"""
    user = update.effective_user
    welcome_message = telegram_config.welcome_message or "欢迎您"
    
    # 记录用户信息到数据库
    db = next(get_db())
    await get_user_by_id(db, user.id, create_if_not_exists=True)
    
    await update.message.reply_text(welcome_message)
    logger.info(f"用户 {user.id} ({user.username or user.first_name}) 开始使用客服系统")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理/help命令"""
    help_text = (
        "客服系统使用指南：\n\n"
        "1. 直接发送消息与客服人员沟通\n"
        "2. 您可以发送文字、图片、视频、文件等多种类型的消息\n"
        "3. 客服人员会尽快回复您的消息\n\n"
        "如需再次查看此帮助信息，请发送 /help 命令"
    )
    await update.message.reply_text(help_text)

async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理回调查询"""
    try:
        query = update.callback_query
        data = query.data
        
        logger.info(f"处理回调查询: {data}")
        
        # 根据回调数据类型分发处理
        if data.startswith("read_"):
            # 处理标记已读回调
            logger.info(f"处理标记已读回调: {data}")
            # 直接传递给process_callback_query处理
            from app.telegram.callbacks import process_callback_query
            await process_callback_query(update, context)
        else:
            # 其他回调类型，传递给process_callback_query
            from app.telegram.callbacks import process_callback_query
            await process_callback_query(update, context)
    except Exception as e:
        logger.error(f"处理回调查询时出错: {str(e)}")
        await update.callback_query.answer("处理失败，请重试")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理错误"""
    logger.error("Exception while handling an update:", exc_info=context.error)
    
    if isinstance(context.error, TimedOut):
        logger.warning("网络超时，将在稍后重试")
    elif isinstance(context.error, NetworkError):
        logger.error("网络错误，请检查网络连接")
    elif isinstance(context.error, Forbidden):
        logger.error("操作被禁止，可能是权限不足")
    elif isinstance(context.error, BadRequest):
        logger.error(f"错误的请求: {context.error}")
    else:
        logger.error(f"未知错误: {context.error}")

async def reload_config_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理/reload_config命令，重新加载配置"""
    user_id = update.effective_user.id
    if user_id not in telegram_config.admin_user_ids:
        await update.message.reply_text("您没有权限执行此操作")
        return
        
    # 重新加载配置
    load_dotenv(override=True)
    telegram_config.reload_config()
    
    await update.message.reply_text("配置已重新加载")
    logger.info(f"管理员 {user_id} 重新加载了配置")

def setup_application() -> Application:
    """设置应用"""
    # 创建应用构建器
    builder = Application.builder()
    
    # 设置Token
    builder.token(telegram_config.token)
    
    # 设置HTTP配置
    http_config = telegram_config.get_http_config()
    builder.connection_pool_size(http_config["connection_pool_size"])
    builder.connect_timeout(http_config["connect_timeout"])
    builder.read_timeout(http_config["read_timeout"])
    builder.write_timeout(http_config["write_timeout"])
    
    # 启用job_queue
    builder.job_queue(JobQueue())
    
    # 构建应用
    application = builder.build()
    
    # 添加命令处理程序
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("reload_config", reload_config_command))
    
    # 添加用户和管理群组消息处理程序
    application.add_handler(
        MessageHandler(
            ~filters.COMMAND & filters.ChatType.PRIVATE,
            forwarding_message_u2a
        )
    )
    
    application.add_handler(
        MessageHandler(
            ~filters.COMMAND & filters.Chat(chat_id=telegram_config.admin_group_id), 
            forwarding_message_a2u
        )
    )
    
    # 添加回调查询处理程序
    application.add_handler(CallbackQueryHandler(callback_query_handler))
    
    # 添加错误处理程序
    application.add_error_handler(error_handler)
    
    return application

def init_database():
    """初始化数据库"""
    try:
        # 导入数据库模型并创建表
        from app.database.database import Base, engine
        from app.models import User, MediaGroupMessage, FormnStatus, MessageMap
        
        # 创建基本表结构
        Base.metadata.create_all(bind=engine)
        
        logger.info("数据库初始化成功")
        return True
    except Exception as e:
        logger.error(f"数据库初始化失败: {str(e)}")
        return False

async def verify_bot_environment():
    """验证机器人运行环境"""
    try:
        logger.info("正在验证机器人运行环境...")
        
        # 创建临时应用程序检查环境
        app = ApplicationBuilder().token(telegram_config.token).build()
        
        # 1. 检查Token是否有效
        try:
            bot_info = await app.bot.get_me()
            logger.info(f"1. Bot令牌有效: {bot_info.first_name} (@{bot_info.username})")
        except TelegramError:
            logger.error("1. Bot令牌无效")
            return False
            
        # 2. 检查管理群组是否有效
        if not await verify_admin_group(app.bot):
            logger.error("2. 管理群组无效")
            return False
        else:
            logger.info("2. 管理群组有效")
            
        # 3. 检查机器人是否有管理权限
        try:
            bot_member = await app.bot.get_chat_member(
                chat_id=telegram_config.admin_group_id,
                user_id=bot_info.id
            )
            if bot_member.status == "administrator":
                logger.info("3. Bot是群组的管理员")
            else:
                logger.error("3. Bot不是群组的管理员")
                return False
        except TelegramError:
            logger.error("3. Bot是群组的管理员")
            return False
            
        # 4. 初始化系统话题
        if await initialize_system_topics(app.bot):
            logger.info("4. 系统话题初始化成功")
        else:
            logger.warning("4. 系统话题初始化失败，但将继续运行")
            
        # 关闭临时应用
        await app.shutdown()
        
        logger.info("机器人环境验证完成")
        return True
    except Exception as e:
        logger.error(f"验证机器人环境时出错: {str(e)}")
        return False

async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Telegram客服系统")
    parser.add_argument("--debug", action="store_true", help="启用调试模式")
    parser.add_argument("--env", help="指定自定义.env文件路径", default=".env")
    args = parser.parse_args()
    
    # 设置日志级别
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("已启用调试模式")
    
    # 优先读取外部配置文件
    # 如果是打包环境，优先读取外部配置
    if getattr(sys, 'frozen', False):
        # 打包环境
        logger.info("检测到打包环境，将优先读取外部配置")
        # 检查当前目录下是否存在.env文件
        if os.path.exists(".env"):
            load_dotenv(override=True)
            telegram_config.reload_config()
            logger.info("已从当前目录加载.env配置")
    
    # 如果指定了自定义.env文件，则加载它
    if args.env != ".env" and os.path.exists(args.env):
        load_dotenv(dotenv_path=args.env, override=True)
        telegram_config.reload_config()
        logger.info(f"已加载自定义配置文件: {args.env}")
    
    # 检查配置
    if not telegram_config.config_valid:
        logger.error("配置检查失败，请确保设置了所有必要的环境变量")
        return 1
    
    # 初始化数据库
    if not init_database():
        logger.error("数据库初始化失败")
        return 1
    
    # 验证机器人环境并初始化系统话题
    try:
        if not await verify_bot_environment():
            logger.warning("机器人环境验证失败，但仍将尝试启动")
    except Exception as e:
        logger.error(f"验证环境时出错: {str(e)}")
        logger.warning("将尝试继续启动机器人")
    
    # 设置信号处理
    def signal_handler(sig, frame):
        logger.info(f"收到信号 {sig}，正在优雅退出...")
        sys.exit(0)
    
    # 注册信号处理
    signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler) # 终止信号
    
    # 在非Windows系统上额外注册SIGABRT
    if hasattr(signal, 'SIGABRT'):
        signal.signal(signal.SIGABRT, signal_handler)
    
    # 设置应用
    application = setup_application()
    
    # 运行机器人（使用异步方法）
    logger.info("正在启动Telegram Bot...")
    
    try:
        # 使用异步方式运行机器人
        await application.initialize()
        await application.start()
        await application.updater.start_polling(
            poll_interval=1.0,
            timeout=30,
            bootstrap_retries=5,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=False
        )
        
        # 让程序保持运行状态
        # 这里使用简单的方法保持运行，也可以使用其他方式如信号处理等
        while True:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("程序被用户中断")
    except Exception as e:
        logger.error(f"运行Telegram Bot时出错: {str(e)}")
        return 1
    finally:
        # 确保优雅地关闭机器人
        try:
            await application.updater.stop()
            await application.stop()
            await application.shutdown()
        except Exception as e:
            logger.error(f"关闭机器人时出错: {str(e)}")
        
    return 0

if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except Exception as e:
        logger.critical(f"程序异常退出: {str(e)}")
        sys.exit(1) 