"""配置管理：考试类型权重、衰减系数、科目数权重"""
from database import get_session
from models import Config

# 科目组常量
ALL_SUBJECT_GROUPS = ["语文", "数学", "英语", "二选一", "四选二A", "四选二B"]
MAX_SUBJECT_GROUPS = 6  # 完整考试的科目组数

# 默认权重（周考=期中×1/3）
DEFAULT_TYPE_WEIGHTS = {"周考": 0.25, "月考": 0.50, "期中": 0.75, "期末": 0.75}
DEFAULT_DECAY_LAMBDA = 0.3


def get_decay_lambda(session=None) -> float:
    close = False
    if session is None:
        session = get_session()
        close = True
    try:
        cfg = session.query(Config).filter_by(key="decay_lambda").first()
        return float(cfg.value) if cfg else DEFAULT_DECAY_LAMBDA
    finally:
        if close:
            session.close()


def set_decay_lambda(value: float):
    session = get_session()
    try:
        cfg = session.query(Config).filter_by(key="decay_lambda").first()
        if cfg:
            cfg.value = str(value)
        else:
            session.add(Config(key="decay_lambda", value=str(value)))
        session.commit()
    finally:
        session.close()


def get_type_weights(session=None) -> dict:
    close = False
    if session is None:
        session = get_session()
        close = True
    weights = {}
    try:
        for exam_type in ["周考", "月考", "期中", "期末"]:
            cfg = session.query(Config).filter_by(key=f"type_weight_{exam_type}").first()
            weights[exam_type] = float(cfg.value) if cfg else DEFAULT_TYPE_WEIGHTS[exam_type]
    finally:
        if close:
            session.close()
    return weights


def set_type_weight(exam_type: str, weight: float):
    session = get_session()
    try:
        cfg = session.query(Config).filter_by(key=f"type_weight_{exam_type}").first()
        if cfg:
            cfg.value = str(weight)
        else:
            session.add(Config(key=f"type_weight_{exam_type}", value=str(weight)))
        session.commit()
    finally:
        session.close()


def get_subject_count_weight(exam_subject_group_count: int) -> float:
    """科目数权重：若考试科目组少于6个，权重按比例降低"""
    if exam_subject_group_count <= 0:
        return 0.0
    return min(exam_subject_group_count / MAX_SUBJECT_GROUPS, 1.0)
