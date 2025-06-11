from sqlalchemy import create_engine, inspect, Table, Column, MetaData, Boolean, Integer, String, DateTime, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
import logging
from dotenv import load_dotenv

# 设置日志
logger = logging.getLogger(__name__)

# 加载环境变量
load_dotenv()

# 从环境变量中获取数据库URL，如果没有则使用SQLite
SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL", "sqlite:///./telegram_customer_service.db"
)

# 创建数据库引擎
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)

# 创建会话
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 创建模型基类
Base = declarative_base()

# 依赖项，用于获取数据库会话
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def auto_migrate():
    """自动检查并更新数据库结构以匹配模型定义"""
    try:
        logger.info("开始检查数据库结构...")
        
        # 获取检查器
        inspector = inspect(engine)
        
        # 定义模型与表名的映射
        model_table_map = {
            'User': 'user',
            'FormnStatus': 'formn_status',
            'MessageMap': 'message_map',
            'MediaGroupMessage': 'media_group_message'
        }
        
        # 连接数据库
        connection = engine.connect()
        
        for model_name, table_name in model_table_map.items():
            # 检查表是否存在
            if table_name in inspector.get_table_names():
                # 获取表中已有的列
                existing_columns = {column['name']: column for column in inspector.get_columns(table_name)}
                
                # 根据模型获取应有的列
                if model_name == 'FormnStatus':
                    # 特别处理FormnStatus模型
                    expected_columns = {
                        'id': {'type': 'INTEGER', 'primary_key': True},
                        'user_id': {'type': 'INTEGER', 'unique': False},
                        'topic_id': {'type': 'INTEGER', 'unique': True},
                        'topic_name': {'type': 'VARCHAR', 'unique': False},
                        'status': {'type': 'VARCHAR', 'default': 'opened'},
                        'is_system_topic': {'type': 'BOOLEAN', 'default': False},
                        'from_group': {'type': 'BOOLEAN', 'default': False},
                        'source_group_id': {'type': 'INTEGER', 'nullable': True},
                        'source_group_name': {'type': 'VARCHAR', 'nullable': True},
                        'created_at': {'type': 'TIMESTAMP'},
                        'updated_at': {'type': 'TIMESTAMP'}
                    }
                    
                    # 检查缺少的列
                    for col_name, col_info in expected_columns.items():
                        if col_name not in existing_columns:
                            logger.info(f"表 {table_name} 缺少列 {col_name}，正在添加...")
                            
                            # 构建列定义
                            col_def = f"{col_name} {col_info['type']}"
                            if col_info.get('default') is not None:
                                if isinstance(col_info['default'], bool):
                                    default_val = '1' if col_info['default'] else '0'
                                    col_def += f" DEFAULT {default_val}"
                                else:
                                    col_def += f" DEFAULT '{col_info['default']}'"
                            
                            # 添加列
                            try:
                                connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_def}"))
                                connection.commit()
                                logger.info(f"成功添加列 {col_name} 到表 {table_name}")
                            except Exception as e:
                                logger.error(f"添加列 {col_name} 到表 {table_name} 失败: {str(e)}")
                    
                    # 检查user_id的唯一约束
                    has_unique_constraint = False
                    
                    # 检查索引
                    for index in inspector.get_indexes(table_name):
                        if 'user_id' in index['column_names'] and len(index['column_names']) == 1 and index.get('unique', False):
                            has_unique_constraint = True
                            break
                    
                    # 检查约束
                    if not has_unique_constraint:
                        for constraint in inspector.get_unique_constraints(table_name):
                            if 'user_id' in constraint['column_names'] and len(constraint['column_names']) == 1:
                                has_unique_constraint = True
                                break
                    
                    # 如果存在唯一约束，需要移除它
                    if has_unique_constraint:
                        logger.info(f"表 {table_name} 的 user_id 列有唯一约束，正在移除...")
                        
                        try:
                            # 检查临时表是否存在
                            if f"{table_name}_new" in inspector.get_table_names():
                                logger.info(f"检测到临时表 {table_name}_new，尝试删除...")
                                connection.execute(text(f"DROP TABLE IF EXISTS {table_name}_new"))
                                connection.commit()
                                logger.info(f"成功删除临时表 {table_name}_new")
                            
                            # SQLite不支持直接删除约束，需要重建表
                            # 1. 创建新表
                            connection.execute(text(f"""
                                CREATE TABLE {table_name}_new (
                                    id INTEGER PRIMARY KEY,
                                    user_id INTEGER,
                                    topic_id INTEGER UNIQUE,
                                    topic_name VARCHAR,
                                    status VARCHAR,
                                    is_system_topic BOOLEAN,
                                    from_group BOOLEAN DEFAULT 0,
                                    source_group_id INTEGER,
                                    source_group_name VARCHAR,
                                    created_at TIMESTAMP,
                                    updated_at TIMESTAMP
                                )
                            """))
                            
                            # 2. 复制数据
                            # 检查is_system_topic和from_group是否存在
                            if 'is_system_topic' in existing_columns and 'from_group' in existing_columns:
                                connection.execute(text(f"""
                                    INSERT INTO {table_name}_new 
                                    SELECT id, user_id, topic_id, topic_name, status, 
                                           is_system_topic, from_group, source_group_id, source_group_name,
                                           created_at, updated_at 
                                    FROM {table_name}
                                """))
                            elif 'is_system_topic' in existing_columns:
                                connection.execute(text(f"""
                                    INSERT INTO {table_name}_new 
                                    SELECT id, user_id, topic_id, topic_name, status, 
                                           is_system_topic, 0, NULL, NULL,
                                           created_at, updated_at 
                                    FROM {table_name}
                                """))
                            else:
                                connection.execute(text(f"""
                                    INSERT INTO {table_name}_new 
                                    SELECT id, user_id, topic_id, topic_name, status, 
                                           0, 0, NULL, NULL,
                                           created_at, updated_at 
                                    FROM {table_name}
                                """))
                            
                            # 3. 删除旧表
                            connection.execute(text(f"DROP TABLE {table_name}"))
                            
                            # 4. 重命名新表
                            connection.execute(text(f"ALTER TABLE {table_name}_new RENAME TO {table_name}"))
                            
                            # 5. 重建索引
                            connection.execute(text(f"CREATE INDEX ix_{table_name}_user_id ON {table_name} (user_id)"))
                            connection.execute(text(f"CREATE UNIQUE INDEX ix_{table_name}_topic_id ON {table_name} (topic_id)"))
                            connection.execute(text(f"CREATE INDEX ix_{table_name}_topic_name ON {table_name} (topic_name)"))
                            
                            # 提交更改
                            connection.commit()
                            
                            logger.info(f"成功移除表 {table_name} 的 user_id 列的唯一约束")
                        except Exception as e:
                            logger.error(f"移除表 {table_name} 的 user_id 列的唯一约束失败: {str(e)}")
                
                # 处理 User 表
                elif model_name == 'User':
                    # 检查是否有 last_group_id 列
                    if 'last_group_id' not in existing_columns:
                        logger.info(f"表 {table_name} 缺少列 last_group_id，正在添加...")
                        try:
                            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN last_group_id INTEGER"))
                            connection.commit()
                            logger.info(f"成功添加列 last_group_id 到表 {table_name}")
                        except Exception as e:
                            logger.error(f"添加列 last_group_id 到表 {table_name} 失败: {str(e)}")
                    
                    # 检查是否有 last_group_name 列
                    if 'last_group_name' not in existing_columns:
                        logger.info(f"表 {table_name} 缺少列 last_group_name，正在添加...")
                        try:
                            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN last_group_name VARCHAR"))
                            connection.commit()
                            logger.info(f"成功添加列 last_group_name 到表 {table_name}")
                        except Exception as e:
                            logger.error(f"添加列 last_group_name 到表 {table_name} 失败: {str(e)}")
                
                # 处理 MessageMap 表
                if model_name == 'MessageMap':
                    # 检查是否有 is_unread_topic 列
                    if 'is_unread_topic' not in existing_columns:
                        logger.info(f"表 {table_name} 缺少列 is_unread_topic，正在添加...")
                        try:
                            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN is_unread_topic BOOLEAN DEFAULT 0"))
                            connection.commit()
                            logger.info(f"成功添加列 is_unread_topic 到表 {table_name}")
                        except Exception as e:
                            logger.error(f"添加列 is_unread_topic 到表 {table_name} 失败: {str(e)}")
                    
                    # 检查是否有 handled_by_user_id 列
                    if 'handled_by_user_id' not in existing_columns:
                        logger.info(f"表 {table_name} 缺少列 handled_by_user_id，正在添加...")
                        try:
                            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN handled_by_user_id INTEGER"))
                            connection.commit()
                            logger.info(f"成功添加列 handled_by_user_id 到表 {table_name}")
                        except Exception as e:
                            logger.error(f"添加列 handled_by_user_id 到表 {table_name} 失败: {str(e)}")
                    
                    # 检查是否有 handled_time 列
                    if 'handled_time' not in existing_columns:
                        logger.info(f"表 {table_name} 缺少列 handled_time，正在添加...")
                        try:
                            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN handled_time TIMESTAMP"))
                            connection.commit()
                            logger.info(f"成功添加列 handled_time 到表 {table_name}")
                        except Exception as e:
                            logger.error(f"添加列 handled_time 到表 {table_name} 失败: {str(e)}")
                    
                    # 检查是否有 unread_topic_message_id 列
                    if 'unread_topic_message_id' not in existing_columns:
                        logger.info(f"表 {table_name} 缺少列 unread_topic_message_id，正在添加...")
                        try:
                            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN unread_topic_message_id INTEGER"))
                            connection.commit()
                            logger.info(f"成功添加列 unread_topic_message_id 到表 {table_name}")
                        except Exception as e:
                            logger.error(f"添加列 unread_topic_message_id 到表 {table_name} 失败: {str(e)}")
                    
                    # 检查是否有 is_from_group 列
                    if 'is_from_group' not in existing_columns:
                        logger.info(f"表 {table_name} 缺少列 is_from_group，正在添加...")
                        try:
                            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN is_from_group BOOLEAN DEFAULT 0"))
                            connection.commit()
                            logger.info(f"成功添加列 is_from_group 到表 {table_name}")
                        except Exception as e:
                            logger.error(f"添加列 is_from_group 到表 {table_name} 失败: {str(e)}")
                    
                    # 检查是否有 source_group_id 列
                    if 'source_group_id' not in existing_columns:
                        logger.info(f"表 {table_name} 缺少列 source_group_id，正在添加...")
                        try:
                            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN source_group_id INTEGER"))
                            connection.commit()
                            logger.info(f"成功添加列 source_group_id 到表 {table_name}")
                        except Exception as e:
                            logger.error(f"添加列 source_group_id 到表 {table_name} 失败: {str(e)}")
                    
                    # 检查是否有 source_group_name 列
                    if 'source_group_name' not in existing_columns:
                        logger.info(f"表 {table_name} 缺少列 source_group_name，正在添加...")
                        try:
                            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN source_group_name VARCHAR"))
                            connection.commit()
                            logger.info(f"成功添加列 source_group_name 到表 {table_name}")
                        except Exception as e:
                            logger.error(f"添加列 source_group_name 到表 {table_name} 失败: {str(e)}")
        
        # 关闭连接
        connection.close()
        
        logger.info("数据库结构检查完成")
        return True
    except Exception as e:
        logger.error(f"自动迁移数据库失败: {str(e)}")
        return False 