"""学生成绩评级系统 — Streamlit 主应用"""
import streamlit as st
import pandas as pd
from datetime import date
from io import BytesIO

from database import init_db, get_session
from models import Student, Exam, ExamSubject, ExamScore, ExamRanking
from config import (
    get_type_weights, set_type_weight, get_decay_lambda, set_decay_lambda,
    ALL_SUBJECT_GROUPS, DEFAULT_TYPE_WEIGHTS, DEFAULT_DECAY_LAMBDA,
)
from rating import (
    calculate_rating_for_student, recalculate_all_ratings,
    get_rating_tier, get_student_rating_history,
    get_rating_breakdown, detect_anomalies,
    get_all_students_comparison,
)
from import_export import (
    parse_student_file, import_students, generate_student_template,
    create_exam, parse_score_file, import_scores, generate_score_template,
    export_ratings_excel, export_db_dump,
)
from visualizations import (
    chart_rating_history, chart_class_rating_distribution,
    chart_exam_heatmap, chart_rank_sankey,
    chart_rating_breakdown_pie, chart_class_rating_comparison,
    chart_subject_rating_radar, export_all_charts_as_zip,
)

# ── 初始化 ──────────────────────────────────────────────
st.set_page_config(page_title="学生成绩评级系统", layout="wide", initial_sidebar_state="expanded")
init_db()

# 页面路由
PAGES = {
    "🏠 首页仪表盘": "dashboard",
    "👨‍🎓 学生管理": "students",
    "📝 考试管理": "exams",
    "📊 Rating 总览": "ratings",
    "📈 可视化分析": "charts",
    "⚙️ 权重配置": "settings",
    "💾 数据导出": "export",
}

with st.sidebar:
    st.title("📚 成绩评级系统")
    page = st.radio("导航", list(PAGES.keys()), label_visibility="collapsed")
    st.divider()
    st.caption("© wujiahaocoder  CC BY-NC-ND 4.0")

page_id = PAGES[page]

# ── 首页仪表盘 ──────────────────────────────────────────
if page_id == "dashboard":
    st.title("🏠 仪表盘")

    session = get_session()
    try:
        n_students = session.query(Student).count()
        n_exams = session.query(Exam).count()
    finally:
        session.close()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("学生总数", n_students)
    col2.metric("考试总数", n_exams)
    col3.metric("衰减系数 λ", get_decay_lambda())
    tw = get_type_weights()
    col4.metric("权重配置", f"周考={tw['周考']}, 期中={tw['期中']}")

    st.divider()

    if st.button("🔄 重算全部 Rating", type="primary", width='stretch'):
        with st.spinner("正在重算..."):
            ratings = recalculate_all_ratings()
        st.success(f"重算完成！共 {len(ratings)} 名学生")
        st.rerun()

    # Rating 排行 Top 20
    st.subheader("🏆 Rating 排行榜 (Top 20)")
    try:
        ratings = recalculate_all_ratings()
    except Exception:
        ratings = {}
    if ratings:
        session = get_session()
        try:
            rows = []
            for sid, rdict in ratings.items():
                stu = session.query(Student).filter_by(id=sid).first()
                if not stu:
                    continue
                ov = rdict.get("overall", 0)
                rows.append({
                    "排名": 0, "学号": stu.student_id, "姓名": stu.name,
                    "班级": stu.class_name, "Rating": ov, "评级": get_rating_tier(ov),
                })
            rows.sort(key=lambda r: r["Rating"], reverse=True)
            for i, r in enumerate(rows):
                r["排名"] = i + 1
            df = pd.DataFrame(rows[:20])

            def color_tier(val):
                colors = {"S": "gold", "A": "red", "B": "orange", "C": "green", "D": "gray"}
                return f"color: {colors.get(val, 'black')}; font-weight: bold"

            st.dataframe(
                df.style.map(color_tier, subset=["评级"]),
                width='stretch', hide_index=True,
                column_config={"Rating": st.column_config.NumberColumn(format="%.1f")},
            )
        finally:
            session.close()
    else:
        st.info("暂无数据，请先导入学生和考试成绩")

# ── 学生管理 ────────────────────────────────────────────
elif page_id == "students":
    st.title("👨‍🎓 学生管理")

    tab1, tab2, tab3 = st.tabs(["📋 学生列表", "➕ 手动添加", "📥 批量导入"])

    with tab1:
        session = get_session()
        try:
            students = session.query(Student).order_by(Student.class_name, Student.student_id).all()
            if students:
                df = pd.DataFrame([{
                    "ID": s.id, "学号": s.student_id, "姓名": s.name, "班级": s.class_name,
                } for s in students])
                st.dataframe(df, width='stretch', hide_index=True)

                # 删除学生
                st.divider()
                st.subheader("删除学生")
                del_ids = st.multiselect("选择要删除的学生", options=[f"{s.id}: {s.name}({s.student_id})" for s in students])
                if del_ids and st.button("🗑️ 确认删除", type="secondary"):
                    del_id_ints = [int(x.split(":")[0]) for x in del_ids]
                    del_session = get_session()
                    try:
                        for did in del_id_ints:
                            stu = del_session.query(Student).get(did)
                            if stu:
                                del_session.delete(stu)
                        del_session.commit()
                        st.success(f"已删除 {len(del_id_ints)} 名学生")
                        st.rerun()
                    except Exception as e:
                        del_session.rollback()
                        st.error(f"删除失败: {e}")
                    finally:
                        del_session.close()
            else:
                st.info("暂无学生数据")
        finally:
            session.close()

    with tab2:
        st.subheader("手动添加学生")
        col1, col2, col3 = st.columns(3)
        sid = col1.text_input("学号", key="manual_sid")
        name = col2.text_input("姓名", key="manual_name")
        cls = col3.text_input("班级", key="manual_class")

        if st.button("✅ 添加", width='stretch'):
            if not sid or not name or not cls:
                st.error("学号、姓名、班级均为必填")
            else:
                session = get_session()
                try:
                    existing = session.query(Student).filter_by(student_id=sid).first()
                    if existing:
                        st.error(f"学号 {sid} 已存在")
                    else:
                        session.add(Student(student_id=sid, name=name, class_name=cls))
                        session.commit()
                        st.success(f"已添加 {name}({sid})")
                        st.rerun()
                finally:
                    session.close()

    with tab3:
        st.subheader("批量导入学生")
        st.markdown("支持 **CSV** 和 **Excel (.xlsx)** 格式，表头：`学号,姓名,班级`")

        col1, col2 = st.columns([3, 1])
        with col2:
            template = generate_student_template()
            st.download_button("📥 下载模板", data=template, file_name="学生导入模板.csv", mime="text/csv")

        uploaded = col1.file_uploader("上传文件", type=["csv", "xlsx"], key="student_upload")

        if uploaded:
            df, errors = parse_student_file(uploaded.read(), uploaded.name)

            # 预检报告
            error_count = len([e for e in errors if e["line"] > 0])
            warn_count = len([e for e in errors if e["line"] == 0])

            st.subheader("预检报告")
            c1, c2, c3 = st.columns(3)
            c1.metric("✅ 可导入", len(df) - error_count)
            c2.metric("⚠️ 警告", warn_count)
            c3.metric("❌ 错误", error_count)

            with st.expander("查看详情"):
                for e in errors:
                    st.warning(f"第 {e['line']} 行: {e['reason']}")

            with st.expander("预览数据（前10行）"):
                st.dataframe(df.head(10), width='stretch')

            if error_count < len(df):
                if st.button("✅ 确认导入", type="primary", width='stretch'):
                    success, skipped = import_students(df, errors)
                    st.success(f"导入完成：成功 {success} 行，跳过 {skipped} 行")
                    st.rerun()

# ── 考试管理 ────────────────────────────────────────────
elif page_id == "exams":
    st.title("📝 考试管理")

    tab1, tab2, tab3 = st.tabs(["📋 考试列表", "➕ 创建考试 & 录入成绩", "📥 批量导入成绩"])

    with tab1:
        session = get_session()
        try:
            exams = session.query(Exam).order_by(Exam.exam_date.desc()).all()
            if exams:
                rows = []
                for e in exams:
                    subj_count = session.query(ExamSubject).filter_by(exam_id=e.id).count()
                    score_count = session.query(ExamScore).filter_by(exam_id=e.id).count()
                    rows.append({
                        "ID": e.id, "考试名称": e.name, "类型": e.exam_type,
                        "日期": str(e.exam_date), "科目数": subj_count, "成绩记录": score_count,
                    })
                st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)

                # 删除考试
                st.divider()
                del_exam = st.selectbox("选择要删除的考试", options=[f"{e.id}: {e.name}" for e in exams])
                if st.button("🗑️ 删除考试（含成绩和排名）", type="secondary"):
                    eid = int(del_exam.split(":")[0])
                    ds = get_session()
                    try:
                        exam = ds.query(Exam).get(eid)
                        if exam:
                            ds.delete(exam)
                            ds.commit()
                            st.success("已删除")
                            st.rerun()
                    finally:
                        ds.close()
            else:
                st.info("暂无考试")
        finally:
            session.close()

    with tab2:
        st.subheader("创建考试")

        col1, col2, col3 = st.columns(3)
        exam_name = col1.text_input("考试名称（唯一）", key="exam_name")
        exam_type = col2.selectbox("考试类型", ["周考", "月考", "期中", "期末"], key="exam_type")
        exam_date = col3.date_input("考试日期", value=date.today(), key="exam_date")

        st.markdown("### 配置科目与满分")
        st.caption("至少配置一个科目。科目组用于分科 Rating 计算。")

        # 预设科目组模板
        with st.expander("📋 快速预设（点击展开）"):
            preset = st.selectbox("选择预设模板", ["自定义", "全科(语数英+物/历+化生+政地)", "仅语数英", "语数英+物/历"])
            if st.button("应用预设"):
                st.session_state["preset_applied"] = preset
                st.rerun()

        # 默认科目行
        if "subject_rows" not in st.session_state:
            st.session_state["subject_rows"] = [{"name": "", "group": "语文", "max": 150}]

        # 应用预设
        if st.session_state.get("preset_applied"):
            preset = st.session_state["preset_applied"]
            if preset == "全科(语数英+物/历+化生+政地)":
                st.session_state["subject_rows"] = [
                    {"name": "语文", "group": "语文", "max": 150},
                    {"name": "数学", "group": "数学", "max": 150},
                    {"name": "英语", "group": "英语", "max": 150},
                    {"name": "物理", "group": "二选一", "max": 100},
                    {"name": "历史", "group": "二选一", "max": 100},
                    {"name": "化学", "group": "四选二A", "max": 100},
                    {"name": "生物", "group": "四选二A", "max": 100},
                    {"name": "政治", "group": "四选二B", "max": 100},
                    {"name": "地理", "group": "四选二B", "max": 100},
                ]
            elif preset == "仅语数英":
                st.session_state["subject_rows"] = [
                    {"name": "语文", "group": "语文", "max": 150},
                    {"name": "数学", "group": "数学", "max": 150},
                    {"name": "英语", "group": "英语", "max": 150},
                ]
            elif preset == "语数英+物/历":
                st.session_state["subject_rows"] = [
                    {"name": "语文", "group": "语文", "max": 150},
                    {"name": "数学", "group": "数学", "max": 150},
                    {"name": "英语", "group": "英语", "max": 150},
                    {"name": "物理", "group": "二选一", "max": 100},
                    {"name": "历史", "group": "二选一", "max": 100},
                ]
            st.session_state["preset_applied"] = None

        # 动态科目行
        edited_rows = []
        for i, row in enumerate(st.session_state["subject_rows"]):
            c1, c2, c3, c4 = st.columns([3, 2, 2, 1])
            name = c1.text_input(f"科目名", value=row["name"], key=f"sn_{i}", placeholder="如：语文")
            group = c2.selectbox(f"科目组", ALL_SUBJECT_GROUPS, index=ALL_SUBJECT_GROUPS.index(row["group"]) if row["group"] in ALL_SUBJECT_GROUPS else 0, key=f"sg_{i}")
            max_s = c3.number_input(f"满分", value=row["max"], min_value=1, max_value=300, key=f"sm_{i}")
            if c4.button("❌", key=f"del_{i}") and len(st.session_state["subject_rows"]) > 1:
                st.session_state["subject_rows"].pop(i)
                st.rerun()
            edited_rows.append({"name": name, "group": group, "max": max_s})

        st.session_state["subject_rows"] = edited_rows

        if st.button("➕ 添加科目", width='stretch'):
            st.session_state["subject_rows"].append({"name": "", "group": "语文", "max": 100})
            st.rerun()

        st.divider()

        # 手动录入成绩
        if st.session_state["subject_rows"] and any(r["name"] for r in st.session_state["subject_rows"]):
            st.markdown("### 手动录入成绩（可选）")

            session = get_session()
            try:
                students = session.query(Student).order_by(Student.class_name, Student.student_id).all()
            finally:
                session.close()

            if students:
                st.caption("仅录入有成绩的学生，留空即为不录入该生")

                # 按班级分组
                classes = sorted(set(s.class_name for s in students))
                selected_class = st.selectbox("筛选班级", ["全部"] + classes, key="score_class_filter")

                filtered_students = students if selected_class == "全部" else [s for s in students if s.class_name == selected_class]

                score_data = {}
                for stu in filtered_students:
                    with st.expander(f"{stu.name} ({stu.student_id}) — {stu.class_name}"):
                        cols = st.columns(len(st.session_state["subject_rows"]))
                        stu_scores = {}
                        for j, subj in enumerate(st.session_state["subject_rows"]):
                            if not subj["name"]:
                                continue
                            val = cols[j].text_input(
                                f"{subj['name']}(/{subj['max']})",
                                key=f"score_{stu.id}_{j}",
                                placeholder="缺考留空",
                            )
                            if val.strip():
                                try:
                                    stu_scores[subj["name"]] = float(val)
                                except ValueError:
                                    pass
                        score_data[stu.id] = stu_scores
            else:
                st.info("请先添加学生")

        if st.button("💾 创建考试并保存", type="primary", width='stretch'):
            if not exam_name:
                st.error("请输入考试名称")
            else:
                valid_subjects = [r for r in st.session_state["subject_rows"] if r["name"]]
                if not valid_subjects:
                    st.error("请至少配置一个科目")
                else:
                    try:
                        exam = create_exam(exam_name, exam_type, exam_date,
                                           [{"name": r["name"], "group": r["group"], "max": r["max"]} for r in valid_subjects])
                        st.success(f"考试「{exam_name}」创建成功！")

                        # 如果填了成绩，导入
                        if students and score_data:
                            # 构建 DataFrame 导入
                            rows_list = []
                            for stu in filtered_students:
                                if stu.id in score_data and score_data[stu.id]:
                                    row = {"学号": stu.student_id}
                                    row.update(score_data[stu.id])
                                    rows_list.append(row)
                            if rows_list:
                                df_scores = pd.DataFrame(rows_list)
                                errors_scores = []
                                succ, skip = import_scores(df_scores, errors_scores, exam.id)
                                st.success(f"成绩导入：成功 {succ} 行")
                                recalculate_all_ratings()

                        st.balloons()
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))

    with tab3:
        st.subheader("批量导入成绩")

        session = get_session()
        try:
            exams = session.query(Exam).order_by(Exam.exam_date.desc()).all()
        finally:
            session.close()

        if not exams:
            st.warning("请先创建考试")
        else:
            selected_exam = st.selectbox("选择考试", options=[f"{e.id}: {e.name} ({e.exam_type})" for e in exams])
            eid = int(selected_exam.split(":")[0])

            # 下载模板
            template_data = generate_score_template(eid)
            col_a, col_b = st.columns([3, 1])
            with col_b:
                st.download_button("📥 下载成绩模板", data=template_data,
                                   file_name=f"成绩导入_{selected_exam.split(':')[1].strip()}.csv", mime="text/csv")

            uploaded_score = col_a.file_uploader("上传成绩文件", type=["csv", "xlsx"], key="score_upload")

            if uploaded_score:
                df_scores, errors_scores = parse_score_file(uploaded_score.read(), uploaded_score.name, eid)

                err_count = len([e for e in errors_scores if e["line"] > 0])
                warn_count = len([e for e in errors_scores if e["line"] == 0])

                st.subheader("预检报告")
                c1, c2, c3 = st.columns(3)
                c1.metric("✅ 可导入", len(df_scores) - err_count)
                c2.metric("⚠️ 警告", warn_count)
                c3.metric("❌ 错误", err_count)

                with st.expander("查看详情"):
                    for e in errors_scores:
                        st.warning(f"第 {e['line']} 行: {e['reason']}")

                with st.expander("预览数据"):
                    st.dataframe(df_scores.head(20), width='stretch')

                if err_count < len(df_scores):
                    if st.button("✅ 确认导入成绩", type="primary", width='stretch'):
                        succ, skip = import_scores(df_scores, errors_scores, eid)
                        st.success(f"导入完成：成功 {succ} 行，跳过 {skip} 行")
                        st.info("正在重算 Rating...")
                        recalculate_all_ratings()
                        st.success("Rating 重算完成！")
                        st.rerun()

# ── Rating 总览 ─────────────────────────────────────────
elif page_id == "ratings":
    st.title("📊 Rating 总览")

    if st.button("🔄 刷新 Rating", width='stretch'):
        recalculate_all_ratings()
        st.rerun()

    ratings = recalculate_all_ratings()

    if not ratings:
        st.info("暂无数据")
    else:
        session = get_session()
        try:
            # ── 对比上次视图（默认） ──
            st.subheader("📈 对比上次考试 (Rating / 排名)")
            comparison = get_all_students_comparison(session)
            if comparison:
                df_comp = pd.DataFrame(comparison)
                display_cols = [
                    "学号", "姓名", "班级",
                    "当前Rating", "上次Rating", "Rating变动",
                    "当前排名", "上次排名", "排名变动", "评级",
                ]
                df_display = df_comp[display_cols].copy()

                # 样式函数（操作原始数值，染色后由 Styler.format 显示）
                def color_rating_change(val):
                    if val is None or pd.isna(val):
                        return ""
                    if val > 0:
                        return "color: #22c55e; font-weight: bold"
                    elif val < 0:
                        return "color: #ef4444; font-weight: bold"
                    return "color: #888"

                def color_rank_change(val):
                    if val is None or pd.isna(val):
                        return ""
                    if val < 0:
                        return "color: #22c55e; font-weight: bold"
                    elif val > 0:
                        return "color: #ef4444; font-weight: bold"
                    return "color: #888"

                # 先对原始数值染色
                styled = df_display.style.map(
                    color_rating_change, subset=["Rating变动"]
                ).map(
                    color_rank_change, subset=["排名变动"]
                ).map(
                    lambda v: f"color: {'gold' if v=='S' else 'red' if v=='A' else 'orange' if v=='B' else 'green' if v=='C' else 'gray'}; font-weight: bold",
                    subset=["评级"],
                )

                # 再用 format 控制显示（不影响底层数值）
                styled = styled.format(
                    {
                        "当前Rating": "{:.1f}",
                        "上次Rating": lambda v: f"{v:.1f}" if pd.notna(v) else "—",
                        "Rating变动": lambda v: (f"+{v:.1f}" if v > 0 else f"{v:.1f}") if pd.notna(v) else "—",
                        "当前排名": lambda v: str(int(v)) if pd.notna(v) else "—",
                        "上次排名": lambda v: str(int(v)) if pd.notna(v) else "—",
                        "排名变动": lambda v: (f"↑{abs(int(v))}" if v < 0 else (f"↓{int(v)}" if v > 0 else "→0")) if pd.notna(v) else "—",
                    },
                    na_rep="—",
                )

                st.dataframe(
                    styled,
                    width='stretch', hide_index=True,
                    column_config={
                        "当前Rating": st.column_config.NumberColumn(format="%.1f"),
                    },
                )

            # ── 评级分档统计 ──
            st.divider()
            tiers = {"S": 0, "A": 0, "B": 0, "C": 0, "D": 0}
            for r in comparison:
                tiers[r["评级"]] += 1
            cols = st.columns(5)
            for i, (tier, count) in enumerate(tiers.items()):
                color = ["gold", "red", "orange", "green", "gray"][i]
                cols[i].metric(f"评级 {tier}", count)

            # ── 完整 Rating 表（折叠） ──
            with st.expander("📋 完整 Rating 表（含分科）"):
                rows = []
                for sid, rdict in ratings.items():
                    stu = session.query(Student).filter_by(id=sid).first()
                    if not stu:
                        continue
                    ov = rdict.get("overall", 0)
                    row = {
                        "学号": stu.student_id, "姓名": stu.name, "班级": stu.class_name,
                        "总分Rating": ov, "评级": get_rating_tier(ov),
                    }
                    for sg in ALL_SUBJECT_GROUPS:
                        row[sg] = rdict.get(sg, 0)
                    rows.append(row)
                rows.sort(key=lambda r: r["总分Rating"], reverse=True)

                st.dataframe(
                    pd.DataFrame(rows).style.map(
                        lambda v: f"color: {'gold' if v=='S' else 'red' if v=='A' else 'orange' if v=='B' else 'green' if v=='C' else 'gray'}; font-weight: bold",
                        subset=["评级"],
                    ),
                    width='stretch', hide_index=True,
                    column_config={sg: st.column_config.NumberColumn(format="%.1f") for sg in ALL_SUBJECT_GROUPS},
                )

            # 学生详情
            st.divider()
            st.subheader("🔍 学生详情")
            student_options = {f"{s.id}: {s.name}({s.student_id})": s.id for s in session.query(Student).all()}
            selected_stu = st.selectbox("选择学生", list(student_options.keys()))
            if selected_stu:
                stu_id = student_options[selected_stu]
                stu_ratings = ratings.get(stu_id, {})
                if stu_ratings:
                    st.markdown("### 分科 Rating")
                    rc = st.columns(len(ALL_SUBJECT_GROUPS) + 1)
                    ov = stu_ratings.get("overall", 0)
                    rc[0].metric("总分", f"{ov:.1f}", get_rating_tier(ov))
                    for i, sg in enumerate(ALL_SUBJECT_GROUPS):
                        rc[i + 1].metric(sg, f"{stu_ratings.get(sg, 0):.1f}")

                    # Rating 历史
                    history = get_student_rating_history(stu_id)
                    if history:
                        dfh = pd.DataFrame(history)
                        st.markdown("### Rating 变化历史")
                        st.dataframe(dfh, width='stretch', hide_index=True,
                                     column_config={"rating": st.column_config.NumberColumn("Rating", format="%.1f")})

                    # 异常检测
                    anomalies = detect_anomalies(stu_id)
                    if anomalies:
                        st.warning("### ⚠️ 排名异常波动")
                        for a in anomalies:
                            direction = "上升" if a["change"] < 0 else "下降"
                            st.warning(f"{a['exam_name']}: 从第{a['prev_rank']}名{direction}至第{a['curr_rank']}名（变化{a['change']}名，班级{a['class_size']}人）")
        finally:
            session.close()

# ── 可视化分析 ──────────────────────────────────────────
elif page_id == "charts":
    st.title("📈 可视化分析")

    # 批量导出按钮
    col_left, col_right = st.columns([3, 1])
    with col_right:
        if st.button("📦 批量导出全部图表 (ZIP)", type="primary", width='stretch', use_container_width=True):
            with st.spinner("正在生成全部 7 种图表..."):
                data = export_all_charts_as_zip(recalculate_all_ratings())
            st.download_button(
                "⬇️ 点击下载 ZIP", data=data,
                file_name="StuRating_全部图表.zip",
                mime="application/zip",
            )

    chart_type = st.selectbox("选择图表", [
        "Rating 变化曲线",
        "班级 Rating 分布",
        "单次考试热力图",
        "排名变化桑基图",
        "Rating 贡献饼图",
        "多班级平行坐标",
        "各科 Rating 雷达图",
    ])

    session = get_session()
    try:
        students_list = session.query(Student).order_by(Student.class_name, Student.student_id).all()
        student_opts = {f"{s.id}: {s.name}({s.student_id}) [{s.class_name}]": s.id for s in students_list}
    finally:
        session.close()

    if chart_type == "Rating 变化曲线":
        st.subheader("Rating 变化曲线")
        selected = st.multiselect("选择学生（可多选）", list(student_opts.keys()), default=list(student_opts.keys())[:3] if student_opts else [])
        # 选择科目组
        group = st.selectbox("科目组", ["总分"] + ALL_SUBJECT_GROUPS, key="curve_group")
        sg_param = None if group == "总分" else group

        if selected:
            histories = {}
            for sel in selected:
                sid = student_opts[sel]
                hist = get_student_rating_history(sid, sg_param)
                if hist:
                    histories[sid] = hist
            if histories:
                fig = chart_rating_history(histories)
                st.plotly_chart(fig, width='stretch')
            else:
                st.info("所选学生暂无 Rating 历史")

    elif chart_type == "班级 Rating 分布":
        st.subheader("班级 Rating 分布")
        classes = sorted(set(s.class_name for s in students_list))
        cls_filter = st.selectbox("班级", ["全部"] + classes)
        ratings_all = recalculate_all_ratings()
        fig = chart_class_rating_distribution(ratings_all, None if cls_filter == "全部" else cls_filter)
        st.plotly_chart(fig, width='stretch')

    elif chart_type == "单次考试热力图":
        st.subheader("单次考试热力图")
        session = get_session()
        try:
            exams_opts = session.query(Exam).order_by(Exam.exam_date.desc()).all()
            if exams_opts:
                sel_exam = st.selectbox("选择考试", [f"{e.id}: {e.name}" for e in exams_opts])
                eid = int(sel_exam.split(":")[0])
                fig = chart_exam_heatmap(eid)
                st.plotly_chart(fig, width='stretch')
            else:
                st.info("暂无考试")
        finally:
            session.close()

    elif chart_type == "排名变化桑基图":
        st.subheader("排名变化桑基图")
        sel_stu = st.selectbox("选择学生", list(student_opts.keys()), key="sankey_stu")
        if sel_stu:
            fig = chart_rank_sankey(student_opts[sel_stu])
            st.plotly_chart(fig, width='stretch')

    elif chart_type == "Rating 贡献饼图":
        st.subheader("Rating 贡献分解饼图")
        sel_stu = st.selectbox("选择学生", list(student_opts.keys()), key="pie_stu")
        if sel_stu:
            fig = chart_rating_breakdown_pie(student_opts[sel_stu])
            st.plotly_chart(fig, width='stretch')

    elif chart_type == "多班级平行坐标":
        st.subheader("多班级 Rating 平行坐标对比")
        ratings_all = recalculate_all_ratings()
        fig = chart_class_rating_comparison(ratings_all)
        st.plotly_chart(fig, width='stretch')

    elif chart_type == "各科 Rating 雷达图":
        st.subheader("各科 Rating 雷达图")
        sel_stu = st.selectbox("选择学生", list(student_opts.keys()), key="radar_stu")
        if sel_stu:
            fig = chart_subject_rating_radar(student_opts[sel_stu])
            st.plotly_chart(fig, width='stretch')

# ── 权重配置 ────────────────────────────────────────────
elif page_id == "settings":
    st.title("⚙️ 权重配置")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("考试类型权重")
        tw = get_type_weights()

        new_tw = {}
        for et in ["周考", "月考", "期中", "期末"]:
            new_tw[et] = st.number_input(
                f"{et}权重",
                value=tw[et],
                min_value=0.0,
                max_value=2.0,
                step=0.05,
                format="%.2f",
                key=f"tw_{et}",
            )

        if st.button("💾 保存考试权重", width='stretch'):
            for et, w in new_tw.items():
                set_type_weight(et, w)
            st.success("权重已保存！正在重算 Rating...")
            recalculate_all_ratings()
            st.success("重算完成")
            st.rerun()

    with col2:
        st.subheader("衰减系数")
        current_lambda = get_decay_lambda()
        new_lambda = st.slider("λ (衰减系数)", min_value=0.05, max_value=1.0, value=current_lambda, step=0.05)

        st.markdown(f"""
        | 往前 N 次 | 衰减系数 (λ={new_lambda:.2f}) |
        |-----------|------|
        | 0（最近） | 1.00 |
        | 1 | {2.71828**(-new_lambda*1):.2f} |
        | 3 | {2.71828**(-new_lambda*3):.2f} |
        | 5 | {2.71828**(-new_lambda*5):.2f} |
        | 10 | {2.71828**(-new_lambda*10):.2f} |
        """)

        if st.button("💾 保存衰减系数", width='stretch'):
            set_decay_lambda(new_lambda)
            st.success("已保存！正在重算 Rating...")
            recalculate_all_ratings()
            st.success("重算完成")
            st.rerun()

    st.divider()
    st.subheader("📐 Rating 公式说明")
    st.latex(r"""
    \text{contribution}_i = w_{\text{type}} \times w_{\text{subjects}} \times e^{-\lambda(N-i)} \times 2000 \times \left(1 - \frac{\text{rank}-1}{\text{class\_size}}\right)
    """)
    st.latex(r"""
    \text{Rating} = \frac{\sum \text{contribution}_i}{\sum w_{\text{type}} \times w_{\text{subjects}} \times e^{-\lambda(N-i)}}
    """)
    st.caption("三个独立乘区：考试类型权重 × 科目数权重 × 时间衰减 × 排名分")

# ── 数据导出 ────────────────────────────────────────────
elif page_id == "export":
    st.title("💾 数据导出")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.subheader("Rating 榜 (Excel)")
        if st.button("📥 导出 Rating 榜", width='stretch'):
            ratings = recalculate_all_ratings()
            data = export_ratings_excel(ratings)
            st.download_button("点击下载", data=data, file_name="Rating排行榜.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with col2:
        st.subheader("数据库备份")
        if st.button("📥 导出数据库", width='stretch'):
            data = export_db_dump()
            st.download_button("点击下载", data=data, file_name="student_rating_backup.db", mime="application/octet-stream")

    with col3:
        st.subheader("图表导出")
        st.caption("在可视化分析页面，鼠标悬停图表右上角 → 点击相机图标即可导出 PNG/SVG")
