"""可视化图表 — Plotly"""
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
from database import get_session
from models import Student, Exam, ExamRanking, ExamScore, ExamSubject
from config import ALL_SUBJECT_GROUPS


def _get_student_label(session, student_id: int) -> str:
    s = session.query(Student).filter_by(id=student_id).first()
    return f"{s.name}({s.student_id})" if s else str(student_id)


def chart_rating_history(rating_histories: dict) -> go.Figure:
    """学生 Rating 变化曲线（支持多学生对比）"""
    fig = go.Figure()
    for sid, history in rating_histories.items():
        if not history:
            continue
        df = pd.DataFrame(history)
        session = get_session()
        try:
            label = _get_student_label(session, sid)
        finally:
            session.close()
        fig.add_trace(go.Scatter(
            x=df["exam_seq"],
            y=df["rating"],
            mode="lines+markers",
            name=label,
            hovertemplate="考试: %{text}<br>Rating: %{y}<br>排名: 第%{customdata}名<extra></extra>",
            text=df["exam_name"],
            customdata=df["rank"],
        ))
    fig.update_layout(
        title="Rating 变化曲线",
        xaxis_title="考试序列",
        yaxis_title="Rating",
        hovermode="x unified",
        height=500,
    )
    # 评级分档水平线
    for val, tier, color in [(1800, "S", "gold"), (1500, "A", "red"), (1200, "B", "orange"),
                               (900, "C", "green")]:
        fig.add_hline(y=val, line_dash="dash", line_color=color,
                      annotation_text=tier, annotation_position="right")
    return fig


def chart_class_rating_distribution(ratings: dict, class_name: str = None) -> go.Figure:
    """班级 Rating 分布（箱线图+直方图+小提琴图三合一）"""
    session = get_session()
    try:
        data = []
        for sid, rdict in ratings.items():
            stu = session.query(Student).filter_by(id=sid).first()
            if not stu:
                continue
            if class_name and stu.class_name != class_name:
                continue
            data.append({"班级": stu.class_name, "Rating": rdict.get("overall", 0)})
        df = pd.DataFrame(data)
    finally:
        session.close()

    if df.empty:
        fig = go.Figure()
        fig.update_layout(title="暂无数据")
        return fig

    classes = sorted(df["班级"].unique())
    n_classes = len(classes)

    fig = make_subplots(
        rows=1, cols=3,
        subplot_titles=["箱线图", "直方图", "小提琴图"],
        column_widths=[0.3, 0.35, 0.35],
    )

    # 箱线图
    for cls in classes:
        cdf = df[df["班级"] == cls]
        fig.add_trace(go.Box(y=cdf["Rating"], name=cls, boxpoints="outliers"), row=1, col=1)

    # 直方图
    for cls in classes:
        cdf = df[df["班级"] == cls]
        fig.add_trace(go.Histogram(x=cdf["Rating"], name=cls, nbinsx=20, opacity=0.6), row=1, col=2)

    # 小提琴图
    for cls in classes:
        cdf = df[df["班级"] == cls]
        fig.add_trace(go.Violin(y=cdf["Rating"], name=cls, box_visible=True, meanline_visible=True), row=1, col=3)

    fig.update_layout(
        title="班级 Rating 分布",
        height=500,
        showlegend=n_classes <= 5,
        barmode="overlay",
    )
    fig.update_yaxes(title_text="Rating", row=1, col=1)
    fig.update_yaxes(title_text="人数", row=1, col=2)
    fig.update_yaxes(title_text="Rating", row=1, col=3)

    return fig


def chart_exam_heatmap(exam_id: int) -> go.Figure:
    """单次考试各科成绩热力图（学生 × 科目）"""
    session = get_session()
    try:
        exam = session.query(Exam).filter_by(id=exam_id).first()
        if not exam:
            fig = go.Figure()
            fig.update_layout(title="考试不存在")
            return fig

        scores = (
            session.query(ExamScore)
            .filter_by(exam_id=exam_id)
            .all()
        )
        if not scores:
            fig = go.Figure()
            fig.update_layout(title="无成绩数据")
            return fig

        rows = []
        for sc in scores:
            stu = sc.student or session.query(Student).get(sc.student_id)
            esubj = sc.exam_subject or session.query(ExamSubject).get(sc.exam_subject_id)
            rows.append({
                "学生": f"{stu.name}({stu.student_id})" if stu else str(sc.student_id),
                "科目": esubj.subject_name if esubj else "?",
                "科目组": esubj.subject_group if esubj else "?",
                "得分率": (sc.score / esubj.max_score * 100) if sc.score is not None and esubj else None,
            })

        df = pd.DataFrame(rows)
        pivot = df.pivot_table(values="得分率", index="学生", columns="科目", aggfunc="mean")

        fig = px.imshow(
            pivot,
            text_auto=".0f",
            aspect="auto",
            color_continuous_scale="RdYlGn",
            range_color=[0, 100],
            title=f"《{exam.name}》各科成绩热力图（得分率 %）",
        )
        fig.update_layout(height=max(400, len(pivot) * 25 + 100))
        return fig
    finally:
        session.close()


def chart_rank_sankey(student_id: int) -> go.Figure:
    """班级排名变化桑基图"""
    session = get_session()
    try:
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
            fig = go.Figure()
            fig.update_layout(title="需要至少2次考试数据")
            return fig

        labels = []
        source = []
        target = []
        values = []
        customdata = []

        for i in range(len(rankings) - 1):
            exam_cur = rankings[i].exam or session.query(Exam).get(rankings[i].exam_id)
            exam_next = rankings[i + 1].exam or session.query(Exam).get(rankings[i + 1].exam_id)

            from_label = f"{exam_cur.name}<br>第{rankings[i].rank}名"
            to_label = f"{exam_next.name}<br>第{rankings[i+1].rank}名"

            if from_label not in labels:
                labels.append(from_label)
            if to_label not in labels:
                labels.append(to_label)

            source.append(labels.index(from_label))
            target.append(labels.index(to_label))
            values.append(1)
            change = rankings[i + 1].rank - rankings[i].rank
            direction = "↑" if change < 0 else ("↓" if change > 0 else "→")
            customdata.append(f"排名变化: {direction}{abs(change)}")

        fig = go.Figure(go.Sankey(
            node=dict(pad=15, thickness=20, line=dict(color="black", width=0.5), label=labels),
            link=dict(source=source, target=target, value=values,
                      customdata=customdata,
                      hovertemplate="%{source.label} → %{target.label}<br>%{customdata}<extra></extra>"),
        ))
        student_label = _get_student_label(session, student_id)
        fig.update_layout(title=f"{student_label} 排名变化", height=400)
        return fig
    finally:
        session.close()


def chart_rating_breakdown_pie(student_id: int) -> go.Figure:
    """Rating 贡献分解饼图（按考试类型）"""
    from rating import get_rating_breakdown
    data = get_rating_breakdown(student_id)
    if not data:
        fig = go.Figure()
        fig.update_layout(title="暂无数据")
        return fig

    df = pd.DataFrame(data)
    session = get_session()
    try:
        label = _get_student_label(session, student_id)
    finally:
        session.close()

    fig = px.pie(
        df, values="value", names="exam_type",
        title=f"{label} — Rating 贡献分解（按考试类型）",
        hover_data={"pct": True},
    )
    fig.update_traces(textinfo="label+percent", hovertemplate="%{label}: %{value}<br>占比: %{customdata[0]}%")
    return fig


def chart_class_rating_comparison(ratings: dict) -> go.Figure:
    """多班级 Rating 对比（平行坐标 + 柱状图）"""
    session = get_session()
    try:
        rows = []
        for sid, rdict in ratings.items():
            stu = session.query(Student).filter_by(id=sid).first()
            if not stu:
                continue
            row = {"班级": stu.class_name, "总分Rating": rdict.get("overall", 0)}
            for sg in ALL_SUBJECT_GROUPS:
                row[sg] = rdict.get(sg, 0)
            rows.append(row)
        df = pd.DataFrame(rows)
    finally:
        session.close()

    if df.empty:
        fig = go.Figure()
        fig.update_layout(title="暂无数据")
        return fig

    # 平行坐标图
    classes = sorted(df["班级"].unique())
    color_map = {cls: px.colors.qualitative.Plotly[i % len(px.colors.qualitative.Plotly)]
                 for i, cls in enumerate(classes)}
    df["color_idx"] = df["班级"].map({c: i for i, c in enumerate(classes)})

    dimensions = [
        dict(label="总分Rating", values=df["总分Rating"]),
    ] + [dict(label=sg, values=df[sg]) for sg in ALL_SUBJECT_GROUPS]

    fig = go.Figure(go.Parcoords(
        line=dict(color=df["color_idx"], colorscale=[
            [i / max(len(classes) - 1, 1), color_map[c]] for i, c in enumerate(classes)
        ]),
        dimensions=dimensions,
    ))
    fig.update_layout(title="多班级 Rating 平行坐标对比", height=500)
    return fig


def chart_subject_rating_radar(student_id: int) -> go.Figure:
    """单学生各科 Rating 雷达图"""
    session = get_session()
    try:
        from rating import calculate_rating_for_student
        ratings = calculate_rating_for_student(student_id, session)
        student = session.query(Student).get(student_id)
    finally:
        session.close()

    if not ratings:
        fig = go.Figure()
        fig.update_layout(title="暂无数据")
        return fig

    r_values = [ratings.get(sg, 0) for sg in ALL_SUBJECT_GROUPS]

    fig = go.Figure(go.Scatterpolar(
        r=r_values + [r_values[0]],
        theta=ALL_SUBJECT_GROUPS + [ALL_SUBJECT_GROUPS[0]],
        fill="toself",
        name=f"{student.name}({student.student_id})" if student else "",
    ))
    fig.update_layout(
        title=f"{student.name} 各科 Rating 雷达图" if student else "各科 Rating 雷达图",
        polar=dict(radialaxis=dict(range=[0, 2000])),
        height=500,
    )
    return fig


def export_all_charts_as_zip(ratings: dict) -> bytes:
    """生成所有图表的 HTML 文件并打包为 ZIP"""
    import zipfile
    from io import BytesIO
    from database import get_session
    from models import Student, Exam
    from rating import get_student_rating_history

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        session = get_session()
        try:
            students_list = session.query(Student).order_by(Student.class_name, Student.student_id).all()
            student_ids = {s.id for s in students_list}
            classes = sorted(set(s.class_name for s in students_list))
        finally:
            session.close()

        if not students_list:
            return buf.getvalue()

        # 1. Rating 变化曲线 — 选前3名学生
        sample_sids = sorted(student_ids)[:3]
        histories = {}
        for sid in sample_sids:
            hist = get_student_rating_history(sid, None)
            if hist:
                histories[sid] = hist
        if histories:
            fig = chart_rating_history(histories)
            zf.writestr("01_Rating变化曲线.html", fig.to_html(include_plotlyjs="cdn", full_html=True))

        # 2. 班级 Rating 分布
        if classes:
            fig = chart_class_rating_distribution(ratings)
            zf.writestr("02_班级Rating分布.html", fig.to_html(include_plotlyjs="cdn", full_html=True))

        # 3. 单次考试热力图 — 最近一次考试
        session = get_session()
        try:
            latest_exam = session.query(Exam).order_by(Exam.exam_date.desc()).first()
        finally:
            session.close()
        if latest_exam:
            fig = chart_exam_heatmap(latest_exam.id)
            zf.writestr("03_考试热力图.html", fig.to_html(include_plotlyjs="cdn", full_html=True))

        # 4. 排名变化桑基图 — 第一个学生
        if sample_sids:
            fig = chart_rank_sankey(sample_sids[0])
            zf.writestr("04_排名变化桑基图.html", fig.to_html(include_plotlyjs="cdn", full_html=True))

        # 5. Rating 贡献饼图 — 第一个学生
        if sample_sids:
            fig = chart_rating_breakdown_pie(sample_sids[0])
            zf.writestr("05_Rating贡献饼图.html", fig.to_html(include_plotlyjs="cdn", full_html=True))

        # 6. 多班级平行坐标
        fig = chart_class_rating_comparison(ratings)
        zf.writestr("06_多班级平行坐标.html", fig.to_html(include_plotlyjs="cdn", full_html=True))

        # 7. 各科 Rating 雷达图 — 第一个学生
        if sample_sids:
            fig = chart_subject_rating_radar(sample_sids[0])
            zf.writestr("07_各科Rating雷达图.html", fig.to_html(include_plotlyjs="cdn", full_html=True))

    return buf.getvalue()
