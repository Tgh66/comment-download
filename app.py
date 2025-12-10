import streamlit as st
import asyncio
import pandas as pd
import re
import time
from bilibili_api import video, comment, sync
from bilibili_api.user import User

# 设置页面配置
st.set_page_config(page_title="Bilibili 评论采集器", page_icon="📺")

# --- 辅助函数 ---

def extract_bv(url):
    """从链接或字符串中提取BV号"""
    pattern = r"(BV[a-zA-Z0-9]{10})"
    match = re.search(pattern, url)
    if match:
        return match.group(1)
    return None

async def fetch_comments_async(bv_id, limit_pages=5):
    """
    异步获取评论核心逻辑
    :param bv_id: 视频BV号
    :param limit_pages: 限制抓取的页数（防止请求过多被封IP）
    """
    # 1. 初始化视频对象
    v = video.Video(bvid=bv_id)
    
    # 2. 获取视频基础信息（我们需要 oid/aid 来获取评论）
    info = await v.get_info()
    oid = info['aid']
    title = info['title']
    
    comments_data = []
    page = 1
    
    # 创建一个进度条占位符
    progress_text = st.empty()
    progress_bar = st.progress(0)
    
    # 3. 循环获取评论（默认按热度/时间排序，这里API通常返回混合排序）
    # 注意：B站API普通接口很难一次性拿到几万条，通常只能拿几十页
    try:
        while page <= limit_pages:
            progress_text.text(f"正在抓取第 {page} 页评论...")
            
            # 获取评论页
            # type_=1 代表视频评论
            c = await comment.get_comments(oid, comment.ResourceType.VIDEO, page)
            
            if 'replies' not in c or not c['replies']:
                break # 没有更多评论了
            
            for r in c['replies']:
                # 提取核心数据
                item = {
                    '用户名': r['member']['uname'],
                    '性别': r['member']['sex'],
                    '等级': r['member']['level_info']['current_level'],
                    '内容': r['content']['message'],
                    '点赞数': r['like'],
                    '发布时间': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(r['ctime'])),
                    '回复数': r['count'],
                    'rpid': r['rpid_str'] # 评论ID
                }
                comments_data.append(item)
                
                # 如果有二级回复（楼中楼），API通常只返回前几条
                # 若要抓取所有楼中楼，需要对每个rpid再发请求，这里为了速度仅抓取预览的
                if r.get('replies'):
                    for sub in r['replies']:
                         sub_item = {
                            '用户名': sub['member']['uname'],
                            '性别': sub['member']['sex'],
                            '等级': sub['member']['level_info']['current_level'],
                            '内容': f"[楼中楼] {sub['content']['message']}",
                            '点赞数': sub['like'],
                            '发布时间': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(sub['ctime'])),
                            '回复数': 0,
                            'rpid': sub['rpid_str']
                        }
                         comments_data.append(sub_item)

            # 更新进度
            progress_bar.progress(min(page / limit_pages, 1.0))
            
            # 翻页控制
            page += 1
            # 重要：休眠一下，尊重B站服务器，防止被封W_rid
            await asyncio.sleep(1.0)
            
    except Exception as e:
        st.error(f"抓取中断或完成: {str(e)}")
    
    progress_text.text(f"抓取完成！共获取 {len(comments_data)} 条数据。")
    return title, comments_data

# --- Streamlit UI ---

st.title("📺 Bilibili 视频评论采集器")
st.caption("基于开源库 `bilibili-api-python` | 仅供学习研究使用")

# 侧边栏配置
with st.sidebar:
    st.header("⚙️ 设置")
    max_pages = st.slider("最大抓取页数 (每页约20条主评)", 1, 50, 5)
    st.info("⚠️ 注意：B站接口有严格的反爬限制。不登录情况下，抓取页数过多可能会导致IP暂时被禁。建议小批量测试。")

# 主输入区
url_input = st.text_input("请输入B站视频链接 (例如: https://www.bilibili.com/video/BV1xxxx...)", "")

if st.button("开始抓取评论", type="primary"):
    if not url_input:
        st.warning("请先输入视频链接！")
    else:
        bv_id = extract_bv(url_input)
        if not bv_id:
            st.error("无法识别 BV 号，请检查链接格式。")
        else:
            st.success(f"已识别 BV 号: {bv_id}，开始连接 Bilibili API...")
            
            # 在 Streamlit 中运行异步代码
            try:
                # 创建新的事件循环来运行异步任务
                title, data = asyncio.run(fetch_comments_async(bv_id, max_pages))
                
                if data:
                    st.divider()
                    st.subheader(f"📄 视频：{title}")
                    
                    # 转换为 DataFrame
                    df = pd.DataFrame(data)
                    
                    # 数据展示
                    st.dataframe(df, use_container_width=True)
                    
                    # CSV 下载
                    csv = df.to_csv(index=False).encode('utf-8-sig')
                    st.download_button(
                        label="📥 下载评论数据 (CSV)",
                        data=csv,
                        file_name=f"bilibili_comments_{bv_id}.csv",
                        mime="text/csv"
                    )
                    
                    # 简单的简单数据分析
                    st.divider()
                    st.write("📊 **快速分析**")
                    col1, col2 = st.columns(2)
                    with col1:
                        st.metric("评论总数 (本次抓取)", len(df))
                    with col2:
                        avg_level = df['等级'].astype(int).mean()
                        st.metric("平均用户等级", f"Lv {avg_level:.1f}")
                        
                else:
                    st.warning("未获取到评论，可能是视频无评论或触发了风控。")
                    
            except Exception as e:
                st.error(f"发生错误: {e}")
