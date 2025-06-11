# TelegramBridge - Telegram 双向客服系统

基于 Python-Telegram-Bot 构建的专业双向客服系统，为 Telegram 用户和客服人员提供实时双向通信的解决方案。

[English Documentation](README.en.md)

## 功能特点

- **双向实时通信**：在用户和客服人员之间无缝双向转发消息
- **话题式组织**：自动将用户对话组织到论坛话题中
- **未读消息系统**：突出显示未读消息，确保每个咨询都得到处理
- **多媒体支持**：处理包括照片、视频、文档在内的各种媒体类型
- **用户管理**：通过简单操作封禁/解封用户和标记消息为已读
- **会员用户识别**：自动识别 Telegram Premium 会员用户

## 系统要求

- Python 3.7+
- Telegram Bot Token（从 [@BotFather](https://t.me/BotFather) 获取）
- 已启用论坛话题功能的 Telegram 超级群组
- 机器人在超级群组中的管理员权限

## 安装方法

1. 克隆仓库
```bash
git clone https://github.com/FriesOfficial/TelegramBridge.git
cd TelegramBridge
```

2. 安装依赖
```bash
pip install -r requirements.txt
```

3. 在项目根目录创建 `.env` 文件，添加以下变量：
```
TELEGRAM_TOKEN=从botfather获取的机器人令牌
TELEGRAM_ADMIN_GROUP_ID=管理群组ID
TELEGRAM_ADMIN_USER_IDS=管理员1ID,管理员2ID
```

### 获取 Telegram ID

要获取群组 ID 和个人 ID，可以使用 [@GetTheirIDBot](https://t.me/GetTheirIDBot) 机器人：

1. **获取个人 ID**：
   - 在 Telegram 中搜索并打开 [@GetTheirIDBot](https://t.me/GetTheirIDBot)
   - 向机器人发送任意消息
   - 机器人将回复您的个人 ID

2. **获取群组 ID**：
   - 将 [@GetTheirIDBot](https://t.me/GetTheirIDBot) 添加到您的管理群组
   - 在群组中发送 `/id` 命令
   - 机器人将回复群组的 ID
   - 获取 ID 后，您可以将机器人从群组中移除

记录这些 ID 并在 `.env` 文件中正确配置 `TELEGRAM_ADMIN_GROUP_ID` 和 `TELEGRAM_ADMIN_USER_IDS`。

## 配置说明

### 必要环境变量

- `TELEGRAM_TOKEN`：从 BotFather 获取的 Telegram Bot 令牌
- `TELEGRAM_ADMIN_GROUP_ID`：管理员群组 ID（必须是启用了论坛话题功能的超级群组）
- `TELEGRAM_ADMIN_USER_IDS`：管理员用户 ID，以逗号分隔

### 可选环境变量

- `TELEGRAM_APP_NAME`：应用名称（默认："客服系统"）
- `TELEGRAM_WELCOME_MESSAGE`：用户欢迎消息
- `TELEGRAM_REQUEST_TIMEOUT`：API 请求超时时间（秒）（默认：30）
- `TELEGRAM_CONNECTION_POOL_SIZE`：连接池大小（默认：100）

## 使用方法

### 启动机器人

```bash
python telegram_bot.py
```

### 命令行选项

- `--debug`：启用调试模式，显示更详细的日志
- `--env`：指定自定义 .env 文件路径

### 管理员命令

- `/start`：初始化机器人
- `/help`：显示帮助信息
- `/reload_config`：从 .env 文件重新加载配置

### 用户交互流程

1. 用户通过发送任意消息开始与机器人的对话
2. 消息会被转发到管理员群组中为该用户专门创建的话题
3. 管理员在话题中回复，回复会被转发回用户
4. 未读消息会出现在单独的系统话题中，直到被标记为已读

## 数据库

系统默认使用 SQLAlchemy 与 SQLite。机器人启动时会自动创建数据表。数据库文件存储在项目目录中。

## 目录结构

```
python-telegram-bot/
├── telegram_bot.py       # 主入口点
├── app/
│   ├── config/           # 配置文件
│   ├── database/         # 数据库模型和连接
│   ├── models/           # 数据模型
│   ├── schemas/          # Pydantic 模式
│   └── telegram/         # Telegram 机器人逻辑
├── assets/
│   └── imgs/             # 图片资源
└── .env                  # 环境变量
```

## 故障排除

### 常见问题

1. **"terminated by other getUpdates request" 错误**
   - 原因：多个机器人实例同时运行
   - 解决方法：确保只有一个实例在运行，使用 `ps aux | grep telegram_bot.py` 检查
   - 如果存在多个实例，使用 `pkill -f telegram_bot.py` 停止所有实例后重新启动

2. **网络超时问题**
   - 原因：网络连接不稳定或 Telegram API 暂时不可用
   - 解决方法：
     - 检查网络连接：`curl api.telegram.org`
     - 增加超时时间：设置 `TELEGRAM_REQUEST_TIMEOUT=60`
     - 配置代理：设置 `HTTPS_PROXY=http://your-proxy:port`

3. **权限问题**
   - 原因：机器人在管理群组中权限不足
   - 解决方法：
     - 确保机器人是群组的管理员
     - 验证机器人拥有管理话题的权限

## 许可证

[MIT 许可证](LICENSE)

## 贡献

欢迎贡献！请随时提交 Pull Request。 