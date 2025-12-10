import streamlit as st
import yt_dlp
import os
import shutil
import re
import time
import asyncio
import pandas as pd
import requests
import json
import urllib.parse
import io
import math
import zipfile
from concurrent.futures import ThreadPoolExecutor
from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx
from bilibili_api import video, comment, Credential
from bilibili_api.exceptions import ResponseCodeException

# --- PDF 生成相关库 ---
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont 
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# ==========================================
# 1. 全局配置 (必须在所有 Streamlit 命令之前)
# ==========================================
st.set_page_config(page_title="Bilibili 全能工具箱", page_icon="🧰", layout="wide")

# ==========================================
# 2. 视频下载器模块 (Video Downloader)
# ==========================================
class VideoDownloaderApp:
    def __init__(self):
        self.DOWNLOAD_ROOT = "downloads"
        self.MAX_CONCURRENT_TASKS = 2
        self._init_environment()

    def _init_environment(self):
        if 'queue' not in st.session_state:
            st.session_state.queue = [] 
        if 'downloader_init' not in st.session_state:
            if os.path.exists(self.DOWNLOAD_ROOT):
                try:
                    shutil.rmtree(self.DOWNLOAD_ROOT)
                except:
                    pass
            os.makedirs(self.DOWNLOAD_ROOT, exist_ok=True)
            st.session_state['downloader_init'] = True

    def extract_url(self, text):
        if not text: return None
        url_pattern = r'(https?://[a-zA-Z0-9./?=&_%-]+)'
        match = re.search(url_pattern, text)
        if match: return match.group(1)
        return text

    def download_worker(self, task_info, ui_components, ctx):
        add_script_run_ctx(ctx=ctx)
        raw_url = task_info['url']
        
        # 使用时间戳作为文件夹名
        task_dir = os.path.join(self.DOWNLOAD_ROOT, f"task_{int(time.time())}_{hash(raw_url)}")
        os.makedirs(task_dir, exist_ok=True)

        def progress_hook(d):
            if d['status'] == 'downloading':
                p_str = d.get('_percent_str', '0%').replace('%', '')
                try:
                    percent = float(p_str) / 100
                    ui_components['bar'].progress(percent)
                    ui_components['status'].markdown(f"🚀 下载中: `{p_str}%` | ⚡ `{d.get('_speed_str')}`")
                except:
                    pass
            elif d['status'] == 'finished':
                ui_components['bar'].progress(1.0)
                ui_components['status'].markdown("✅ 下载完成，正在处理文件...")

        ydl_opts = {
            'outtmpl': f'{task_dir}/%(title)s.%(ext)s',
            'progress_hooks': [progress_hook],
            'restrictfilenames': True,
            'trim_file_name': 50,
            'format': 'bestvideo[vcodec^=avc]+bestaudio[acodec^=mp4a]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'merge_output_format': 'mp4',
            'quiet': True,
            'no_warnings': True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(raw_url, download=False)
                title = info.get('title', 'Unknown')
                ui_components['title'].markdown(f"**🎬 {title}**")
                
                ydl.download([raw_url])
                time.sleep(1) 
                
                files = [f for f in os.listdir(task_dir) if f.endswith('.mp4')]
                if files:
                    file_path = os.path.join(task_dir, files[0])
                    file_size = os.path.getsize(file_path)/1024/1024
                    ui_components['status'].success(f"🎉 完成! ({file_size:.1f} MB)")
                    return file_path
                else:
                    ui_components['status'].error("❌ 未生成文件")
                    return None
        except Exception as e:
            ui_components['status'].error(f"❌ 错误: {str(e)[:50]}...")
            return None

    def render(self):
        st.header("🛡️ Bilibili 稳定版下载器")
        st.caption("已修复 Windows 播放问题 & 提升下载稳定性")

        # 1. 输入区
        with st.container():
            c1, c2 = st.columns([5, 1])
            raw_input = c1.text_input("粘贴链接:", key="dl_url_input", placeholder="支持 Bilibili 链接或分享口令")
            
            def add_to_queue():
                if st.session_state.dl_url_input:
                    clean_url = self.extract_url(st.session_state.dl_url_input)
                    current_urls = [t['url'] for t in st.session_state.queue]
                    if clean_url not in current_urls:
                        st.session_state.queue.append({'url': clean_url})
                        st.toast(f"已添加任务")
                    else:
                        st.toast("任务已存在")
            
            c2.button("➕ 添加", on_click=add_to_queue, use_container_width=True)

        # 2. 队列
        if st.session_state.queue:
            st.divider()
            for i, task in enumerate(st.session_state.queue):
                st.text(f"{i+1}. 🔗 {task['url']}")

            st.divider()

            # 3. 执行区
            if st.button("🚀 开始下载", type="primary", use_container_width=True):
                st.write("---")
                
                ui_holders = []
                for i, task in enumerate(st.session_state.queue):
                    with st.container():
                        c_title = st.empty()
                        c_title.text(f"准备解析任务 {i+1}...")
                        c_bar = st.progress(0)
                        c_status = st.empty()
                        st.divider()
                        ui_holders.append({'title': c_title, 'bar': c_bar, 'status': c_status})
                
                ctx = get_script_run_ctx()
                completed_files = []
                
                with ThreadPoolExecutor(max_workers=self.MAX_CONCURRENT_TASKS) as executor:
                    futures = []
                    for i, task in enumerate(st.session_state.queue):
                        future = executor.submit(self.download_worker, task, ui_holders[i], ctx)
                        futures.append(future)
                    
                    for future in futures:
                        try:
                            res = future.result()
                            if res: completed_files.append(res)
                        except Exception:
                            pass

                if completed_files:
                    zip_name = "bilibili_videos.zip"
                    try:
                        with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zf:
                            for f in completed_files:
                                if f and os.path.exists(f):
                                    zf.write(f, os.path.basename(f))
                        
                        if os.path.exists(zip_name):
                            with open(zip_name, "rb") as f:
                                st.balloons()
                                st.download_button("📦 打包下载所有视频", f, file_name=zip_name)
                    except Exception as e:
                        st.error(f"打包失败: {e}")

# ==========================================
# 3. 评论抓取器模块 (Comment Scraper)
# ==========================================
class CommentScraperApp:
    def __init__(self):
        self._init_session()
        
    class VideoTypeFix:
        value = 1 

    def _init_session(self):
        if 'comments_data' not in st.session_state:
            st.session_state.comments_data = None
        if 'video_title' not in st.session_state:
            st.session_state.video_title = ""
        if 'bv_id' not in st.session_state:
            st.session_state.bv_id = ""

    def extract_bv_robust(self, text):
        if not text: return None, None
        bv_pattern = r"(BV[a-zA-Z0-9]{10})"
        match = re.search(bv_pattern, text)
        if match:
            return match.group(1), "Direct Match"
        
        short_link_pattern = r"(https?://b23\.tv/[a-zA-Z0-9]+)"
        short_match = re.search(short_link_pattern, text)
        if short_match:
            short_url = short_match.group(1)
            try:
                headers = {"User-Agent": "Mozilla/5.0"}
                resp = requests.get(short_url, headers=headers, allow_redirects=True, timeout=10)
                real_url = resp.url
                match_redirect = re.search(bv_pattern, real_url)
                if match_redirect:
                    return match_redirect.group(1), real_url
            except Exception as e:
                print(f"短链接解析失败: {e}")
        return None, None

    def parse_cookie_json(self, json_str):
        try:
            data = json.loads(json_str)
            cookie_list = []
            if isinstance(data, list):
                cookie_list = data
            elif isinstance(data, dict) and "cookies" in data:
                cookie_list = data["cookies"]
            else:
                return None, "JSON 格式不正确"

            cookies = {c['name']: c['value'] for c in cookie_list}
            sessdata = cookies.get('SESSDATA')
            bili_jct = cookies.get('bili_jct')
            buvid3 = cookies.get('buvid3')

            if not sessdata or not bili_jct:
                return None, "缺少 SESSDATA 或 bili_jct"

            sessdata = urllib.parse.unquote(sessdata)
            bili_jct = urllib.parse.unquote(bili_jct)
            cred = Credential(sessdata=sessdata, bili_jct=bili_jct, buvid3=buvid3)
            return cred, None
        except Exception as e:
            return None, f"解析错误: {str(e)}"

    def create_pdf(self, dataframe, title):
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        elements = []
        font_name = 'STSong-Light'
        try:
            pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
        except:
            font_name = "Helvetica"

        styles = getSampleStyleSheet()
        title_style = styles['Title']
        if font_name == 'STSong-Light': title_style.fontName = font_name
        
        cell_style = ParagraphStyle(name='CellStyle', fontName=font_name, fontSize=9, leading=12, wordWrap='CJK')
        safe_title = re.sub(r'[^\w\s\u4e00-\u9fa5]', '', title)
        elements.append(Paragraph(f"视频评论: {safe_title}", title_style))
        elements.append(Paragraph("<br/><br/>", styles['Normal']))

        col_widths = [70, 240, 40, 80, 40] 
        headers = dataframe.columns.to_list()
        processed_data = [headers]

        for index, row in dataframe.iterrows():
            new_row = []
            uname = re.sub(r'[^\x00-\x7F\u4e00-\u9fa5]+', '', str(row['用户名']))
            content = re.sub(r'[^\x00-\x7F\u4e00-\u9fa5]+', '', str(row['内容']))
            new_row.append(Paragraph(uname, cell_style)) 
            new_row.append(Paragraph(content, cell_style))
            new_row.append(str(row['点赞']))
            new_row.append(str(row['时间'])) 
            new_row.append(str(row['回复数']))
            processed_data.append(new_row)

        t = Table(processed_data, colWidths=col_widths)
        style = TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), font_name), 
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ])
        t.setStyle(style)
        elements.append(t)
        try:
            doc.build(elements)
            buffer.seek(0)
            return buffer
        except:
            return None

    async def fetch_one_page(self, oid, page, credential, semaphore):
        async with semaphore:
            try:
                await asyncio.sleep(0.05)
                c = await comment.get_comments(oid, self.VideoTypeFix(), page, credential=credential)
                return c
            except:
                return None

    async def fetch_comments_async(self, bv_id, fetch_mode, limit_pages, credential=None):
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

        try:
            page_1_data = await comment.get_comments(oid, self.VideoTypeFix(), 1, credential=credential)
        except ResponseCodeException as e:
            return None, f"抓取失败: {e.code}"
        
        if not page_1_data: return title, []

        page_info = page_1_data.get('page', {})
        total_count = page_info.get('count', 0)
        total_pages_available = math.ceil(total_count / 20)
        
        if fetch_mode == "全部下载":
            target_pages = total_pages_available
            status_text.text(f"共 {total_count} 条，约 {target_pages} 页，全速下载中...")
        else:
            target_pages = min(total_pages_available, limit_pages)
            status_text.text(f"准备下载前 {target_pages} 页...")

        def process_json(c_json):
            processed = []
            if 'replies' not in c_json or not c_json['replies']: return processed
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

        comments_data.extend(process_json(page_1_data))
        progress_bar.progress(1 / max(target_pages, 1))

        if target_pages > 1:
            sem = asyncio.Semaphore(5)
            tasks = []
            for p in range(2, target_pages + 1):
                tasks.append(self.fetch_one_page(oid, p, credential, sem))
            
            finished_count = 1
            for future in asyncio.as_completed(tasks):
                result = await future
                finished_count += 1
                if result:
                    comments_data.extend(process_json(result))
                progress_bar.progress(min(finished_count / target_pages, 1.0))
                status_text.text(f"⚡ 并发下载中: {finished_count}/{target_pages} 页")

        status_text.text("✅ 下载完成！")
        return title, comments_data

    def render(self):
        st.header("⚡ B站评论抓取 (终极版)")

        # 侧边栏配置 (仅在评论抓取页面显示)
        with st.sidebar:
            st.divider()
            st.subheader("📝 抓取设置")
            cookie_input = st.text_area("Cookie JSON (可选):", height=100, placeholder='{"cookies": [...]}')
            cred = None
            if cookie_input:
                cred, err_msg = self.parse_cookie_json(cookie_input)
                if cred: st.success("✅ Cookie 有效")
                else: st.error(f"❌ {err_msg}")
            
            fetch_mode = st.radio("模式", ("指定页数", "全部下载"))
            limit_pages = 5
            if fetch_mode == "指定页数":
                limit_pages = st.slider("页数", 1, 100, 5)

        # 主界面输入
        url_input = st.text_input("👇 视频链接", placeholder="支持各种乱码格式、短链接、中文标题混排")

        if st.button("开始抓取", type="primary"):
            if not url_input:
                st.warning("请粘贴内容")
            else:
                with st.spinner("正在解析..."):
                    bv_id, _ = self.extract_bv_robust(url_input)
                    if not bv_id:
                        st.error("无法识别 BV 号")
                    else:
                        st.success(f"识别成功: {bv_id}")
                        try:
                            loop = asyncio.get_event_loop()
                        except RuntimeError:
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                        
                        title, data = loop.run_until_complete(self.fetch_comments_async(bv_id, fetch_mode, limit_pages, credential=cred))
                        
                        if isinstance(data, str):
                            st.error(data)
                        elif data:
                            st.session_state.comments_data = data
                            st.session_state.video_title = title
                            st.session_state.bv_id = bv_id
                            st.rerun()
                        else:
                            st.warning("未抓取到数据")

        # 结果显示
        if st.session_state.comments_data:
            st.divider()
            title = st.session_state.video_title
            data = st.session_state.comments_data
            st.subheader(f"📄 {title}")
            df = pd.DataFrame(data)
            
            col1, col2 = st.columns([3, 1])
            with col2:
                st.markdown("### 🛠️ 导出")
                st.write(f"共 {len(df)} 条")
                csv = df.to_csv(index=False).encode('utf-8-sig')
                st.download_button("📥 下载 CSV", csv, f"{st.session_state.bv_id}.csv", "text/csv")
                
                if st.button("生成 PDF"):
                    with st.spinner("生成中..."):
                        pdf_buffer = self.create_pdf(df, title)
                        if pdf_buffer:
                            st.download_button("📥 下载 PDF", pdf_buffer, f"{st.session_state.bv_id}.pdf", "application/pdf")
                        else:
                            st.error("PDF生成失败")
                            
            with col1:
                st.dataframe(df, use_container_width=True, height=500)
            
            if st.button("🔄 清空结果"):
                st.session_state.comments_data = None
                st.rerun()

# ==========================================
# 4. 主程序入口 & 导航
# ==========================================

# 侧边栏导航
st.sidebar.title("🧰 Bilibili 工具箱")
app_mode = st.sidebar.radio(
    "选择功能模块:",
    ["📺 视频下载器", "📝 评论抓取器"],
    captions=["基于 yt-dlp 稳定下载", "基于 bilibili-api 抓取评论"]
)

# 路由分发
if app_mode == "📺 视频下载器":
    downloader = VideoDownloaderApp()
    downloader.render()
elif app_mode == "📝 评论抓取器":
    scraper = CommentScraperApp()
    scraper.render()

# 页脚
st.sidebar.divider()
st.sidebar.caption("Provided by Gemini")
