import streamlit as st
import asyncio
import pandas as pd
import re
import time
import requests
from bilibili_api import video, comment
from bilibili_api.exception import ResponseCodeException

# --- 页面配置 ---
st.set_page_config(page_title="B站评论抓取神器", page_icon="📝", layout="centered")

# --- 核心逻辑函数 ---

def get_real_url(url):
    """
    处理 b23.tv 短链接，获取真实重定向后的 URL
    """
    if "b23.tv" in url:
        try:
            # 模拟浏览器请求，允许重定向
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            resp = requests.get(url, headers=headers, allow_redirects=True, timeout=10)
            return resp.url
        except Exception as e:
            st.error(f"短链接解析失败: {e}")
            return url
    return url

def extract_bv(url):
    """
    从任意字符串中提取 BV 号
    """
    # 1. 先尝试解析短链
    real_url = get_real_url(url)
    
    # 2. 正则提取 BV 号 (忽略问号后面的参数)
    pattern = r"(BV[a-zA-Z0-9]{10})"
    match = re.search(pattern, real_url)
    
    if match:
        return match.group(1), real_url
    return None, real_url

async def fetch_comments_async(bv_id, limit_pages=5):
    """
    异步获取评论数据
    """
    # 初始化
    v = video.Video(bvid=bv_id)
    
    try:
        # 获取视频基础信息 (为了拿到 oid/aid)
        info = await v.get_info()
        oid = info['aid']
        title = info['title']
    except Exception as e:
        return None, f"无法获取视频信息，请检查BV号是否有效。错误: {e}"

    comments_data = []
    page = 1
    
    # UI 进度条
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    try:
        while page <= limit_pages:
            status_text.text(f"🚀 正在抓取第 {page}/{limit_pages} 页...")
            
            try:
                # 获取评论 (type_=1 代表视频)
                c = await comment.get_comments(oid, comment.ResourceType.VIDEO, page)
            except ResponseCodeException as e:
                # 某些视频评论区关闭或需要登录
                if e.code == -404: 
                    break 
                else:
                    raise e

            # 检查是否有评论内容
            if 'replies' not in c or not c['replies']:
                status_text.text("✅ 已到达评论区底部。")
                break
            
            for r in c['replies']:
                # 解析主评论
                item = {
                    '类型': '主评论',
                    '用户名': r['member']['uname'],
                    '内容': r['content']['message'],
                    '点赞': r['like'],
                    '时间': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(r['ctime'])),
                    '楼层': r.get('floor', 0)
                }
                comments_data.append(item)
                
                # 解析楼中楼 (B站API通常只返回前几条热评回复)
                if r.get('replies'):
                    for sub in r['replies']:
                        sub_item = {
                            '类型': '└─ 回复',
                            '用户名': sub['member']['uname'],
                            '内容': sub['content']['message'],
                            '点赞': sub['like'],
                            '时间': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(sub['ctime'])),
                            '楼层': sub.get('floor', 0)
                        }
                        comments_data.append(sub_item)

            # 更新进度
            progress_bar.progress(min(page / limit_pages, 1.0))
            page += 1
            
            # 休眠防止触发风控 (重要！)
            await asyncio.sleep(0.8)
            
    except Exception as e:
        st.warning(f"抓取过程中止: {str(e)}")
    
    progress_bar.progress(100)
    status_text.text("🎉 抓取完成！")
    
    return title, comments_data

# --- Streamlit UI 界面 ---

st.title("📺 Bilibili 评论区一键导出")
st.markdown("""
利用开源库 `bilibili-api-python` 制作。
支持格式：
- **标准链接**: `https://www.bilibili.com/video/BV15RW2zvENr/...`
- **短链接**: `https://b23.tv/YTfd2CY`
""")

with st.sidebar:
    st.header("⚙️ 参数设置")
    max_pages = st.number_input("抓取页数 (每页约20条主评)", min_value=1, max_value=100, value=5)
    st.info("提示：不登录状态下，B站API通常限制查看前几页或热门评论。")

# 输入框
url_input = st.text_input("👇 请粘贴视频链接", placeholder="https://b23.tv/...")

if st.button("开始抓取", type="primary"):
    if not url_input:
        st.error("请先输入链接！")
    else:
        # 1. 解析链接
        with st.spinner("正在解析链接..."):
            bv_id, real_url = extract_bv(url_input)
        
        if not bv_id:
            st.error("❌ 未能识别出 BV 号，请检查链接是否正确。")
        else:
            st.success(f"✅ 识别成功: {bv_id}")
            st.caption(f"解析后地址: {real_url}")
            
            # 2. 运行异步抓取
            # 在 Streamlit 中运行 asyncio 需要新建循环或使用 asyncio.run
            try:
                title, data = asyncio.run(fetch_comments_async(bv_id, max_pages))
                
                if isinstance(data, str): # 如果返回的是错误信息
                    st.error(data)
                elif data:
                    # 3. 展示结果
                    st.divider()
                    st.subheader(f"📄 视频标题：{title}")
                    
                    df = pd.DataFrame(data)
                    st.dataframe(df, use_container_width=True, height=400)
                    
                    st.success(f"共抓取 {len(df)} 条评论")
                    
                    # 4. 下载按钮
                    csv = df.to_csv(index=False).encode('utf-8-sig')
                    st.download_button(
                        label="📥 下载 CSV 表格",
                        data=csv,
                        file_name=f"B站评论_{bv_id}.csv",
                        mime="text/csv"
                    )
                else:
                    st.warning("结果为空，可能是视频没有评论或API访问受限。")
                    
            except Exception as e:
                st.error(f"运行时发生错误: {e}")
