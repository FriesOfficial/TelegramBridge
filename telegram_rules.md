# Telegram客服系统规则文档

## 核心原则

1. **单一入口原则**
   - 统一使用`telegram_bot.py`作为唯一入口点
   - 禁止创建多个入口脚本或使用多个shell脚本
   - 遵循python-telegram-bot官方推荐的`application.run_polling()`方法运行机器人

2. **配置集中管理**
   - 所有配置参数通过环境变量或`.env`文件设置
   - 配置逻辑集中在`app/config/telegram_config.py`中处理

3. **错误处理机制**
   - 所有网络请求都应包含适当的超时处理和重试机制
   - 必须捕获并记录所有可能的异常

## 环境变量配置

1. **必需配置项**
   - `TELEGRAM_TOKEN`: 从BotFather获取的Bot令牌
   - `TELEGRAM_ADMIN_GROUP_ID`: 管理员群组ID（必须是超级群组且启用话题功能）
   - `TELEGRAM_ADMIN_USER_IDS`: 管理员用户ID，多个ID用逗号分隔

2. **可选配置项**
   - `TELEGRAM_APP_NAME`: 应用名称，默认为"客服系统"
   - `TELEGRAM_WELCOME_MESSAGE`: 欢迎消息
   - `TELEGRAM_DISABLE_CAPTCHA`: 是否禁用验证码，默认为false
   - `TELEGRAM_MESSAGE_INTERVAL`: 消息发送间隔(秒)，默认为0
   - `TELEGRAM_REQUEST_TIMEOUT`: API请求超时时间(秒)，默认为30
   - `TELEGRAM_CONNECTION_POOL_SIZE`: 连接池大小，默认为100

## 管理群组要求

1. **群组类型**
   - 必须是超级群组(Supergroup)
   - 必须启用话题功能(Forum)

2. **Bot权限**
   - 机器人必须是群组管理员
   - 机器人必须有管理话题的权限(can_manage_topics)
   - 机器人必须有发送消息的权限

## 文件组织规范

1. **代码结构**
   - `telegram_bot.py`: 单一入口点
   - `app/telegram/bot.py`: 核心Bot逻辑和处理函数
   - `app/telegram/utils.py`: 工具函数
   - `app/config/telegram_config.py`: 配置处理
   - `app/models/`: 数据模型定义

2. **命名规范**
   - 函数名使用小写下划线命名法(snake_case)
   - 类名使用驼峰命名法(CamelCase)
   - 常量使用大写下划线命名法(UPPER_SNAKE_CASE)

## 运行规则

1. **启动方式**
   ```bash
   python telegram_bot.py [--debug] [--db-only]
   ```

2. **参数说明**
   - `--debug`: 启用调试模式，显示更详细的日志
   - `--db-only`: 仅初始化数据库，不启动机器人

## 网络问题处理规则

1. **超时处理**
   - 对所有API请求设置合理的超时时间(默认30秒)
   - 实现指数退避重试机制，初始等待时间为1秒，最大等待时间为60秒
   - 最大重试次数为3次，超过后记录错误并通知管理员

2. **连接池管理**
   - 使用连接池减少连接建立开销
   - 定期检查连接池健康状态
   - 在遇到网络问题时自动刷新连接池

3. **代理支持**
   - 支持通过环境变量`HTTPS_PROXY`配置代理
   - 当直连失败时自动尝试使用代理连接

## 故障排查指南

1. **"terminated by other getUpdates request"错误**
   - 原因：多个Bot实例同时运行
   - 解决方法：确保只有一个入口点在运行，使用`ps aux | grep telegram_bot.py`检查
   - 如有多个实例，使用`pkill -f telegram_bot.py`停止所有实例后重新启动

2. **网络超时问题**
   - 原因：网络连接不稳定或Telegram API暂时不可用
   - 解决方法：
     1. 检查网络连接：`curl api.telegram.org`
     2. 增加超时时间：设置`TELEGRAM_REQUEST_TIMEOUT=60`
     3. 配置代理：设置`HTTPS_PROXY=http://your-proxy:port`
     4. 使用VPN或代理服务

3. **权限问题**
   - 原因：Bot在群组中权限不足
   - 解决方法：
     1. 检查Bot是否为管理员
     2. 确认Bot拥有管理话题权限
     3. 使用`/permissions`命令查看Bot当前权限

## 扩展规则

1. **添加新命令**
   - 在`app/telegram/bot.py`中添加新的命令处理函数
   - 在`setup_handlers()`函数中注册新的CommandHandler
   - 更新帮助文档

2. **集成新功能**
   - 遵循模块化设计原则
   - 在添加新功能前先创建详细设计文档
   - 确保新功能不破坏现有功能的正常运行

## 安全规则

1. **令牌安全**
   - 不要在代码中硬编码Token
   - 不要将包含Token的配置文件提交到版本控制系统

2. **权限控制**
   - 仅允许指定的管理员ID执行管理命令
   - 确保机器人只能被添加到指定的管理群组

3. **数据保护**
   - 用户与管理员之间的通信应保持私密
   - 定期备份数据库以防数据丢失

## 代码规范

1. **异常处理**
   - 所有API调用都应使用try-except包裹
   - 网络超时问题应提供重试机制
   - 错误信息应记录到日志中

2. **代码风格**
   - 遵循PEP 8规范
   - 使用类型注解增强代码可读性
   - 函数和方法应有清晰的文档字符串

## 修改配置

1. **添加新配置项**
   - 在`app/config/telegram_config.py`中添加新的配置项
   - 更新环境变量说明文档
   - 确保向后兼容性 