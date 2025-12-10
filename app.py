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
st.set_page_config(page_title="B站评论抓取神器 (完美PDF版)", page_icon="🍪", layout="wide")

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
    # leading 是行间距，fontSize 是字号
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
    # 定义列宽 (单位: point, A4 宽度约为 595, 去掉页边距可用约 450-500)
    # 列顺序: 用户名, 内容, 点赞, 时间, 回复数
    col_widths = [70, 240, 40, 80, 40] 

    # 处理表头
    headers = dataframe.columns.to_list()
    processed_data = [headers]

    # 处理每一行数据
    for index, row in dataframe.iterrows():
        new_row = []
        
        # 提取每一列的数据
        uname = str(row['用户名'])
        content = str(row['内容'])
        like = str(row['点赞'])
        time_str = str(row['时间'])
        reply_count = str(row['回复数'])

        # 清理 PDF 不支持的字符
        content = re.sub(r'[^\x00-\x7F\u4e00-\u9fa5]+', '', content)
        uname = re.sub(r'[^\x00-\x7F\u4e00-\u9fa5]+', '', uname)

        # 【核心逻辑】将长文本转换为 Paragraph 对象，实现自动换行
        # 其他短字段可以直接用字符串，或者也转为 Paragraph 以保持格式统一
        # 这里我们将 内容(索引1) 设为 Paragraph
        new_row.append(Paragraph(uname, cell_style)) # 用户名也可能长，加上保险
        new_row.append(Paragraph(content, cell_style)) # 内容必须换行
        new_row.append(like)
        new_row.append(time_str) # 时间通常固定宽度
        new_row.append(reply_count)

        processed_data.append(new_row)

    # 4. 创建表格对象，传入列宽参数
    t = Table(processed_data, colWidths=col_widths)
    
    # 5. 设置表格样式
    style = TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), font_name), 
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey), # 表头背景
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke), # 表头文字颜色
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'), # 表头居中
        ('VALIGN', (0, 0), (-1, -1), 'TOP'), # 所有单元格内容顶对齐 (对长文很重要)
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black), # 表格线
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

async def fetch_comments_async(bv_id, limit_pages, credential=None):
    """
    异步抓取评论
    """
    v = video.Video(bvid=bv_id, credential=credential)
    
    try:
        info = await v.get_info()
        oid = info['aid']
        title = info['title']
    except Exception as e:
        return None, f"无法获取视频信息: {str(e)}"

    comments_data = []
    page = 1
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    try:
        while page <= limit_pages:
            status_text.text(f"🚀 正在抓取第 {page}/{limit_pages} 页...")
            
            try:
                c = await comment.get_comments(oid, VideoTypeFix(), page, credential=credential)
            except ResponseCodeException as e:
                if e.code == -404: break
                st.warning(f"API 错误代码: {e.code}")
                break
            except Exception as e:
                st.warning(f"未知错误: {e}")
                break

            if 'replies' not in c or not c['replies']:
                status_text.text("✅ 已到达底部")
                break
            
            for r in c['replies']:
                item = {
                    '用户名': r['member']['uname'],
                    '内容': r['content']['message'],
                    '点赞': int(r['like']), 
                    '时间': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(r['ctime'])),
                    '回复数': int(r['count'])
                }
                comments_data.append(item)
                
                if r.get('replies'):
                    for sub in r['replies']:
                        sub_item = {
                            '用户名': sub['member']['uname'],
                            '内容': f"[回复] {sub['content']['message']}",
                            '点赞': int(sub['like']),
                            '时间': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(sub['ctime'])),
                            '回复数': 0
                        }
                        comments_data.append(sub_item)

            progress_bar.progress(min(page / limit_pages, 1.0))
            page += 1
            await asyncio.sleep(0.5)
            
    except Exception as e:
        st.error(f"中断: {e}")
    
    return title, comments_data

# --- UI 布局 ---

st.title("🍪 B站评论抓取 (完美PDF版)")

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
    max_pages = st.slider("抓取页数", 1, 100, 5)

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
            
            title, data = loop.run_until_complete(fetch_comments_async(bv_id, max_pages, credential=cred))
            
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
