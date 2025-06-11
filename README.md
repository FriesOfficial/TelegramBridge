# Telegram客服系统

基于[python-telegram-bot](https://docs.python-telegram-bot.org/en/stable/)官方库构建的客服系统，采用单一入口点设计。

## 功能特点

- 用户可以通过机器人发送消息，消息会被转发到管理员群组
- 管理员可以在群组中回复用户消息
- 支持多种媒体类型的消息转发（图片、视频、文件等）
- 提供话题管理功能，每个用户自动创建单独的话题
- 支持广播功能，可以向所有用户发送通知

## 系统要求

- Python 3.9+
- python-telegram-bot 20.0+
- 有效的Telegram Bot Token
- 管理员群组（需启用话题功能）

## 安装步骤

pyinstaller --onefile --add-data "app:app" --hidden-import=dotenv telegram_bot.py

1. 克隆项目并进入目录
```bash
git clone <repository-url>
cd python-telegram-bot
```

2. 安装依赖
```bash
pip install -r requirements.txt
```

3. 配置环境变量
创建`.env`文件，添加以下内容：
```
TELEGRAM_TOKEN=your_bot_token
TELEGRAM_ADMIN_GROUP_ID=your_admin_group_id
TELEGRAM_ADMIN_USER_IDS=user_id1,user_id2
```

## 使用方法

### 启动客服系统

使用单一入口点启动整个系统：

```bash
python telegram_bot.py
```

### 命令行参数

- `--debug`: 启用调试模式，显示更详细的日志
- `--db-only`: 仅初始化数据库，不启动机器人

### 管理员命令

在管理员群组中可用的命令：

- `/clear`: 清除当前话题
- `/broadcast`: 向所有用户广播消息 (需回复要广播的消息)

### 用户命令

用户可以使用的命令：

- `/start`: 开始使用客服系统
- `/help`: 显示帮助信息

## 数据库结构

系统使用SQLite数据库存储以下信息：

- 用户信息
- 消息映射（用户消息和管理员消息的对应关系）
- 话题状态
- 媒体组消息

## 项目结构

```
python-telegram-bot/
├── app/
│   ├── database/           # 数据库模块
│   ├── models/             # 数据模型
│   ├── config/             # 配置模块
│   └── telegram/           # Telegram机器人相关模块
├── assets/                 # 资源文件
│   └── imgs/               # 图片资源
├── telegram_bot.py         # 单一入口点
└── requirements.txt        # 依赖文件
```

## 故障排除

如果遇到"terminated by other getUpdates request"错误，表示有多个Bot实例同时运行。请确保只有一个实例在运行：

```bash
# 检查是否有多个实例在运行
ps aux | grep telegram_bot.py

# 如需停止所有实例
pkill -f telegram_bot.py
```

## 许可证

本项目采用MIT许可证。
 