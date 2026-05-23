"""SQLAlchemy ORM — 支持分科 Rating 的模型"""
from sqlalchemy import (
    Column, Integer, String, Float, Date, ForeignKey, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship
from database import Base


class Student(Base):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(String(50), unique=True, nullable=False, index=True, comment="学号")
    name = Column(String(100), nullable=False, comment="姓名")
    class_name = Column(String(100), nullable=False, index=True, comment="班级")

    scores = relationship("ExamScore", back_populates="student", cascade="all, delete-orphan")
    rankings = relationship("ExamRanking", back_populates="student", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Student {self.student_id} {self.name}>"


class Exam(Base):
    __tablename__ = "exams"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), unique=True, nullable=False, comment="考试名称")
    exam_type = Column(String(20), nullable=False, index=True, comment="考试类型: 周考/月考/期中/期末")
    exam_date = Column(Date, nullable=False, index=True, comment="考试日期")

    subjects = relationship("ExamSubject", back_populates="exam", cascade="all, delete-orphan")
    scores = relationship("ExamScore", back_populates="exam", cascade="all, delete-orphan")
    rankings = relationship("ExamRanking", back_populates="exam", cascade="all, delete-orphan")

    @property
    def subject_count(self):
        """有效科目组数（去重后的 subject_group 数量）"""
        return len(set(s.subject_group for s in self.subjects))

    def __repr__(self):
        return f"<Exam {self.name} ({self.exam_type})>"


class ExamSubject(Base):
    """考试科目定义：每场考试包含哪些科目、各自满分"""
    __tablename__ = "exam_subjects"
    __table_args__ = (
        UniqueConstraint("exam_id", "subject_name", name="uq_exam_subject"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    exam_id = Column(Integer, ForeignKey("exams.id", ondelete="CASCADE"), nullable=False)
    subject_name = Column(String(100), nullable=False, comment="科目名（如「语文」「物理」）")
    subject_group = Column(String(50), nullable=False, index=True, comment="科目组：语文/数学/英语/二选一/四选二A/四选二B")
    max_score = Column(Float, nullable=False, comment="满分")

    exam = relationship("Exam", back_populates="subjects")

    def __repr__(self):
        return f"<ExamSubject {self.subject_name} [{self.subject_group}] max={self.max_score}>"


class ExamScore(Base):
    __tablename__ = "exam_scores"
    __table_args__ = (
        UniqueConstraint("exam_id", "student_id", "exam_subject_id", name="uq_exam_student_subject"),
        Index("idx_es_exam", "exam_id"),
        Index("idx_es_student", "student_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    exam_id = Column(Integer, ForeignKey("exams.id", ondelete="CASCADE"), nullable=False)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    exam_subject_id = Column(Integer, ForeignKey("exam_subjects.id", ondelete="CASCADE"), nullable=False)
    score = Column(Float, nullable=True, comment="分数 (NULL=缺考)")

    exam = relationship("Exam", back_populates="scores")
    student = relationship("Student", back_populates="scores")
    exam_subject = relationship("ExamSubject")

    def __repr__(self):
        return f"<ExamScore s={self.student_id} subj={self.exam_subject_id} score={self.score}>"


class ExamRanking(Base):
    """排名表：subject_group 为空时表示总分排名；非空表示该科目组内排名"""
    __tablename__ = "exam_rankings"
    __table_args__ = (
        UniqueConstraint("exam_id", "student_id", "subject_group", name="uq_exam_ranking"),
        Index("idx_er_exam", "exam_id"),
        Index("idx_er_student", "student_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    exam_id = Column(Integer, ForeignKey("exams.id", ondelete="CASCADE"), nullable=False)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    subject_group = Column(String(50), nullable=True, index=True, comment="科目组，NULL=总分")
    total_score = Column(Float, nullable=False, comment="总分（该组内）")
    rank = Column(Integer, nullable=False, comment="排名")

    exam = relationship("Exam", back_populates="rankings")
    student = relationship("Student", back_populates="rankings")

    def __repr__(self):
        grp = self.subject_group or "总分"
        return f"<ExamRanking e={self.exam_id} s={self.student_id} {grp} rank={self.rank}>"


class Config(Base):
    __tablename__ = "config"

    key = Column(String(100), primary_key=True)
    value = Column(String(500), nullable=False)
