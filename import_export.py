"""数据导入导出"""
import io
import base64
import pandas as pd
from datetime import date
from collections import defaultdict
from database import get_session
from models import Student, Exam, ExamSubject, ExamScore, ExamRanking
from config import ALL_SUBJECT_GROUPS


def _read_csv_smart(file_bytes: bytes) -> pd.DataFrame:
    """智能读取 CSV：依次尝试 utf-8-sig, gbk, gb2312, gb18030, utf-8"""
    encodings = ['utf-8-sig', 'gbk', 'gb18030', 'gb2312', 'utf-8', 'latin-1']
    for enc in encodings:
        try:
            return pd.read_csv(io.BytesIO(file_bytes), dtype=str, encoding=enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    # 全失败，用 utf-8-sig 让 pandas 报原始错
    return pd.read_csv(io.BytesIO(file_bytes), dtype=str, encoding='utf-8-sig')


# ── 学生导入 ────────────────────────────────────────────

def parse_student_file(file_bytes: bytes, filename: str) -> tuple[pd.DataFrame, list[dict]]:
    """解析学生文件，返回 (DataFrame, 错误列表)"""
    errors = []

    try:
        if filename.endswith('.csv'):
            df = _read_csv_smart(file_bytes)
        else:
            df = pd.read_excel(io.BytesIO(file_bytes), dtype=str)
    except Exception as e:
        return pd.DataFrame(), [{"line": 0, "reason": f"文件解析失败: {e}"}]

    # 标准化列名
    df.columns = df.columns.str.strip()
    required = ["学号", "姓名", "班级"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return df, [{"line": 0, "reason": f"缺少列: {missing}"}]

    # 校验
    session = get_session()
    existing_ids = {s.student_id for s in session.query(Student.student_id).all()}
    session.close()

    for idx, row in df.iterrows():
        line_no = idx + 2  # +1 for 0-index, +1 for header
        sid = str(row.get("学号", "")).strip()
        name = str(row.get("姓名", "")).strip()
        cls = str(row.get("班级", "")).strip()

        if not sid or not name or not cls:
            if not sid and not name and not cls:
                errors.append({"line": line_no, "reason": "空行"})
            else:
                errors.append({"line": line_no, "reason": "存在空值（学号/姓名/班级必填）"})
            continue

        if sid in existing_ids:
            errors.append({"line": line_no, "reason": f"学号 {sid} 已存在"})
            continue
        existing_ids.add(sid)  # 文件内去重

    return df, errors


def import_students(df: pd.DataFrame, errors: list[dict]) -> tuple[int, int]:
    """执行学生导入，返回 (成功数, 跳过数)"""
    error_lines = {e["line"] for e in errors}
    session = get_session()
    success = 0
    skipped = 0

    try:
        for idx, row in df.iterrows():
            line_no = idx + 2
            if line_no in error_lines:
                skipped += 1
                continue

            sid = str(row["学号"]).strip()
            name = str(row["姓名"]).strip()
            cls = str(row["班级"]).strip()

            if not sid or not name or not cls:
                skipped += 1
                continue

            session.add(Student(student_id=sid, name=name, class_name=cls))
            success += 1
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return success, skipped


def generate_student_template() -> bytes:
    """生成学生导入模板"""
    df = pd.DataFrame(columns=["学号", "姓名", "班级"])
    output = io.BytesIO()
    df.to_csv(output, index=False, encoding='utf-8-sig')
    return output.getvalue()


# ── 考试管理 ────────────────────────────────────────────

def create_exam(name: str, exam_type: str, exam_date: date,
                subjects: list[dict]) -> Exam:
    """
    创建考试
    subjects: [{"name": "语文", "group": "语文", "max": 150}, ...]
    """
    session = get_session()
    try:
        existing = session.query(Exam).filter_by(name=name).first()
        if existing:
            raise ValueError(f"考试名称 '{name}' 已存在")

        exam = Exam(name=name, exam_type=exam_type, exam_date=exam_date)
        session.add(exam)
        session.flush()

        for subj in subjects:
            session.add(ExamSubject(
                exam_id=exam.id,
                subject_name=subj["name"],
                subject_group=subj["group"],
                max_score=subj["max"],
            ))

        session.commit()
        session.refresh(exam)
        return exam
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_exam_subject_map(exam_id: int, session=None) -> dict:
    """返回 {subject_name: ExamSubject}"""
    close = False
    if session is None:
        session = get_session()
        close = True
    try:
        subs = session.query(ExamSubject).filter_by(exam_id=exam_id).all()
        return {s.subject_name: s for s in subs}
    finally:
        if close:
            session.close()


# ── 成绩导入 ────────────────────────────────────────────

def parse_score_file(file_bytes: bytes, filename: str, exam_id: int) -> tuple[pd.DataFrame, list[dict]]:
    """解析成绩文件，返回 (DataFrame, 错误列表)"""
    errors = []

    try:
        if filename.endswith('.csv'):
            df = _read_csv_smart(file_bytes)
        else:
            df = pd.read_excel(io.BytesIO(file_bytes), dtype=str)
    except Exception as e:
        return pd.DataFrame(), [{"line": 0, "reason": f"文件解析失败: {e}"}]

    df.columns = df.columns.str.strip()

    if "学号" not in df.columns:
        return df, [{"line": 0, "reason": "缺少「学号」列"}]

    session = get_session()
    try:
        subj_map = get_exam_subject_map(exam_id, session)
        existing_students = {s.student_id: s for s in session.query(Student).all()}

        subj_names = set(subj_map.keys())
        # 检查科目列是否匹配
        score_cols = [c for c in df.columns if c != "学号" and c != "姓名"]
        unknown = [c for c in score_cols if c not in subj_names]
        if unknown:
            errors.append({"line": 0, "reason": f"未识别的科目列: {unknown}（当前考试科目: {list(subj_names)}）"})

        for idx, row in df.iterrows():
            line_no = idx + 2
            sid = str(row.get("学号", "")).strip()
            if not sid:
                errors.append({"line": line_no, "reason": "学号为空"})
                continue
            # 未知学号：不再报错，导入时自动创建

            # 分数校验
            for col in score_cols:
                if col not in subj_map:
                    continue
                val = row.get(col)
                if pd.isna(val) or str(val).strip() == "":
                    continue  # 缺考允许
                try:
                    score = float(val)
                    max_s = subj_map[col].max_score
                    if score < 0 or score > max_s:
                        errors.append({"line": line_no, "reason": f"{col}: {score} 超出范围 [0, {max_s}]"})
                except ValueError:
                    errors.append({"line": line_no, "reason": f"{col}: '{val}' 不是有效数字"})

        return df, errors
    finally:
        session.close()


def import_scores(df: pd.DataFrame, errors: list[dict], exam_id: int) -> tuple[int, int]:
    """导入成绩，计算排名，返回 (成功数, 跳过数)"""
    error_lines = {e["line"] for e in errors if e["line"] > 0}
    session = get_session()
    success = 0
    skipped = 0

    try:
        exam = session.query(Exam).filter_by(id=exam_id).first()
        if not exam:
            raise ValueError(f"考试不存在")

        subj_map = get_exam_subject_map(exam_id, session)
        students_map = {s.student_id: s for s in session.query(Student).all()}
        score_cols = [c for c in df.columns if c in subj_map]

        # 先删旧数据
        session.query(ExamScore).filter_by(exam_id=exam_id).delete()
        session.query(ExamRanking).filter_by(exam_id=exam_id).delete()

        # 插入成绩
        student_scores = {}  # {student_db_id: [(exam_subject_id, score, group)]}
        new_students_created = 0
        for idx, row in df.iterrows():
            line_no = idx + 2
            if line_no in error_lines:
                skipped += 1
                continue

            sid = str(row["学号"]).strip()

            # 自动创建学生（学号不存在时）
            if sid not in students_map:
                name = str(row.get("姓名", "")).strip() or f"学生{sid}"
                cls = str(row.get("班级", "")).strip() or "未分班"
                new_stu = Student(student_id=sid, name=name, class_name=cls)
                session.add(new_stu)
                session.flush()
                students_map[sid] = new_stu
                new_students_created += 1

            student = students_map[sid]
            if student.id not in student_scores:
                student_scores[student.id] = []

            for col in score_cols:
                esubj = subj_map[col]
                val = row.get(col)
                if pd.isna(val) or str(val).strip() == "":
                    score_val = None  # 缺考
                else:
                    score_val = float(val)

                session.add(ExamScore(
                    exam_id=exam_id,
                    student_id=student.id,
                    exam_subject_id=esubj.id,
                    score=score_val,
                ))
                student_scores[student.id].append((esubj, score_val))
            success += 1

        session.flush()

        # 计算排名：按班级分组，每组内按总分排名
        # 请假学生（全部科目为空）不参与排名
        class_students = defaultdict(list)
        for sid_key, stu in students_map.items():
            if stu.id in student_scores:
                # 判断是否请假：该生所有科目分数均为 None
                scores_list = student_scores[stu.id]
                all_empty = all(s[1] is None for s in scores_list)
                if all_empty:
                    continue  # 请假，不参与排名
                class_students[stu.class_name].append(stu)

        # 按班级计算排名
        for class_name, students_in_class in class_students.items():
            # 总分排名
            total_scores = []
            for stu in students_in_class:
                if stu.id not in student_scores:
                    continue
                # 总分 = 所有科目分数之和（缺考计0）
                total = sum(s[1] or 0 for s in student_scores[stu.id])
                total_scores.append((stu.id, total))
            total_scores.sort(key=lambda x: x[1], reverse=True)

            # 排名（相同分数同排名）
            current_rank = 1
            prev_score = None
            same_count = 0
            for i, (sid, ts) in enumerate(total_scores):
                if ts == prev_score:
                    same_count += 1
                else:
                    current_rank += same_count
                    same_count = 1
                prev_score = ts
                session.add(ExamRanking(
                    exam_id=exam_id,
                    student_id=sid,
                    subject_group=None,
                    total_score=ts,
                    rank=current_rank,
                ))

            # 各科目组排名
            for sg in ALL_SUBJECT_GROUPS:
                sg_scores = []
                for stu in students_in_class:
                    if stu.id not in student_scores:
                        continue
                    # 该科目组总分
                    sg_total = sum(
                        (s[1] or 0) for s in student_scores[stu.id]
                        if s[0].subject_group == sg
                    )
                    sg_scores.append((stu.id, sg_total))
                if not sg_scores:
                    continue
                sg_scores.sort(key=lambda x: x[1], reverse=True)

                current_rank = 1
                prev_score = None
                same_count = 0
                for i, (sid, ts) in enumerate(sg_scores):
                    if ts == prev_score:
                        same_count += 1
                    else:
                        current_rank += same_count
                        same_count = 1
                    prev_score = ts
                    session.add(ExamRanking(
                        exam_id=exam_id,
                        student_id=sid,
                        subject_group=sg,
                        total_score=ts,
                        rank=current_rank,
                    ))

        session.commit()
        return success, skipped
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()





def generate_score_template(exam_id: int) -> bytes:
    """生成成绩导入模板（基于考试科目配置）"""
    session = get_session()
    try:
        exam = session.query(Exam).filter_by(id=exam_id).first()
        if not exam:
            raise ValueError("考试不存在")

        subs = session.query(ExamSubject).filter_by(exam_id=exam_id).order_by(ExamSubject.subject_group, ExamSubject.subject_name).all()

        columns = ["学号", "姓名"] + [s.subject_name for s in subs]
        df = pd.DataFrame(columns=columns)

        # 加一行示例
        example = {"学号": "20240001", "姓名": "张三"}
        for s in subs:
            example[s.subject_name] = f"0~{int(s.max_score)}"
        df.loc[0] = example

        output = io.BytesIO()
        df.to_csv(output, index=False, encoding='utf-8-sig')
        return output.getvalue()
    finally:
        session.close()


# ── 导出 ────────────────────────────────────────────────

def export_ratings_excel(ratings: dict) -> bytes:
    """导出 Rating 榜为 Excel"""
    session = get_session()
    try:
        from rating import get_rating_tier

        rows = []
        for sid, rdict in ratings.items():
            stu = session.query(Student).filter_by(id=sid).first()
            if not stu:
                continue
            overall = rdict.get("overall", 0)
            row = {
                "学号": stu.student_id,
                "姓名": stu.name,
                "班级": stu.class_name,
                "总分Rating": overall,
                "评级": get_rating_tier(overall),
            }
            for sg in ALL_SUBJECT_GROUPS:
                row[f"{sg}Rating"] = rdict.get(sg, 0)
            rows.append(row)

        rows.sort(key=lambda r: r["总分Rating"], reverse=True)
        df = pd.DataFrame(rows)

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name="Rating榜")
        return output.getvalue()
    finally:
        session.close()


def export_db_dump() -> bytes:
    """导出 SQLite 数据库"""
    import shutil, tempfile, os
    from database import DB_PATH

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
    tmp.close()
    try:
        shutil.copy2(DB_PATH, tmp.name)
        with open(tmp.name, 'rb') as f:
            return f.read()
    finally:
        os.unlink(tmp.name)
