"""
Telegram 配置模块
"""
import os
import logging
import signal
from typing import List, Optional
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 日志配置
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class TelegramConfig:
    """Telegram 配置类"""
    
    def __init__(self):
        """初始化配置"""
        self.reload_config()
        
        # 设置信号处理
        signal.signal(signal.SIGTERM, self._handle_exit)
        signal.signal(signal.SIGINT, self._handle_exit)
    
    def reload_config(self):
        """重新加载配置"""
        # 加载环境变量配置
        self.token = os.getenv("TELEGRAM_TOKEN")
        admin_group_id = os.getenv("TELEGRAM_ADMIN_GROUP_ID")
        admin_user_ids = os.getenv("TELEGRAM_ADMIN_USER_IDS", "")
        
        # 转换类型
        self.admin_group_id = int(admin_group_id) if admin_group_id else None
        self.admin_user_ids = [int(id.strip()) for id in admin_user_ids.split(",") if id.strip()] if admin_user_ids else []
        
        # 客服系统名称
        self.app_name = os.getenv("TELEGRAM_APP_NAME", "客服系统")
        
        # 欢迎消息
        self.welcome_message = os.getenv("TELEGRAM_WELCOME_MESSAGE")
        if self.welcome_message:
            # 将字符串中的"\n"替换为实际的换行符
            self.welcome_message = self.welcome_message.replace("\\n", "\n")
        
        # 是否禁用验证码
        self.disable_captcha = os.getenv("TELEGRAM_DISABLE_CAPTCHA", "").lower() in ["true", "1", "yes"]
        
        # 消息发送间隔(秒)
        self.message_interval = int(os.getenv("TELEGRAM_MESSAGE_INTERVAL", "0"))
        
        # API请求超时时间(秒)
        self.request_timeout = int(os.getenv("TELEGRAM_REQUEST_TIMEOUT", "30"))
        
        # 连接池大小
        self.connection_pool_size = int(os.getenv("TELEGRAM_CONNECTION_POOL_SIZE", "100"))
        
        # 最大重试次数
        self.max_retries = int(os.getenv("TELEGRAM_MAX_RETRIES", "3"))
        
        # 重试初始等待时间(秒)
        self.retry_initial_wait = float(os.getenv("TELEGRAM_RETRY_INITIAL_WAIT", "1.0"))
        
        # 是否启用客服功能
        self.enable_customer_service = os.getenv("TELEGRAM_ENABLE_CUSTOMER_SERVICE", "true").lower() in ["true", "1", "yes"]
        
        # 代理设置
        self.proxy_url = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
        if self.proxy_url:
            logger.info(f"检测到代理设置: {self.proxy_url}")
        
        # 检查配置有效性
        self._check_config()
    
    def _check_config(self):
        """检查配置是否有效"""
        self.config_valid = True
        
        if not self.token:
            logger.error("未设置TELEGRAM_TOKEN环境变量")
            self.config_valid = False
        
        if not self.admin_group_id:
            logger.error("未设置TELEGRAM_ADMIN_GROUP_ID环境变量")
            self.config_valid = False
        
        if not self.admin_user_ids:
            logger.warning("未设置TELEGRAM_ADMIN_USER_IDS环境变量，将无法使用管理员命令")
        
        if self.config_valid:
            # 仅当配置有效时打印配置信息
            masked_token = f"{self.token[:5]}...{self.token[-5:]}" if self.token else None
            logger.info("Telegram客服配置检查通过")
            
    def _handle_exit(self, signum, frame):
        """处理退出信号"""
        logger.info(f"收到信号 {signum}，正在优雅退出...")
        
    def get_http_config(self):
        """获取HTTP请求配置"""
        config = {
            "timeout": self.request_timeout,
            "connection_pool_size": self.connection_pool_size,
            "read_timeout": self.request_timeout,
            "write_timeout": self.request_timeout,
            "connect_timeout": self.request_timeout
        }
        
        # 添加代理配置
        if self.proxy_url:
            config["proxy_url"] = self.proxy_url
        
        return config
        
    def get_retry_config(self):
        """获取重试配置"""
        return {
            "max_retries": self.max_retries,
            "initial_wait": self.retry_initial_wait,
            "max_wait": 60.0  # 最大等待时间(秒)
        }
        
    def log_config_info(self):
        """记录配置信息"""
        if not self.token:
            return
            
        masked_token = f"{self.token[:5]}...{self.token[-5:]}"
        logger.info("============= 配置信息 =============")
        logger.info(f"机器人Token: {masked_token}")
        logger.info(f"管理群组ID: {self.admin_group_id}")
        logger.info(f"管理员ID: {', '.join(map(str, self.admin_user_ids))}")
        if self.proxy_url:
            logger.info(f"使用代理: {self.proxy_url}")
        logger.info("====================================")

# 创建全局配置实例
telegram_config = TelegramConfig()

# 导出实例
__all__ = ["telegram_config"]

# 管理权限检查说明
permission_notes = """
注意事项:
1. 管理群组必须是超级群组(Supergroup)
2. 管理群组必须启用话题功能(Forum)
3. 机器人必须是群组管理员
4. 机器人必须有管理话题的权限
5. 同一时间只能运行一个Bot实例

如果遇到错误:
- "Chat not found" - 检查群组类型和话题设置
- "terminated by other getUpdates request" - 有多个Bot实例在运行
"""
 