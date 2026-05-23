"""数据库连接与会话管理"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# 相对路径：db 落在当前工作目录（exe 旁 / 项目根目录）
DB_PATH = os.path.join(os.getcwd(), "student_rating.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, echo=False, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


def init_db():
    """创建所有表并初始化默认配置"""
    from models import Config  # noqa: F401
    Base.metadata.create_all(bind=engine)

    session = SessionLocal()
    try:
        defaults = {
            "decay_lambda": "0.3",
            "type_weight_周考": "0.25",
            "type_weight_月考": "0.50",
            "type_weight_期中": "0.75",
            "type_weight_期末": "0.75",
        }
        for k, v in defaults.items():
            existing = session.query(Config).filter_by(key=k).first()
            if not existing:
                session.add(Config(key=k, value=v))
        session.commit()
    finally:
        session.close()


def get_session():
    """获取数据库会话"""
    return SessionLocal()
