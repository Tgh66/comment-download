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
import math
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
st.set_page_config(page_title="B站评论抓取神器 (终极版)", page_icon="🔥", layout="wide")

# --- 初始化 Session State ---
if 'comments_data' not in st.session_state:
    st.session_state.comments_data = None
if 'video_title' not in st.session_state:
    st.session_state.video_title = ""
if 'bv_id' not in st.session_state:
    st.session_state.bv_id = ""

# --- 核心辅助函数 (URL解析增强版) ---

def extract_bv_robust(text):
    """
    终极 BV 号提取函数，支持：
    1. 标准链接
    2. 带有中文标题的混合文本
    3. b23.tv 短链接 (自动解析跳转)
    4. 格式错误的链接 (如 http://1https//...)
    """
    if not text:
        return None, None

    # 1. 尝试直接正则匹配 BV 号 (最快，最准)
    # 只要字符串里包含 BV.......... 就能匹配到，忽略周围的乱码
    bv_pattern = r"(BV[a-zA-Z0-9]{10})"
    match = re.search(bv_pattern, text)
    
    if match:
        return match.group(1), "Direct Match"

    # 2. 如果没找到 BV 号，检查是否包含 b23.tv 短链接
    # 提取 text 中的 http...b23.tv... 部分
    short_link_pattern = r"(https?://b23\.tv/[a-zA-Z0-9]+)"
    short_match = re.search(short_link_pattern, text)
    
    if short_match:
        short_url = short_match.group(1)
        try:
            # 模拟浏览器访问短链接，获取重定向后的真实 URL
            headers = {"User-Agent": "Mozilla/5.0"}
            resp = requests.get(short_url, headers=headers, allow_redirects=True, timeout=10)
            real_url = resp.url
            
            # 从跳转后的 URL 中再次查找 BV 号
            match_redirect = re.search(bv_pattern, real_url)
            if match_redirect:
                return match_redirect.group(1), real_url
        except Exception as e:
            print(f"短链接解析失败: {e}")
            return None, None

    return None, None

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

# --- PDF 生成函数 ---
def create_pdf(dataframe, title):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []

    font_name = 'STSong-Light'
    try:
        pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    except Exception as e:
        font_name = "Helvetica"

    styles = getSampleStyleSheet()
    title_style = styles['Title']
    if font_name == 'STSong-Light':
        title_style.fontName = font_name
    
    cell_style = ParagraphStyle(
        name='CellStyle',
        fontName=font_name,
        fontSize=9,
        leading=12,
        wordWrap='CJK'
    )

    safe_title = re.sub(r'[^\w\s\u4e00-\u9fa5]', '', title)
    elements.append(Paragraph(f"视频评论: {safe_title}", title_style))
    elements.append(Paragraph("<br/><br/>", styles['Normal']))

    col_widths = [70, 240, 40, 80, 40] 
    headers = dataframe.columns.to_list()
    processed_data = [headers]

    for index, row in dataframe.iterrows():
        new_row = []
        uname = str(row['用户名'])
        content = str(row['内容'])
        like = str(row['点赞'])
        time_str = str(row['时间'])
        reply_count = str(row['回复数'])

        content = re.sub(r'[^\x00-\x7F\u4e00-\u9fa5]+', '', content)
        uname = re.sub(r'[^\x00-\x7F\u4e00-\u9fa5]+', '', uname)

        new_row.append(Paragraph(uname, cell_style)) 
        new_row.append(Paragraph(content, cell_style))
        new_row.append(like)
        new_row.append(time_str) 
        new_row.append(reply_count)
        processed_data.append(new_row)

    t = Table(processed_data, colWidths=col_widths)
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

# --- 异步并发抓取逻辑 ---
async def fetch_one_page(oid, page, credential, semaphore):
    async with semaphore:
        try:
            await asyncio.sleep(0.05)
            c = await comment.get_comments(oid, VideoTypeFix(), page, credential=credential)
            return c
        except Exception as e:
            return None

async def fetch_comments_async(bv_id, fetch_mode, limit_pages, credential=None):
    v = video.Video(bvid=bv_id, credential=credential)
    
    try:
        info = await v.get_info()
        oid = info['aid']
        title = info['title']
    except Exception as e:
        return None, f"无法获取视频信息: {str(e)}"

    comments_data = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    status_text.text("🚀 正在初始化...")

    # 1. 抓取第1页
    try:
        page_1_data = await comment.get_comments(oid, VideoTypeFix(), 1, credential=credential)
    except ResponseCodeException as e:
        return None, f"抓取第1页失败，错误码: {e.code}"
    
    if not page_1_data:
        return title, []

    page_info = page_1_data.get('page', {})
    total_count = page_info.get('count', 0)
    total_pages_available = math.ceil(total_count / 20)
    
    if fetch_mode == "全部下载":
        target_pages = total_pages_available
        status_text.text(f"共 {total_count} 条评论，约 {target_pages} 页，全速下载中...")
    else:
        target_pages = min(total_pages_available, limit_pages)
        status_text.text(f"准备下载前 {target_pages} 页...")

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

    # 2. 并发后续页面
    if target_pages > 1:
        sem = asyncio.Semaphore(5)
        tasks = []
        for p in range(2, target_pages + 1):
            task = fetch_one_page(oid, p, credential, sem)
            tasks.append(task)
        
        finished_count = 1
        for future in asyncio.as_completed(tasks):
            result = await future
            finished_count += 1
            if result:
                new_items = process_comments_json(result)
                comments_data.extend(new_items)
            progress = min(finished_count / target_pages, 1.0)
            progress_bar.progress(progress)
            status_text.text(f"⚡ 并发下载中: {finished_count}/{target_pages} 页")

    status_text.text("✅ 下载完成！")
    await asyncio.sleep(0.5)
    return title, comments_data

# --- UI 布局 ---

st.title("⚡ B站评论抓取 (终极版)")

with st.sidebar:
    st.header("🔐 身份验证 (推荐)")
    st.info("粘贴 Cookie JSON")
    cookie_input = st.text_area("Cookie 数据:", height=150, placeholder='{"url": "...", "cookies": [...]}')
    
    cred = None
    if cookie_input:
        cred, err_msg = parse_cookie_json(cookie_input)
        if cred:
            st.success("✅ Cookie 解析成功！")
        else:
            st.error(f"❌ {err_msg}")
            
    st.divider()
    st.header("⚙️ 下载设置")
    fetch_mode = st.radio("下载模式", ("指定页数", "全部下载"))
    
    limit_pages = 5
    if fetch_mode == "指定页数":
        limit_pages = st.slider("选择抓取页数", 1, 100, 5)

# 优化的输入提示
url_input = st.text_input(
    "👇 视频链接 (支持各种乱码格式、短链接、中文标题混排)", 
    placeholder="直接粘贴复制的内容，例如：【视频标题】 https://b23.tv/..."
)

# === 抓取 ===
if st.button("开始抓取", type="primary"):
    if not url_input:
        st.warning("请粘贴内容")
    else:
        # 使用新的鲁棒提取函数
        with st.spinner("正在解析链接..."):
            bv_id, _ = extract_bv_robust(url_input)
            
        if not bv_id:
            st.error("无法识别 BV 号，请检查链接是否有效")
        else:
            st.success(f"识别成功: {bv_id}")
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
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
        sort_order = st.radio("排序方式 (按点赞)", ("默认 (时间)", "点赞数 (高到低)", "点赞数 (低到高)"))
        
        if sort_order == "点赞数 (高到低)":
            df = df.sort_values(by="点赞", ascending=False)
        elif sort_order == "点赞数 (低到高)":
            df = df.sort_values(by="点赞", ascending=True)
        
        st.write(f"共抓取 {len(df)} 条评论")
        
        csv = df.to_csv(index=False).encode('utf-8-sig')
        st.download_button(label="📥 下载 CSV", data=csv, file_name=f"{bv_id}_comments.csv", mime="text/csv")
        
        st.write("---")
        if st.button("生成 PDF"):
            with st.spinner("正在生成 PDF..."):
                pdf_buffer = create_pdf(df, title)
                if pdf_buffer:
                    st.success("生成成功！")
                    st.download_button(label="📥 点击下载 PDF", data=pdf_buffer, file_name=f"{bv_id}_comments.pdf", mime="application/pdf")
                else:
                    st.error("PDF 生成失败。")

    with col1:
        st.dataframe(df, use_container_width=True, height=500)
        
    if st.button("🔄 清空结果"):
        st.session_state.comments_data = None
        st.rerun()
