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
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors

# --- 页面配置 ---
st.set_page_config(page_title="B站评论抓取神器 (排序+PDF版)", page_icon="🍪", layout="wide")

# --- 初始化 Session State (用于持久化保存数据) ---
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

# --- PDF 生成函数 (修复字体路径版) ---
def create_pdf(dataframe, title):
    """
    将 DataFrame 转换为 PDF 字节流
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []

    # 1. 注册字体 (核心修改：优先读取项目目录下的字体文件)
    font_name = "Helvetica" # 默认英文作为保底
    
    # 你的字体文件名，必须和你上传到 GitHub 的文件名完全一致！
    font_file = "SimHei.ttf" 
    
    # 获取当前脚本所在的绝对路径，确保在云端也能找到文件
    current_dir = os.path.dirname(os.path.abspath(__file__))
    font_path = os.path.join(current_dir, font_file)

    if os.path.exists(font_path):
        try:
            # 注册项目文件夹里的字体
            pdfmetrics.registerFont(TTF('SimHei', font_path))
            font_name = 'SimHei'
        except Exception as e:
            print(f"字体注册失败: {e}")
    else:
        # 如果找不到文件，尝试系统的（本地调试用）
        try:
            pdfmetrics.registerFont(TTF('SimHei', 'simhei.ttf')) # Windows 默认路径尝试
            font_name = 'SimHei'
        except:
            pass

    # 2. 准备标题
    styles = getSampleStyleSheet()
    title_style = styles['Title']
    # 如果加载了中文体，应用到标题
    if font_name == 'SimHei':
        title_style.fontName = font_name
    
    safe_title = re.sub(r'[^\w\s\u4e00-\u9fa5]', '', title)
    elements.append(Paragraph(f"视频评论: {safe_title}", title_style))
    elements.append(Paragraph("<br/><br/>", styles['Normal']))

    # 3. 准备表格数据
    data = [dataframe.columns.to_list()] + dataframe.values.tolist()

    processed_data = []
    for row in data:
        new_row = []
        for item in row:
            str_item = str(item)
            if len(str_item) > 50:
                str_item = str_item[:50] + "..."
            # 清理特殊字符
            str_item = re.sub(r'[^\x00-\x7F\u4e00-\u9fa5]+', '', str_item) 
            new_row.append(str_item)
        processed_data.append(new_row)

    # 4. 创建表格对象
    t = Table(processed_data)
    
    # 5. 设置表格样式
    style = TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), font_name), # 全局应用该字体
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
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

# 👇 【核心修复】定义一个自定义类，完美骗过库的检查
class VideoTypeFix:
    value = 1  # 视频类型 ID 为 1

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
                # 👇 【关键修改】使用自定义对象 VideoTypeFix() 代替数字 1
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
                    '点赞': int(r['like']), # 确保转换为数字，方便排序
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

st.title("🍪 B站评论抓取 (排序+PDF版)")

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

# === 第一部分：抓取逻辑 ===
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
            
            # 抓取数据
            title, data = loop.run_until_complete(fetch_comments_async(bv_id, max_pages, credential=cred))
            
            if isinstance(data, str):
                st.error(data)
            elif data:
                # 【重要修改】将数据存入 Session State，而不是直接显示
                st.session_state.comments_data = data
                st.session_state.video_title = title
                st.session_state.bv_id = bv_id
                st.rerun() # 强制刷新页面，进入下方的显示逻辑
            else:
                st.warning("未抓取到数据。")

# === 第二部分：显示与操作逻辑 (只要 Session State 里有数据就显示) ===
if st.session_state.comments_data:
    st.divider()
    
    # 从 State 中读取数据
    title = st.session_state.video_title
    bv_id = st.session_state.bv_id
    data = st.session_state.comments_data
    
    st.subheader(f"📄 {title}")
    
    df = pd.DataFrame(data)
    
    # 布局容器
    col1, col2 = st.columns([3, 1])
    
    with col2:
        st.markdown("### 🛠️ 数据选项")
        
        # 1. 排序选择
        sort_order = st.radio(
            "排序方式 (按点赞)",
            ("默认 (时间)", "点赞数 (高到低)", "点赞数 (低到高)")
        )
        
        # 2. 应用排序
        if sort_order == "点赞数 (高到低)":
            df = df.sort_values(by="点赞", ascending=False)
        elif sort_order == "点赞数 (低到高)":
            df = df.sort_values(by="点赞", ascending=True)
        
        st.write(f"共抓取 {len(df)} 条评论")
        
        # 3. CSV 下载
        csv = df.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📥 下载 CSV",
            data=csv,
            file_name=f"{bv_id}_comments.csv",
            mime="text/csv"
        )
        
        # 4. PDF 下载
        st.write("---")
        # 这里使用嵌套 Button 逻辑，当点击生成后，数据依然存在，所以不会跳回首页
        if st.button("生成 PDF"):
            with st.spinner("正在生成 PDF (可能需要几秒)..."):
                # 使用当前排序后的 df 生成 PDF
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
        # 展示表格 (会展示排序后的结果)
        st.dataframe(df, use_container_width=True, height=500)
        
    # 如果想清除结果，给个重置按钮
    if st.button("🔄 清空结果"):
        st.session_state.comments_data = None
        st.rerun()
