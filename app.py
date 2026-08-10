import streamlit as st
import pandas as pd
import os
import subprocess
import sys
import gspread
import plotly.express as px
import time
from datetime import datetime

# 화면 기본 설정
st.set_page_config(page_title="맞춤 공고 수집 대시보드", layout="wide")

# ==========================================
# 🔐 대시보드 보안 자물쇠 설정
# ==========================================
DASHBOARD_PASSWORD = "0804"  

def check_password():
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False
    if not st.session_state["password_correct"]:
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.title("🔒 대시보드 보안 접속")
            st.info("이 대시보드는 우리 팀원만 접근할 수 있습니다.\n\n발급받은 비밀번호를 입력해 주세요.")
            pwd_input = st.text_input("🔑 비밀번호 입력", type="password")
            if st.button("🚀 접속하기", use_container_width=True, type="primary"):
                if pwd_input == DASHBOARD_PASSWORD:
                    st.session_state["password_correct"] = True
                    st.rerun() 
                else:
                    st.error("🚫 비밀번호가 일치하지 않습니다.")
        return False
    return True

if not check_password():
    st.stop()

# ==========================================
# 🛑 영구 불멸의 '구글 시트' 자물쇠 시스템
# ==========================================
def manage_sheet_lock(action="check", engine_name=""):
    try:
        gc = gspread.service_account(filename="google_key.json")
        doc = gc.open("맞춤공고_DB")
        try:
            ws = doc.worksheet("settings")
        except gspread.exceptions.WorksheetNotFound:
            ws = doc.add_worksheet(title="settings", rows=2, cols=2)
            ws.update(range_name="A1:B1", values=[["free", str(time.time())]])

        if action == "check":
            status = ws.cell(1, 1).value
            timestamp = ws.cell(1, 2).value
            if status == "running":
                if time.time() - float(timestamp) > 900:
                    ws.update(range_name="A1:B1", values=[["free", str(time.time())]])
                    return False
                return True
            return False
        elif action == "lock_and_log":
            ws.update(
                range_name="A1:B2", 
                values=[
                    ["running", str(time.time())],
                    [engine_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S")]
                ]
            )
        elif action == "unlock":
            ws.update(range_name="A1:B1", values=[["free", str(time.time())]])
    except Exception as e:
        return False

@st.cache_data(ttl=60)
def get_recent_log():
    try:
        gc = gspread.service_account(filename="google_key.json")
        doc = gc.open("맞춤공고_DB")
        ws = doc.worksheet("settings")
        eng = ws.cell(2, 1).value
        tm = ws.cell(2, 2).value
        return eng if eng else "기록 없음", tm if tm else "-"
    except:
        return "기록 없음", "-"

# ==========================================
# ⚡ 데이터 통신 및 상태 업데이트 함수
# ==========================================
if "GOOGLE_CREDENTIALS" in st.secrets:
    with open("google_key.json", "w", encoding="utf-8") as f:
        f.write(st.secrets["GOOGLE_CREDENTIALS"])

@st.cache_data(ttl=600)
def get_google_sheet(sheet_name):
    try:
        gc = gspread.service_account(filename="google_key.json")
        doc = gc.open("맞춤공고_DB")
        worksheet = doc.worksheet(sheet_name)
        data = worksheet.get_all_records()
        return pd.DataFrame(data)
    except Exception as e:
        return pd.DataFrame()

def update_notice_status(notice_keys_to_mark, status_value):
    try:
        gc = gspread.service_account(filename="google_key.json")
        doc = gc.open("맞춤공고_DB")
        worksheet = doc.worksheet("notices")
        all_records = worksheet.get_all_values()
        if not all_records: return True
        
        headers = all_records[0]
        if "검토유무" not in headers:
            headers.append("검토유무")
            worksheet.update(range_name="1:1", values=[headers])
            review_col_idx = len(headers) - 1
        else:
            review_col_idx = headers.index("검토유무")
            
        key_col_idx = headers.index("notice_key")
        cells_to_update = []
        
        for row_idx, row in enumerate(all_records):
            if row_idx == 0: continue
            if len(row) <= review_col_idx: row.extend([""] * (review_col_idx - len(row) + 1))
            
            if row[key_col_idx] in notice_keys_to_mark:
                cell = gspread.Cell(row=row_idx+1, col=review_col_idx+1, value=status_value)
                cells_to_update.append(cell)
                
        if cells_to_update: worksheet.update_cells(cells_to_update)
        return True
        
    except gspread.exceptions.APIError:
        st.error("🚨 구글 시트 분당 접속 허용량을 초과했습니다! 약 1분 뒤에 다시 시도해주세요.")
        return False
    except Exception as e:
        st.error(f"🚨 알 수 없는 오류 발생: {e}")
        return False

# ==========================================
# 🎨 테이블 렌더링 헬퍼 함수
# ==========================================
def render_notice_table(df, key_prefix):
    if df.empty:
        st.info("해당되는 공고가 없습니다.")
        return
        
    display_columns = ['notice_key', '출처', '등록일', '공고제목', '특이사항', '검토유무', '상세링크']
    display_df = df[[c for c in display_columns if c in df.columns]].copy()
    display_df.insert(0, '선택', False)
    
    def highlight_row(row):
        status = str(row.get('검토유무', '')).strip()
        title_text = str(row.get('공고제목', ''))
        special_text = str(row.get('특이사항', ''))
        
        if status == '내업무아님': return ['background-color: #8c8c8c; color: #ffffff; text-decoration: line-through;'] * len(row)
        if status == '내업무맞음': return ['background-color: #cce5ff; color: #004080; font-weight: bold;'] * len(row)
        if status == '완료': return ['background-color: #f0f2f6; color: #a0aab2;'] * len(row)
        if '안전점검' in title_text or '안전점검' in special_text: return ['background-color: #e6ffe6; color: #006600; font-weight: bold;'] * len(row)
            
        return [''] * len(row)
        
    styled_df = display_df.style.apply(highlight_row, axis=1)
    disabled_cols = [col for col in display_df.columns if col != '선택']
    
    edited_df = st.data_editor(
        styled_df,
        column_config={
            "선택": st.column_config.CheckboxColumn("선택", required=True),
            "상세링크": st.column_config.LinkColumn("상세링크"),
            "notice_key": None
        },
        disabled=disabled_cols,
        hide_index=True, 
        use_container_width=True, 
        key=f"editor_{key_prefix}"
    )
    
    selected_keys = edited_df[edited_df['선택'] == True]['notice_key'].tolist()
    
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        if st.button("🔵 우리의 업무 맞음 (파랑)", key=f"btn1_{key_prefix}", use_container_width=True):
            if selected_keys:
                with st.spinner("구글 시트에 적용 중..."): 
                    if update_notice_status(selected_keys, "내업무맞음"):
                        get_google_sheet.clear(); st.rerun()
            else: st.warning("선택된 공고가 없습니다.")
    with c2:
        if st.button("⚫ 우리의 업무 아님 (진회색)", key=f"btn2_{key_prefix}", use_container_width=True):
            if selected_keys:
                with st.spinner("구글 시트에 적용 중..."): 
                    if update_notice_status(selected_keys, "내업무아님"):
                        get_google_sheet.clear(); st.rerun()
            else: st.warning("선택된 공고가 없습니다.")
    with c3:
        if st.button("✅ 일반 검토 완료 (연회색)", key=f"btn3_{key_prefix}", use_container_width=True):
            if selected_keys:
                with st.spinner("구글 시트에 적용 중..."): 
                    if update_notice_status(selected_keys, "완료"):
                        get_google_sheet.clear(); st.rerun()
            else: st.warning("선택된 공고가 없습니다.")
    with c4:
        if selected_keys:
            with st.popover("🔄 상태 초기화 (미검토)", use_container_width=True):
                st.error("⚠️ 정말 상태를 '미검토'로 초기화하시겠습니까?")
                if st.button("네, 초기화 실행", key=f"reset_{key_prefix}", use_container_width=True):
                    with st.spinner("구글 시트에 적용 중..."): 
                        if update_notice_status(selected_keys, "미검토"):
                            get_google_sheet.clear(); st.rerun()
        else:
            if st.button("🔄 상태 초기화 (미검토)", key=f"btn4_{key_prefix}", use_container_width=True):
                st.warning("선택된 공고가 없습니다.")

# ==========================================
# 사이드바 메뉴 설정
# ==========================================
st.sidebar.title("📌 메뉴 선택")
menu = st.sidebar.radio(
    "이동할 메뉴를 선택하세요:",
    ["공고 자동수집", "공고 통계 및 분석", "🎯 타겟 공고 (내 업무)", "사이트 검토 필요(오류/개편)", "📝 게시판 / 메모장"]
)
st.sidebar.divider()

st.sidebar.subheader("🔗 주요 사이트 바로가기")
st.sidebar.link_button("🏛️ 한국시설안전협회", "http://www.assi.or.kr/sub/board/gongji.asp?boardname=gongji")
st.sidebar.link_button("📑 조달청 통합명부", "https://www.pps.go.kr/kor/bbs/list.do?key=00641")
st.sidebar.link_button("🏗️ 아이건설넷", "https://www.igunsul.net/")
st.sidebar.link_button("🛒 나라장터", "https://www.g2b.go.kr/index.jsp")

st.sidebar.divider()
st.sidebar.subheader("⏱️ 최근 수집 엔진 기록")
last_engine, last_time = get_recent_log() 
st.sidebar.info(f"**엔진:** {last_engine}\n\n**시간:** {last_time}")

# ==========================================
# 1. 공고 자동수집 메뉴
# ==========================================
if menu == "공고 자동수집":
    st.title("🚀 공고 자동 수집 & 실시간 검색")
    col1, col2 = st.columns([1, 2])
    with col1: 
        collect_days = st.number_input("수집 기간 (0입력 시, 당일만 수집)", min_value=0, max_value=365, value=0, step=1)
    with col2: 
        collect_keywords = st.text_input("🔑 수집 키워드 (쉼표 구분)", value="안전, 모집, 지정, 공고, 용역")

    # 🌟 엔진 4번째 옵션 추가!
    engine_choice = st.radio("⚙️ 수집 엔진 선택", [
        "빠른 탐색(열람가능 사이트)", "정밀 탐색(셀레니움)", "극한 탐색(최대 60초 대기/셀레니움)", "🌟 주요 4대 중앙 사이트 전용 탐색"
    ])

    if st.button("공고 수집", type="primary"):
        if manage_sheet_lock("check"):
            st.warning("⏳ 현재 다른 팀원이 공고를 수집하고 있습니다. 서버 보호를 위해 잠시 후 새로고침(F5)을 눌러주세요!")
        else:
            if "빠른" in engine_choice: target_script = "main_pure.py"
            elif "정밀" in engine_choice: target_script = "main.py"
            elif "극한" in engine_choice: target_script = "main_max.py"
            else: target_script = "main_major.py" # 🌟 신규 엔진 파일 연결
            
            with st.status(f"🚀 [{target_script}] 로봇 출동! 데이터를 수집 중입니다...", expanded=True) as status:
                try:
                    manage_sheet_lock("lock_and_log", engine_name=engine_choice)
                    get_recent_log.clear() 
                    
                    process = subprocess.Popen(
                        [sys.executable, "-u", target_script, str(collect_days), collect_keywords],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', bufsize=1
                    )
                    for line in iter(process.stdout.readline, ''):
                        if line: st.write(line.strip())
                    process.wait()

                    if process.returncode == 0:
                        status.update(label="✅ 공고 수집 완료!", state="complete", expanded=False)
                        get_google_sheet.clear() 
                    else:
                        status.update(label="❌ 수집 실패", state="error", expanded=True)
                except Exception as e:
                    status.update(label="❌ 시스템 오류", state="error", expanded=True)
                finally:
                    manage_sheet_lock("unlock")
            st.rerun()

    st.divider()

    df = get_google_sheet("notices")
    if not df.empty and '공고제목' in df.columns:
        if '검토유무' not in df.columns: df['검토유무'] = '미검토'
            
        st.sidebar.subheader("🔍 공고 실시간 검색")
        search_keyword = st.sidebar.text_input("공고제목 / 특이사항 검색", "")
        search_org = st.sidebar.text_input("발주기관(출처) 검색", "")
        date_range = st.sidebar.date_input("등록일자 범위 지정", [])
        hide_reviewed = st.sidebar.checkbox("✅ 검토 완료된 공고 숨기기", value=False)

        filtered_df = df.copy()
        
        if hide_reviewed:
            filtered_df = filtered_df[~filtered_df['검토유무'].isin(['완료', '내업무아님'])]
            
        if search_keyword: 
            filtered_df = filtered_df[
                filtered_df['공고제목'].astype(str).str.contains(search_keyword, case=False, na=False) |
                filtered_df['특이사항'].astype(str).str.contains(search_keyword, case=False, na=False)
            ]
        if search_org: 
            filtered_df = filtered_df[filtered_df['출처'].astype(str).str.contains(search_org, case=False, na=False)]
        if len(date_range) == 2:
            start_date, end_date = date_range[0], date_range[1]
            parsed_dates = pd.to_datetime(filtered_df['등록일'].astype(str).str.replace('.', '-'), errors='coerce').dt.date
            filtered_df = filtered_df[(parsed_dates >= start_date) & (parsed_dates <= end_date)]

        col_btn1, col_btn2 = st.columns([3, 1])
        with col_btn2:
            if st.button("✅ 현재 화면 전체 '일반 검토완료' 일괄 처리", use_container_width=True):
                keys_to_mark = filtered_df['notice_key'].tolist()
                if keys_to_mark:
                    with st.spinner("구글 시트에 적용 중..."):
                        if update_notice_status(keys_to_mark, "완료"):
                            get_google_sheet.clear()
                            st.success("✅ 일괄 처리가 완료되었습니다!")
                            time.sleep(1)
                            st.rerun()
                else: st.warning("처리할 공고가 없습니다.")

        main_sites_keywords = ['한국시설안전협회', '조달청', '아이건설넷', '나라장터']
        df_main = filtered_df[filtered_df['출처'].str.contains('|'.join(main_sites_keywords), na=False)]
        df_general = filtered_df[~filtered_df['출처'].str.contains('|'.join(main_sites_keywords), na=False)]

        st.subheader(f"📋 일반 기관 공고 (검색 결과: {len(df_general)}건)")
        st.info("💡 체크박스를 선택하고 아래 버튼을 눌러 상태를 변경하세요.")
        render_notice_table(df_general, "general")
        
        st.divider()
        
        st.subheader(f"🌟 주요 4대 중앙 공고 (검색 결과: {len(df_main)}건)")
        st.caption("나라장터, 조달청 통합명부, 아이건설넷, 한국시설안전협회")
        render_notice_table(df_main, "main_site")

    else:
        st.info("아직 구글 시트에 수집된 데이터가 없거나, 시트가 비어있습니다.")

# ==========================================
# 2. 공고 통계 및 분석 메뉴
# ==========================================
elif menu == "공고 통계 및 분석":
    st.title("📊 공고 통계 및 분석 대시보드")
    df = get_google_sheet("notices")
    if not df.empty and '공고제목' in df.columns:
        if '검토유무' not in df.columns: df['검토유무'] = '미검토'
        my_tasks_count = len(df[df['검토유무'] == '내업무맞음'])
        
        col1, col2, col3 = st.columns(3)
        col1.metric("총 누적 수집 공고", f"{len(df)} 건")
        col2.metric("🎯 '내 업무' 분류 공고", f"{my_tasks_count} 건")
        
        parsed_dates = pd.Series(dtype='datetime64[ns]')
        if '등록일' in df.columns:
            parsed_dates = pd.to_datetime(df['등록일'].astype(str).str.replace('.', '-'), errors='coerce').dropna()
            if not parsed_dates.empty: col3.metric("마지막 발주 일자", parsed_dates.max().strftime('%Y-%m-%d'))
            
        st.divider()
        top_col1, top_col2 = st.columns(2)
        with top_col1:
            st.subheader("🗺️ 지역별 공고 현황 (17개 시도 기준)")
            region_keywords = ['서울', '부산', '대구', '인천', '광주', '대전', '울산', '세종', '경기', '강원', '충북', '충남', '전북', '전남', '경북', '경남', '제주']
            region_counts = {k: 0 for k in region_keywords}
            if '특이사항' in df.columns:
                for item in df['특이사항'].dropna().astype(str):
                    if '지역제한' in item:
                        for k in region_keywords:
                            if k in item: region_counts[k] += 1
            region_series = pd.Series(region_counts)
            if region_series.sum() > 0: region_series = region_series[region_series > 0]
            st.bar_chart(region_series)
        with top_col2:
            st.subheader("🔥 주요 특이사항 발생 빈도")
            if '특이사항' in df.columns:
                ignore_words = ['-', 'nan', 'none', '', '없음', '소방']
                valid_specials = df['특이사항'].astype(str).str.strip()
                special_df = df[~valid_specials.str.lower().isin(ignore_words)]
                if not special_df.empty:
                    specials_list = special_df['특이사항'].astype(str).str.replace('🔥', '').str.replace('🔴', '').str.replace('🔵', '').str.split(',')
                    all_specials = [item.strip() for sublist in specials_list if isinstance(sublist, list) for item in sublist if item.strip() and item.strip().lower() not in ignore_words]
                    if all_specials: st.bar_chart(pd.Series(all_specials).value_counts().head(10))
        st.divider()
        bottom_col1, bottom_col2 = st.columns(2)
        with bottom_col1:
            st.subheader("📈 전체 공고 발주 추이 (연도/일별 통합)")
            if '등록일' in df.columns and not parsed_dates.empty:
                today = pd.Timestamp.now()
                valid_dates = parsed_dates[(parsed_dates.dt.year >= 2022) & (parsed_dates <= today + pd.Timedelta(days=1))]
                if not valid_dates.empty:
                    date_counts = valid_dates.value_counts().sort_index()
                    full_range = pd.date_range(start=date_counts.index.min(), end=today)
                    date_counts = date_counts.reindex(full_range, fill_value=0)
                    chart_df = date_counts.reset_index()
                    chart_df.columns = ['날짜', '공고 건수']
                    fig = px.area(chart_df, x='날짜', y='공고 건수')
                    fig.update_xaxes(rangeslider_visible=True, rangeselector=dict(buttons=list([dict(count=1, label="1개월", step="month", stepmode="backward"), dict(step="all", label="전체 보기")])))
                    fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), hovermode="x unified")
                    st.plotly_chart(fig, use_container_width=True)
        with bottom_col2:
            st.subheader("🏆 전체 최다 발주처 Top 10")
            st.bar_chart(df['출처'].value_counts().head(10))

        st.divider()
        st.subheader("🔵 '내 업무' 타겟 공고 전용 집중 분석")
        df_my = df[df['검토유무'] == '내업무맞음']
        if not df_my.empty:
            my_c1, my_c2 = st.columns(2)
            with my_c1:
                st.markdown("**🏆 '내 업무' 최다 발주 기관 Top 5**")
                st.bar_chart(df_my['출처'].value_counts().head(5))
            with my_c2:
                st.markdown("**📍 '내 업무' 집중 지역 현황**")
                my_region_counts = {k: 0 for k in region_keywords}
                if '특이사항' in df_my.columns:
                    for item in df_my['특이사항'].dropna().astype(str):
                        if '지역제한' in item:
                            for k in region_keywords:
                                if k in item: my_region_counts[k] += 1
                my_region_series = pd.Series(my_region_counts)
                if my_region_series.sum() > 0: my_region_series = my_region_series[my_region_series > 0]
                st.bar_chart(my_region_series)
        else:
            st.info("아직 '내 업무 맞음'으로 분류된 공고가 없어 전용 통계를 제공할 수 없습니다.")

# ==========================================
# 3. 🎯 타겟 공고 (내 업무) 메뉴 
# ==========================================
elif menu == "🎯 타겟 공고 (내 업무)":
    st.title("🎯 수동 분류된 '내 업무' 공고 리스트")
    st.info("💡 [공고 자동수집] 메뉴에서 수동으로 '🔵 우리의 업무 맞음'으로 분류하신 핵심 공고들만 모아서 보여줍니다.")
    try:
        df = get_google_sheet("notices")
        if not df.empty and '검토유무' in df.columns:
            df_my = df[df['검토유무'] == '내업무맞음'].copy()
            if not df_my.empty:
                st.success(f"🎉 현재 총 {len(df_my)}건의 '내 업무' 공고가 보관되어 있습니다.")
                display_columns = ['출처', '등록일', '공고제목', '특이사항', '상세링크']
                st.dataframe(
                    df_my[display_columns],
                    column_config={"상세링크": st.column_config.LinkColumn("상세링크")},
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.warning("아직 분류된 내 업무 공고가 없습니다. [공고 자동수집] 탭에서 공고 앞 체크박스를 누르고 '우리의 업무 맞음(파랑)'을 눌러주세요.")
        else:
            st.warning("수집된 데이터가 존재하지 않습니다.")
    except Exception as e:
        st.error(f"데이터를 불러오는 중 오류가 발생했습니다: {e}")

# ==========================================
# 4. 사이트 검토 필요(오류/개편) 메뉴
# ==========================================
elif menu == "사이트 검토 필요(오류/개편)":
    st.title("🚨 사이트 검토 필요 (오류/개편)")
    try:
        df_empty = get_google_sheet("empty_orgs")
        if not df_empty.empty and '분류' in df_empty.columns:
            error_df = df_empty[df_empty['분류'] != '공고 없음']
            empty_df = df_empty[df_empty['분류'] == '공고 없음']
            st.error(f"**아래 {len(error_df)}개 기관의 수동 검토가 필요합니다.**")
            if not error_df.empty: st.dataframe(error_df, use_container_width=True)
            st.divider()
            st.write(f"💡 사이트는 정상인데 단순히 새 공고가 없는 기관: **{len(empty_df)}곳**")
            with st.expander("단순 공고 없음 기관 목록 보기"): st.dataframe(empty_df, use_container_width=True)
    except Exception as e: pass

# ==========================================
# 5. 📝 게시판 / 메모장 메뉴
# ==========================================
elif menu == "📝 게시판 / 메모장":
    st.title("📝 팀 게시판 및 메모장")
    st.info("팀원들과 업무 진행 상황을 공유하거나, 필요한 개선사항을 자유롭게 메모해두세요.")
    
    with st.form("memo_form", clear_on_submit=True):
        memo_text = st.text_area("✍️ 새로운 메모 남기기", height=100, placeholder="여기에 내용을 입력하세요...")
        submitted = st.form_submit_button("메모 등록하기", type="primary")
        if submitted and memo_text.strip():
            try:
                gc = gspread.service_account(filename="google_key.json")
                doc = gc.open("맞춤공고_DB")
                try: ws_memos = doc.worksheet("memos")
                except gspread.exceptions.WorksheetNotFound:
                    ws_memos = doc.add_worksheet("memos", 100, 2)
                    ws_memos.update(range_name="A1:B1", values=[["작성일시", "메모 내용"]])
                ws_memos.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), memo_text.strip()])
                st.success("✅ 메모가 성공적으로 등록되었습니다!")
                get_google_sheet.clear()
                time.sleep(0.5)
                st.rerun()
            except Exception as e:
                st.error(f"메모 등록 중 오류가 발생했습니다: {e}")
                
    st.divider()
    st.subheader("📋 등록된 메모 목록")
    df_memos = get_google_sheet("memos")
    if not df_memos.empty and '작성일시' in df_memos.columns:
        df_memos = df_memos.sort_values(by="작성일시", ascending=False).reset_index(drop=True)
        st.dataframe(df_memos, use_container_width=True)
    else:
        st.write("아직 등록된 메모가 없습니다.")
