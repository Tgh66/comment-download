import streamlit as st
import asyncio
import pandas as pd
import re
import time
import requests
import json
import urllib.parse
import io 
import os
import math  # 新增：用于计算页数
from bilibili_api import video, comment, Credential
from bilibili_api.exceptions import ResponseCodeException

# --- PDF 生成相关库 ---
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont 
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# --- 页面配置 ---
st.set_page_config(page_title="B站评论抓取神器 (并发版)", page_icon="⚡", layout="wide")

# --- 初始化 Session State ---
if 'comments_data' not in st.session_state:
    st.session_state.comments_data = None
if 'video_title' not in st.session_state:
    st.session_state.video_title = ""
if 'bv_id' not in st.session_state:
    st.session_state.bv_id = ""

# --- 辅助函数 ---

def get_real_url(url):
    """处理 b23.tv 短链接"""
    if "b23.tv" in url:
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            resp = requests.get(url, headers=headers, allow_redirects=True, timeout=10)
            return resp.url
        except:
            return url
    return url

def extract_bv(url):
    """提取BV号"""
    real_url = get_real_url(url)
    pattern = r"(BV[a-zA-Z0-9]{10})"
    match = re.search(pattern, real_url)
    if match:
        return match.group(1), real_url
    return None, real_url

def parse_cookie_json(json_str):
    """解析用户粘贴的 JSON Cookie 数据"""
    try:
        data = json.loads(json_str)
        
        cookie_list = []
        if isinstance(data, list):
            cookie_list = data
        elif isinstance(data, dict) and "cookies" in data:
            cookie_list = data["cookies"]
        else:
            return None, "JSON 格式不正确，未找到 cookies 列表"

        cookies = {c['name']: c['value'] for c in cookie_list}
        
        sessdata = cookies.get('SESSDATA')
        bili_jct = cookies.get('bili_jct')
        buvid3 = cookies.get('buvid3')

        if not sessdata or not bili_jct:
            return None, "Cookie 中缺少 SESSDATA 或 bili_jct"

        sessdata = urllib.parse.unquote(sessdata)
        bili_jct = urllib.parse.unquote(bili_jct)

        cred = Credential(sessdata=sessdata, bili_jct=bili_jct, buvid3=buvid3)
        return cred, None

    except json.JSONDecodeError:
        return None, "JSON 解析失败，请检查复制是否完整"
    except Exception as e:
        return None, f"Cookie 解析错误: {str(e)}"

# --- PDF 生成函数 (自动换行 + 完整显示版) ---
def create_pdf(dataframe, title):
    """
    将 DataFrame 转换为 PDF 字节流 (支持自动换行)
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []

    # 1. 注册 CID 中文字体
    font_name = 'STSong-Light'
    try:
        pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    except Exception as e:
        font_name = "Helvetica"

    # 2. 定义样式
    styles = getSampleStyleSheet()
    
    # 标题样式
    title_style = styles['Title']
    if font_name == 'STSong-Light':
        title_style.fontName = font_name
    
    # 正文内容样式 (用于表格内的长文本自动换行)
    cell_style = ParagraphStyle(
        name='CellStyle',
        fontName=font_name,
        fontSize=9,
        leading=12,
        wordWrap='CJK' # 支持中文断行
    )

    safe_title = re.sub(r'[^\w\s\u4e00-\u9fa5]', '', title)
    elements.append(Paragraph(f"视频评论: {safe_title}", title_style))
    elements.append(Paragraph("<br/><br/>", styles['Normal']))

    # 3. 准备表格数据
    col_widths = [70, 240, 40, 80, 40] 

    # 处理表头
    headers = dataframe.columns.to_list()
    processed_data = [headers]

    # 处理每一行数据
    for index, row in dataframe.iterrows():
        new_row = []
        
        uname = str(row['用户名'])
        content = str(row['内容'])
        like = str(row['点赞'])
        time_str = str(row['时间'])
        reply_count = str(row['回复数'])

        # 清理 PDF 不支持的字符
        content = re.sub(r'[^\x00-\x7F\u4e00-\u9fa5]+', '', content)
        uname = re.sub(r'[^\x00-\x7F\u4e00-\u9fa5]+', '', uname)

        # 转换为 Paragraph 对象
        new_row.append(Paragraph(uname, cell_style)) 
        new_row.append(Paragraph(content, cell_style))
        new_row.append(like)
        new_row.append(time_str) 
        new_row.append(reply_count)

        processed_data.append(new_row)

    # 4. 创建表格对象
    t = Table(processed_data, colWidths=col_widths)
    
    # 5. 设置表格样式
    style = TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), font_name), 
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ])
    t.setStyle(style)
    elements.append(t)

    # 6. 生成 PDF
    try:
        doc.build(elements)
        buffer.seek(0)
        return buffer
    except Exception as e:
        print(f"PDF生成错误: {e}")
        return None

# 👇 自定义类
class VideoTypeFix:
    value = 1 

# --- 新增：处理单页抓取的包装函数 ---
async def fetch_one_page(oid, page, credential, semaphore):
    """
    单个页面抓取任务，受信号量控制并发数
    """
    async with semaphore:  # 限制同时运行的任务数量
        try:
            # 随机短暂休眠，防止触发 B 站风控
            await asyncio.sleep(0.05)
            c = await comment.get_comments(oid, VideoTypeFix(), page, credential=credential)
            return c
        except Exception as e:
            return None

async def fetch_comments_async(bv_id, fetch_mode, limit_pages, credential=None):
    """
    异步并发抓取评论 (核心重构)
    """
    v = video.Video(bvid=bv_id, credential=credential)
    
    try:
        info = await v.get_info()
        oid = info['aid']
        title = info['title']
    except Exception as e:
        return None, f"无法获取视频信息: {str(e)}"

    comments_data = []
    
    # 进度显示
    progress_bar = st.progress(0)
    status_text = st.empty()
    status_text.text("🚀 正在初始化...")

    # --- 第一步：抓取第1页，获取总页数信息 ---
    try:
        page_1_data = await comment.get_comments(oid, VideoTypeFix(), 1, credential=credential)
    except ResponseCodeException as e:
        return None, f"抓取第1页失败，错误码: {e.code}"
    
    if not page_1_data:
        return title, []

    # 计算总页数
    page_info = page_1_data.get('page', {})
    total_count = page_info.get('count', 0)
    total_pages_available = math.ceil(total_count / 20) # B站每页20条
    
    # 确定目标抓取页数
    if fetch_mode == "全部下载":
        target_pages = total_pages_available
        status_text.text(f"检测到共 {total_count} 条评论，约 {target_pages} 页，准备全部下载...")
    else:
        target_pages = min(total_pages_available, limit_pages)
        status_text.text(f"准备下载前 {target_pages} 页...")

    # 先处理第1页的数据
    def process_comments_json(c_json):
        processed = []
        if 'replies' not in c_json or not c_json['replies']:
            return processed
            
        for r in c_json['replies']:
            item = {
                '用户名': r['member']['uname'],
                '内容': r['content']['message'],
                '点赞': int(r['like']), 
                '时间': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(r['ctime'])),
                '回复数': int(r['count'])
            }
            processed.append(item)
            if r.get('replies'):
                for sub in r['replies']:
                    sub_item = {
                        '用户名': sub['member']['uname'],
                        '内容': f"[回复] {sub['content']['message']}",
                        '点赞': int(sub['like']),
                        '时间': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(sub['ctime'])),
                        '回复数': 0
                    }
                    processed.append(sub_item)
        return processed

    comments_data.extend(process_comments_json(page_1_data))
    progress_bar.progress(1 / max(target_pages, 1))

    # --- 第二步：并发抓取剩余页面 (如果有) ---
    if target_pages > 1:
        # 限制并发数为 5 (太高会被封)
        sem = asyncio.Semaphore(5)
        tasks = []
        
        # 创建任务列表 (从第2页开始)
        for p in range(2, target_pages + 1):
            task = fetch_one_page(oid, p, credential, sem)
            tasks.append(task)
        
        # 运行并发任务
        finished_count = 1 # 已经抓了第1页
        
        # as_completed 允许我们每完成一个任务就更新一次 UI
        for future in asyncio.as_completed(tasks):
            result = await future
            finished_count += 1
            
            if result:
                new_items = process_comments_json(result)
                comments_data.extend(new_items)
            
            # 更新进度条
            progress = min(finished_count / target_pages, 1.0)
            progress_bar.progress(progress)
            status_text.text(f"⚡ 正在并发下载: {finished_count}/{target_pages} 页...")

    status_text.text("✅ 下载完成！")
    await asyncio.sleep(0.5)
    
    return title, comments_data

# --- UI 布局 ---

st.title("⚡ B站评论抓取 (并发下载+全量版)")

with st.sidebar:
    st.header("🔐 身份验证 (推荐)")
    st.info("粘贴 Cookie JSON")
    
    cookie_input = st.text_area(
        "Cookie 数据:", 
        height=150,
        placeholder='{"url": "...", "cookies": [...]}'
    )
    
    cred = None
    if cookie_input:
        cred, err_msg = parse_cookie_json(cookie_input)
        if cred:
            st.success("✅ Cookie 解析成功！")
        else:
            st.error(f"❌ {err_msg}")
            
    st.divider()
    
    # --- UI 修改：增加模式选择 ---
    st.header("⚙️ 下载设置")
    fetch_mode = st.radio(
        "下载模式",
        ("指定页数", "全部下载")
    )
    
    limit_pages = 5 # 默认值
    if fetch_mode == "指定页数":
        limit_pages = st.slider("选择抓取页数", 1, 100, 5)
    else:
        st.caption("⚠️ 注意：'全部下载'可能耗时较长，且容易触发B站风控，请确保已登录Cookie。")

url_input = st.text_input("👇 视频链接", placeholder="https://b23.tv/...")

# === 抓取 ===
if st.button("开始抓取", type="primary"):
    if not url_input:
        st.warning("请输入链接")
    else:
        bv_id, real_url = extract_bv(url_input)
        if not bv_id:
            st.error("无法识别 BV 号")
        else:
            st.success(f"正在抓取: {bv_id}")
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            # 调用修改后的并发函数
            title, data = loop.run_until_complete(fetch_comments_async(bv_id, fetch_mode, limit_pages, credential=cred))
            
            if isinstance(data, str):
                st.error(data)
            elif data:
                st.session_state.comments_data = data
                st.session_state.video_title = title
                st.session_state.bv_id = bv_id
                st.rerun()
            else:
                st.warning("未抓取到数据。")

# === 显示 ===
if st.session_state.comments_data:
    st.divider()
    
    title = st.session_state.video_title
    bv_id = st.session_state.bv_id
    data = st.session_state.comments_data
    
    st.subheader(f"📄 {title}")
    
    df = pd.DataFrame(data)
    
    col1, col2 = st.columns([3, 1])
    
    with col2:
        st.markdown("### 🛠️ 数据选项")
        
        sort_order = st.radio(
            "排序方式 (按点赞)",
            ("默认 (时间)", "点赞数 (高到低)", "点赞数 (低到高)")
        )
        
        if sort_order == "点赞数 (高到低)":
            df = df.sort_values(by="点赞", ascending=False)
        elif sort_order == "点赞数 (低到高)":
            df = df.sort_values(by="点赞", ascending=True)
        
        st.write(f"共抓取 {len(df)} 条评论")
        
        csv = df.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📥 下载 CSV",
            data=csv,
            file_name=f"{bv_id}_comments.csv",
            mime="text/csv"
        )
        
        st.write("---")
        if st.button("生成 PDF"):
            with st.spinner("正在生成 PDF (支持长文换行)..."):
                pdf_buffer = create_pdf(df, title)
                if pdf_buffer:
                    st.success("生成成功！")
                    st.download_button(
                        label="📥 点击下载 PDF",
                        data=pdf_buffer,
                        file_name=f"{bv_id}_comments.pdf",
                        mime="application/pdf"
                    )
                else:
                    st.error("PDF 生成失败。")

    with col1:
        st.dataframe(df, use_container_width=True, height=500)
        
    if st.button("🔄 清空结果"):
        st.session_state.comments_data = None
        st.rerun()
