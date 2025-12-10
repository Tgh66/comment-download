import streamlit as st
import pandas as pd
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTF
import time

# ==========================================
# 第一部分：你现有的核心逻辑 (保持不变)
# ==========================================

# 假设这是你现有的爬虫函数，你需要确保它返回包含 'likes' (点赞数) 的字典
# 如果你现在的代码只是 print 出来，请修改它让它 return 一个字典
def existing_scraper_function(url, cookies=None):
    """
    这里代表你现有的复杂逻辑：
    1. 识别是B站/抖音/Youtube
    2. 使用Cookie认证
    3. 解析视频信息
    """
    # 模拟返回的数据结构 (请确保你的爬虫提取了 'likes' 字段)
    # 注意：点赞数必须是数字类型 (int)，如果是字符串 '1.2万' 需要转换
    
    # -------------------------------------------------
    # ⚠️在此处保留你的实际代码，不要使用下面的模拟代码⚠️
    # -------------------------------------------------
    import random
    # 模拟数据仅供演示排序功能
    mock_data = {
        "title": f"测试视频标题 - {url[-5:]}",
        "url": url,
        "author": "测试作者",
        "likes": random.randint(100, 100000), # 关键字段：点赞数
        "platform": "Bilibili" if "bilibili" in url else "Other"
    }
    time.sleep(0.5) # 模拟请求耗时
    return mock_data

# ==========================================
# 第二部分：新增的 PDF 生成工具函数
# ==========================================

def generate_pdf(dataframe):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 40
    
    # 注意：ReportLab默认不支持中文，需要注册字体。
    # 为了防止报错，这里用通用处理，实际部署建议下载 'SimHei.ttf' 并注册
    # 或者仅在PDF中输出英文/数字，中文可能显示乱码
    p.setFont("Helvetica", 10) 
    
    p.drawString(30, y, "Video Export List")
    y -= 20
    
    for index, row in dataframe.iterrows():
        if y < 40: # 换页处理
            p.showPage()
            p.setFont("Helvetica", 10)
            y = height - 40
            
        # 简单写入 标题 (截断以防过长) 和 点赞数
        # 实际项目中建议处理中文字体
        title_text = str(row['title'])[:40] 
        text = f"Title: {title_text}... | Likes: {row['likes']} | URL: {row['url']}"
        p.drawString(30, y, text)
        y -= 20
        
    p.save()
    buffer.seek(0)
    return buffer

# ==========================================
# 第三部分：Streamlit 主界面逻辑 (修改部分)
# ==========================================

st.title("多平台视频抓取工具 (含排序导出)")

# 输入区域
urls_input = st.text_area("请输入视频链接 (一行一个):")
run_button = st.button("开始抓取")

# 初始化 session_state 用于存储抓取结果，防止排序时重刷消失
if 'scraped_data' not in st.session_state:
    st.session_state.scraped_data = []

if run_button and urls_input:
    url_list = urls_input.split('\n')
    results = []
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    # 1. 执行抓取
    for i, url in enumerate(url_list):
        if url.strip():
            status_text.text(f"正在分析: {url}")
            try:
                # 调用你现有的逻辑
                data = existing_scraper_function(url.strip())
                if data:
                    results.append(data)
            except Exception as e:
                st.error(f"链接 {url} 解析失败: {e}")
        progress_bar.progress((i + 1) / len(url_list))
    
    # 存入 Session State
    st.session_state.scraped_data = results
    status_text.text("分析完成！")

# 2. 结果展示与处理区域
if st.session_state.scraped_data:
    st.divider()
    st.subheader("📊 结果分析")
    
    # 将列表转换为 Pandas DataFrame
    df = pd.DataFrame(st.session_state.scraped_data)
    
    # --- 新增功能：排序控制 ---
    col1, col2 = st.columns([1, 3])
    with col1:
        sort_method = st.radio(
            "按照点赞数排序:",
            ("降序 (从高到低)", "升序 (从低到高)")
        )
    
    # 执行排序逻辑
    ascending_bool = True if "升序" in sort_method else False
    if 'likes' in df.columns:
        df = df.sort_values(by='likes', ascending=ascending_bool)
        # 重置索引，让序号从1开始
        df = df.reset_index(drop=True)
    else:
        st.warning("未检测到'likes'字段，无法排序。请检查爬虫返回值。")

    # 显示表格
    st.dataframe(
        df, 
        column_config={
            "url": st.column_config.LinkColumn("视频链接"),
            "likes": st.column_config.NumberColumn("点赞数", format="%d")
        },
        use_container_width=True
    )

    # --- 新增功能：导出下载 ---
    st.subheader("💾 数据导出")
    d_col1, d_col2 = st.columns(2)
    
    # 导出 CSV
    csv_data = df.to_csv(index=False).encode('utf-8-sig') # utf-8-sig 解决Excel中文乱码
    with d_col1:
        st.download_button(
            label="下载 CSV 表格",
            data=csv_data,
            file_name='video_stats.csv',
            mime='text/csv',
        )
        
    # 导出 PDF
    with d_col2:
        pdf_data = generate_pdf(df)
        st.download_button(
            label="下载 PDF 报告",
            data=pdf_data,
            file_name='video_stats.pdf',
            mime='application/pdf',
        )
