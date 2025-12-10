import streamlit as st
import asyncio
import pandas as pd
import re
import time
import requests
import json
import urllib.parse
from bilibili_api import video, comment, Credential
from bilibili_api.exceptions import ResponseCodeException

# --- 页面配置 ---
st.set_page_config(page_title="B站评论抓取神器 ", page_icon="🍪", layout="wide")

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
                    '点赞': r['like'],
                    '时间': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(r['ctime'])),
                    '回复数': r['count']
                }
                comments_data.append(item)
                
                if r.get('replies'):
                    for sub in r['replies']:
                        sub_item = {
                            '用户名': sub['member']['uname'],
                            '内容': f"[回复] {sub['content']['message']}",
                            '点赞': sub['like'],
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

st.title("🍪 B站评论抓取 (强力修复版)")

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
                st.subheader(f"📄 {title}")
                df = pd.DataFrame(data)
                st.dataframe(df, use_container_width=True)
                
                csv = df.to_csv(index=False).encode('utf-8-sig')
                st.download_button("📥 下载数据 (CSV)", csv, f"{bv_id}.csv", "text/csv")
            else:
                st.warning("未抓取到数据。")
