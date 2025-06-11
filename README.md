# TelegramBridge - Telegram Two-Way Customer Service Bot

A comprehensive bidirectional customer service system built with Python-Telegram-Bot, designed to efficiently manage customer inquiries through Telegram by connecting users and service agents in real-time.

[中文文档](README.zh.md)

## Features

- **Bidirectional Communication**: Seamless two-way message forwarding between users and customer service agents
- **Topic-based Organization**: Automatically organize conversations with users in forum topics
- **Unread Message System**: Highlight unread messages to ensure no inquiry is missed
- **Media Support**: Handle various types of media including photos, videos, documents, and more
- **User Management**: Block/unblock users and mark messages as read with simple actions
- **Premium User Recognition**: Identify Telegram Premium users automatically

## Requirements

- Python 3.7+
- A Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- A Telegram Supergroup with forum topics enabled
- Admin rights for the bot in the supergroup

## Installation

1. Clone the repository
```bash
git clone https://github.com/FriesOfficial/TelegramBridge.git
cd TelegramBridge
```

2. Install dependencies
```bash
pip install -r requirements.txt
```

3. Create a `.env` file in the project root directory with the following variables:
```
TELEGRAM_TOKEN=your_bot_token_from_botfather
TELEGRAM_ADMIN_GROUP_ID=your_admin_group_id
TELEGRAM_ADMIN_USER_IDS=admin1_id,admin2_id
```

## Configuration

### Required Environment Variables

- `TELEGRAM_TOKEN`: Your Telegram Bot token from BotFather
- `TELEGRAM_ADMIN_GROUP_ID`: Admin group ID (must be a supergroup with forum topics enabled)
- `TELEGRAM_ADMIN_USER_IDS`: Admin user IDs, separated by commas

### Optional Environment Variables

- `TELEGRAM_APP_NAME`: Application name (default: "Customer Service System")
- `TELEGRAM_WELCOME_MESSAGE`: Welcome message for users
- `TELEGRAM_REQUEST_TIMEOUT`: API request timeout in seconds (default: 30)
- `TELEGRAM_CONNECTION_POOL_SIZE`: Connection pool size (default: 100)

## Usage

### Starting the Bot

```bash
python telegram_bot.py
```

### Additional Command Line Options

- `--debug`: Enable debug mode for more detailed logs
- `--env`: Specify a custom .env file path

### Admin Commands

- `/start`: Initialize the bot
- `/help`: Show help information
- `/reload_config`: Reload configuration from .env file

### User Interaction

1. Users start a conversation with the bot by sending any message
2. Messages are forwarded to the admin group in a dedicated topic for each user
3. Admins reply in the topic, and responses are forwarded back to the user
4. Unread messages appear in a separate system topic until marked as read

## Database

The system uses SQLAlchemy with SQLite by default. Tables are created automatically when the bot starts. The database files are stored in the project directory.

## Directory Structure

```
python-telegram-bot/
├── telegram_bot.py       # Main entry point
├── app/
│   ├── config/           # Configuration files
│   ├── database/         # Database models and connection
│   ├── models/           # Data models
│   ├── schemas/          # Pydantic schemas
│   └── telegram/         # Telegram bot logic
├── assets/
│   └── imgs/             # Image assets
└── .env                  # Environment variables
```

## Troubleshooting

### Common Issues

1. **"Terminated by other getUpdates request" error**
   - Cause: Multiple bot instances running simultaneously
   - Solution: Ensure only one instance is running with `ps aux | grep telegram_bot.py`
   - If multiple instances exist, stop all with `pkill -f telegram_bot.py` and restart

2. **Network Timeout Issues**
   - Cause: Unstable network connection or Telegram API unavailability
   - Solution:
     - Check your network connection: `curl api.telegram.org`
     - Increase timeout: Set `TELEGRAM_REQUEST_TIMEOUT=60`
     - Configure a proxy: Set `HTTPS_PROXY=http://your-proxy:port`

3. **Permission Issues**
   - Cause: Bot lacks required permissions in the admin group
   - Solution:
     - Ensure the bot is an administrator in the group
     - Verify the bot has permission to manage topics

## License

[MIT License](LICENSE)

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
 