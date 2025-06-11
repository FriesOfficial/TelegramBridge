"""
主应用模块，集成FastAPI与Telegram客服系统
"""
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
import os
from dotenv import load_dotenv

# 导入数据库和模型
from app.database.database import Base, engine, SessionLocal, get_db
from app.models import User, MediaGroupMessage, FormnStatus, MessageMap

# 导入Telegram集成模块
from app.telegram.integration import setup_telegram_customer_service, cleanup_telegram_customer_service

# 加载环境变量
load_dotenv()

# 创建所有数据库表
Base.metadata.create_all(bind=engine)

# 创建应用
app = FastAPI(
    title="Telegram客服系统API",
    description="基于FastAPI的Telegram客服系统API",
    version="1.0.0",
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源
    allow_credentials=True,
    allow_methods=["*"],  # 允许所有方法
    allow_headers=["*"],  # 允许所有头
)

# 启动时初始化Telegram客服系统
@app.on_event("startup")
async def startup_event():
    """应用启动时执行"""
    # 初始化Telegram客服系统
    setup_telegram_customer_service()

# 关闭时清理资源
@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭时执行"""
    # 清理Telegram客服系统
    cleanup_telegram_customer_service()

# 路由：首页
@app.get("/")
async def read_root():
    """首页"""
    return {"message": "欢迎使用Telegram客服系统API"}

# 路由：用户列表
@app.get("/users/")
async def read_users(skip: int = 0, limit: int = 100, db = Depends(get_db)):
    """获取所有用户"""
    users = db.query(User).offset(skip).limit(limit).all()
    return users

# 路由：用户详情
@app.get("/users/{user_id}")
async def read_user(user_id: int, db = Depends(get_db)):
    """获取指定用户"""
    user = db.query(User).filter(User.user_id == user_id).first()
    if user is None:
        return {"error": "用户不存在"}
    return user 