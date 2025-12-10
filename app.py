import streamlit as st
import yt_dlp
import pandas as pd
import io
from docx import Document
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

# --- 核心函数：获取视频信息（含点赞数） ---
def get_video_metadata(urls):
    data = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True, # 尝试快速抓取
    }

    for i, url in enumerate(urls):
        if not url.strip():
            continue
        
        status_text.text(f"正在分析第 {i+1} 个链接: {url} ...")
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                # 提取关键信息，如果没有则填入默认值
                title = info.get('title', 'Unknown Title')
                like_count = info.get('like_count', 0) # 如果没有获取到点赞，默认为0
                uploader = info.get('uploader', 'Unknown')
                view_count = info.get('view_count', 0)
                
                # 处理None的情况（有些平台可能隐藏数据）
                if like_count is None: like_count = 0
                if view_count is None: view_count = 0

                data.append({
                    "标题": title,
                    "点赞数": like_count,
                    "播放量": view_count,
                    "UP主/作者": uploader,
                    "链接": url
                })
        except Exception as e:
            st.error(f"链接 {url} 解析失败: {e}")
        
        progress_bar.progress((i + 1) / len(urls))
    
    status_text.text("分析完成！")
    progress_bar.empty()
    return pd.DataFrame(data)

# --- 辅助函数：生成 Word 文件 ---
def generate_word(df):
    doc = Document()
    doc.add_heading('视频数据统计', 0)
    
    # 添加表格
    t = doc.add_table(rows=1, cols=len(df.columns))
    t.style = 'Table Grid'
    
    # 表头
    hdr_cells = t.rows[0].cells
    for i, col_name in enumerate(df.columns):
        hdr_cells[i].text = str(col_name)
    
    # 数据行
    for index, row in df.iterrows():
        row_cells = t.add_row().cells
        for i, value in enumerate(row):
            row_cells[i].text = str(value)
            
    bio = io.BytesIO()
    doc.save(bio)
    return bio.getvalue()

# --- 辅助函数：生成 PDF 文件 ---
def generate_pdf(df):
    bio = io.BytesIO()
    doc = SimpleDocTemplate(bio, pagesize=letter)
    elements = []
    
    # 转换数据为列表格式 [列名, 行1, 行2...]
    data = [df.columns.to_list()] + df.values.tolist()
    
    # 解决中文乱码通常需要注册字体，这里为了演示稳定，PDF可能无法显示特殊中文字符
    # 实际项目中建议使用 reportlab 注册中文字体，或者直接推荐用户下载 Excel/Word
    
    t = Table(data)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    elements.append(t)
    doc.build(elements)
    return bio.getvalue()

# --- Streamlit 界面布局 ---
st.set_page_config(page_title="视频数据抓取与排序工具", layout="wide")

st.title("📊 视频数据抓取 & 智能排序工具")
st.markdown("输入视频链接，自动抓取点赞数并生成报表。支持 Bilibili, YouTube, Douyin 等。")

# 1. 输入区域
st.subheader("1. 输入视频链接 (一行一个)")
url_input = st.text_area("粘贴链接到这里：", height=150, placeholder="https://www.bilibili.com/video/...\nhttps://www.youtube.com/watch?v=...")

if st.button("开始抓取数据"):
    if not url_input.strip():
        st.warning("请先输入链接！")
    else:
        urls = [line.strip() for line in url_input.split('\n') if line.strip()]
        
        # 获取数据并存入 Session State 防止刷新丢失
        st.session_state['df'] = get_video_metadata(urls)

# 2. 数据处理与展示区域
if 'df' in st.session_state:
    df = st.session_state['df']
    
    st.divider()
    st.subheader("2. 数据排序与预览")
    
    col1, col2 = st.columns(2)
    with col1:
        sort_by = st.selectbox("选择排序依据", ["点赞数", "播放量"], index=0)
    with col2:
        sort_order = st.radio("排序方式", ["正序 (从低到高)", "倒序 (从高到低)"], index=1)
    
    # 执行排序
    ascending = True if sort_order == "正序 (从低到高)" else False
    sorted_df = df.sort_values(by=sort_by, ascending=ascending)
    
    # 增加排名列
    sorted_df.reset_index(drop=True, inplace=True)
    sorted_df.index = sorted_df.index + 1
    st.dataframe(sorted_df, use_container_width=True)

    # 3. 导出区域
    st.divider()
    st.subheader("3. 导出数据")
    
    c1, c2, c3, c4 = st.columns(4)
    
    # CSV 下载
    csv = sorted_df.to_csv(index=False).encode('utf-8-sig')
    c1.download_button("下载 CSV", data=csv, file_name="video_stats.csv", mime="text/csv")
    
    # Excel 下载
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        sorted_df.to_excel(writer, index=False, sheet_name='Sheet1')
    c2.download_button("下载 Excel", data=buffer.getvalue(), file_name="video_stats.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    
    # Word 下载
    word_data = generate_word(sorted_df)
    c3.download_button("下载 Word", data=word_data, file_name="video_stats.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

    # PDF 下载 (注：Python生成PDF处理中文较复杂，这里仅作基础实现)
    pdf_data = generate_pdf(sorted_df)
    c4.download_button("下载 PDF", data=pdf_data, file_name="video_stats.pdf", mime="application/pdf")
