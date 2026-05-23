"""Rating 计算 — 分科 + 总分 Rating"""
import math
from collections import defaultdict
from database import get_session
from models import Student, Exam, ExamRanking, ExamSubject
from config import (
    get_type_weights, get_decay_lambda, get_subject_count_weight,
    ALL_SUBJECT_GROUPS, MAX_SUBJECT_GROUPS
)

RATING_CACHE: dict = {}  # {(student_db_id, subject_group_or_None): rating}


def _count_class_size(exam_id: int, class_name: str, subject_group: str | None, session) -> int:
    """统计某次考试某班级某科目组的参考人数"""
    from models import Student as Stu
    return (
        session.query(ExamRanking)
        .join(Stu, ExamRanking.student_id == Stu.id)
        .filter(
            ExamRanking.exam_id == exam_id,
            Stu.class_name == class_name,
            ExamRanking.subject_group == subject_group,
        )
        .count()
    )


def _get_exam_subject_group_count(exam_id: int, session) -> int:
    """获取某次考试的科目组数量"""
    subjects = session.query(ExamSubject).filter_by(exam_id=exam_id).all()
    return len(set(s.subject_group for s in subjects))


def _calculate_rating_for_group(student_id: int, subject_group: str | None, session) -> float:
    """
    计算单个学生在某个科目组（或总分）的 Rating
    subject_group=None 表示总分 Rating
    """
    student = session.query(Student).filter_by(id=student_id).first()
    if not student:
        return 0.0

    type_weights = get_type_weights(session)
    decay_lambda = get_decay_lambda(session)

    rankings = (
        session.query(ExamRanking)
        .join(Exam, ExamRanking.exam_id == Exam.id)
        .filter(
            ExamRanking.student_id == student_id,
            ExamRanking.subject_group == subject_group,
        )
        .order_by(Exam.exam_date.asc())
        .all()
    )

    if not rankings:
        return 0.0

    N = len(rankings)
    numerator = 0.0
    denominator = 0.0

    for i, rk in enumerate(rankings):
        exam = rk.exam or session.query(Exam).filter_by(id=rk.exam_id).first()
        if not exam:
            continue

        tw = type_weights.get(exam.exam_type, 0.25)
        decay = math.exp(-decay_lambda * (N - (i + 1)))

        # 科目数权重
        subj_count = _get_exam_subject_group_count(exam.id, session)
        scw = get_subject_count_weight(subj_count)

        class_size = _count_class_size(exam.id, student.class_name, subject_group, session)
        if class_size <= 0:
            class_size = 1

        rank_score = 2000.0 * (1.0 - (rk.rank - 1) / class_size)
        rank_score = max(rank_score, 0.0)

        contribution = tw * scw * decay * rank_score
        numerator += contribution
        denominator += tw * scw * decay

    if denominator == 0:
        return 0.0

    return round(numerator / denominator, 2)


def calculate_rating_for_student(student_id: int, session=None) -> dict:
    """计算学生所有 Rating（分科 + 总分），返回 {subject_group_or_'overall': rating}"""
    close = False
    if session is None:
        session = get_session()
        close = True
    try:
        student = session.query(Student).filter_by(id=student_id).first()
        if not student:
            return {}

        ratings = {}
        for sg in ALL_SUBJECT_GROUPS:
            ratings[sg] = _calculate_rating_for_group(student_id, sg, session)
        ratings["overall"] = _calculate_rating_for_group(student_id, None, session)
        return ratings
    finally:
        if close:
            session.close()


def recalculate_all_ratings() -> dict:
    """全量重算，返回 {student_db_id: {group: rating}}"""
    session = get_session()
    try:
        students = session.query(Student).all()
        ratings = {}
        for s in students:
            ratings[s.id] = calculate_rating_for_student(s.id, session)
        global RATING_CACHE
        RATING_CACHE = ratings
        return ratings
    finally:
        session.close()


def get_rating_tier(rating: float) -> str:
    if rating >= 1800:
        return "S"
    elif rating >= 1500:
        return "A"
    elif rating >= 1200:
        return "B"
    elif rating >= 900:
        return "C"
    else:
        return "D"


def get_student_rating_history(student_id: int, subject_group: str | None = None, session=None) -> list[dict]:
    """获取 Rating 变化历史"""
    close = False
    if session is None:
        session = get_session()
        close = True
    try:
        student = session.query(Student).filter_by(id=student_id).first()
        if not student:
            return []

        type_weights = get_type_weights(session)
        decay_lambda = get_decay_lambda(session)

        rankings = (
            session.query(ExamRanking)
            .join(Exam, ExamRanking.exam_id == Exam.id)
            .filter(
                ExamRanking.student_id == student_id,
                ExamRanking.subject_group == subject_group,
            )
            .order_by(Exam.exam_date.asc())
            .all()
        )

        if not rankings:
            return []

        history = []
        cumulative = []
        for i, rk in enumerate(rankings):
            cumulative.append(rk)
            N = i + 1
            numerator = 0.0
            denominator = 0.0
            for j, crk in enumerate(cumulative):
                exam = crk.exam or session.query(Exam).filter_by(id=crk.exam_id).first()
                if not exam:
                    continue
                tw = type_weights.get(exam.exam_type, 0.25)
                decay = math.exp(-decay_lambda * (N - (j + 1)))
                scw = get_subject_count_weight(_get_exam_subject_group_count(exam.id, session))
                class_size = _count_class_size(exam.id, student.class_name, subject_group, session)
                if class_size <= 0:
                    class_size = 1
                rank_score = max(2000.0 * (1.0 - (crk.rank - 1) / class_size), 0.0)
                numerator += tw * scw * decay * rank_score
                denominator += tw * scw * decay

            rating = numerator / denominator if denominator > 0 else 0.0
            exam = rk.exam or session.query(Exam).filter_by(id=rk.exam_id).first()
            history.append({
                "exam_seq": i + 1,
                "exam_name": exam.name if exam else "",
                "exam_date": str(exam.exam_date) if exam else "",
                "rating": round(rating, 2),
                "rank": rk.rank,
                "tier": get_rating_tier(rating),
            })

        return history
    finally:
        if close:
            session.close()


def get_rating_breakdown(student_id: int, session=None) -> list[dict]:
    """总分 Rating 的贡献分解（按考试类型）"""
    close = False
    if session is None:
        session = get_session()
        close = True
    try:
        student = session.query(Student).filter_by(id=student_id).first()
        if not student:
            return []

        type_weights = get_type_weights(session)
        decay_lambda = get_decay_lambda(session)

        rankings = (
            session.query(ExamRanking)
            .join(Exam, ExamRanking.exam_id == Exam.id)
            .filter(
                ExamRanking.student_id == student_id,
                ExamRanking.subject_group == None,  # 总分
            )
            .order_by(Exam.exam_date.asc())
            .all()
        )

        if not rankings:
            return []

        N = len(rankings)
        breakdown = defaultdict(float)

        for i, rk in enumerate(rankings):
            exam = rk.exam or session.query(Exam).filter_by(id=rk.exam_id).first()
            if not exam:
                continue
            tw = type_weights.get(exam.exam_type, 0.25)
            decay = math.exp(-decay_lambda * (N - (i + 1)))
            scw = get_subject_count_weight(_get_exam_subject_group_count(exam.id, session))
            class_size = _count_class_size(exam.id, student.class_name, None, session)
            if class_size <= 0:
                class_size = 1
            rank_score = max(2000.0 * (1.0 - (rk.rank - 1) / class_size), 0.0)
            breakdown[exam.exam_type] += tw * scw * decay * rank_score

        total = sum(breakdown.values())
        result = []
        for et in ["周考", "月考", "期中", "期末"]:
            if et in breakdown:
                pct = (breakdown[et] / total * 100) if total > 0 else 0
                result.append({"exam_type": et, "value": round(breakdown[et], 2), "pct": round(pct, 1)})

        return result
    finally:
        if close:
            session.close()


def detect_anomalies(student_id: int, session=None) -> list[dict]:
    """检测排名异常波动（总分排名变化超过班级人数30%）"""
    close = False
    if session is None:
        session = get_session()
        close = True
    try:
        student = session.query(Student).filter_by(id=student_id).first()
        if not student:
            return []

        rankings = (
            session.query(ExamRanking)
            .join(Exam, ExamRanking.exam_id == Exam.id)
            .filter(
                ExamRanking.student_id == student_id,
                ExamRanking.subject_group == None,
            )
            .order_by(Exam.exam_date.asc())
            .all()
        )

        if len(rankings) < 2:
            return []

        anomalies = []
        for i in range(1, len(rankings)):
            prev_rk = rankings[i - 1]
            curr_rk = rankings[i]
            class_size = _count_class_size(curr_rk.exam_id, student.class_name, None, session)
            if class_size <= 0:
                class_size = 1
            rank_change = abs(curr_rk.rank - prev_rk.rank)
            if rank_change > class_size * 0.3:
                anomalies.append({
                    "exam_name": (curr_rk.exam or session.query(Exam).get(curr_rk.exam_id)).name,
                    "prev_rank": prev_rk.rank,
                    "curr_rank": curr_rk.rank,
                    "change": curr_rk.rank - prev_rk.rank,
                    "class_size": class_size,
                })

        return anomalies
    finally:
        if close:
            session.close()


def get_all_students_comparison(session=None) -> list[dict]:
    """获取所有学生的 Rating/排名对比（当前 vs 上次考试后），绿进红退"""
    close = False
    if session is None:
        session = get_session()
        close = True
    try:
        students = session.query(Student).all()
        results = []

        for student in students:
            # 获取总分 Rating 历史
            rankings = (
                session.query(ExamRanking)
                .join(Exam, ExamRanking.exam_id == Exam.id)
                .filter(
                    ExamRanking.student_id == student.id,
                    ExamRanking.subject_group == None,
                )
                .order_by(Exam.exam_date.asc())
                .all()
            )

            if not rankings:
                # 没有考试记录
                results.append({
                    "student_id": student.id,
                    "学号": student.student_id,
                    "姓名": student.name,
                    "班级": student.class_name,
                    "当前Rating": 0.0,
                    "上次Rating": None,
                    "Rating变动": None,
                    "当前排名": None,
                    "上次排名": None,
                    "排名变动": None,
                    "评级": "D",
                })
                continue

            # 当前 Rating（全量重算）
            current_rating = calculate_rating_for_student(student.id, session).get("overall", 0)

            # 上次 Rating：用倒数第二次考试及之前的记录重算
            prev_rating = None
            prev_rank = None
            if len(rankings) >= 2:
                # 用 rankings[: -1] 计算 Rating
                type_weights = get_type_weights(session)
                decay_lambda = get_decay_lambda(session)
                prev_rankings = rankings[:-1]
                N = len(prev_rankings)
                numerator = 0.0
                denominator = 0.0
                for i, rk in enumerate(prev_rankings):
                    exam = rk.exam or session.query(Exam).filter_by(id=rk.exam_id).first()
                    if not exam:
                        continue
                    tw = type_weights.get(exam.exam_type, 0.25)
                    decay = math.exp(-decay_lambda * (N - (i + 1)))
                    scw = get_subject_count_weight(_get_exam_subject_group_count(exam.id, session))
                    class_size = _count_class_size(exam.id, student.class_name, None, session)
                    if class_size <= 0:
                        class_size = 1
                    rank_score = max(2000.0 * (1.0 - (rk.rank - 1) / class_size), 0.0)
                    numerator += tw * scw * decay * rank_score
                    denominator += tw * scw * decay
                prev_rating = round(numerator / denominator, 2) if denominator > 0 else 0.0
                prev_rank = prev_rankings[-1].rank

            # 当前排名
            current_rank = rankings[-1].rank if rankings else None

            # 变动
            rating_change = round(current_rating - prev_rating, 2) if prev_rating is not None else None
            rank_change = (current_rank - prev_rank) if (current_rank is not None and prev_rank is not None) else None
            # 排名：数值变小=进步（绿色），变大=退步（红色）
            # Rating：变大=进步（绿色），变小=退步（红色）

            results.append({
                "student_id": student.id,
                "学号": student.student_id,
                "姓名": student.name,
                "班级": student.class_name,
                "当前Rating": current_rating,
                "上次Rating": prev_rating,
                "Rating变动": rating_change,
                "当前排名": current_rank,
                "上次排名": prev_rank,
                "排名变动": rank_change,
                "评级": get_rating_tier(current_rating),
            })

        # 按当前 Rating 降序排列
        results.sort(key=lambda r: r["当前Rating"], reverse=True)
        return results
    finally:
        if close:
            session.close()
