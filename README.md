# video-to-tab

把吉他演奏视频下方逐页切换的 tab 谱提取出来，去掉播放光标，拼接成完整的长图 / PDF。

## 安装

需要 Python 3.12+、[uv](https://docs.astral.sh/uv/)、Node 20+。

    cd backend && uv sync
    cd ../frontend && npm install && npm run build

不需要系统 ffmpeg：PyAV 自带解码库，yt-dlp 只下载无需合并的视频流。

## 使用

    cd backend && uv run uvicorn app.main:app --port 8000

浏览器打开 http://127.0.0.1:8000 ：上传视频或粘贴 bilibili / YouTube 链接 → 确认谱面区域 → 校对页面 → 导出 PNG / PDF。
- 分段横向滚动的谱面（相邻页有重叠）会自动拼接去重，并按小节重新排成行；整页切换的谱面保持原样。

- B 站需要登录或受地区限制时：导出浏览器 cookies（Netscape 格式）并设置 `VTT_COOKIES_FILE=/path/cookies.txt` 后启动。
- 数据目录默认 `data/jobs/`，可用 `VTT_DATA_DIR` 修改。
- 高级参数（识别页面里的“高级参数”）：采样 fps、换页阈值（默认 0.15，漏检换页时调低）、最短页时长。

## 开发

    cd backend && uv run pytest            # 单元 + API 测试（-m network 运行联网下载测试）
    cd backend && uv run python -m app.cli video.mp4 --out out/   # 命令行调试
    cd backend && uv run uvicorn app.main:app --reload --port 8000
    cd frontend && npm run dev             # http://localhost:5173，/api 代理到 8000
    cd frontend && npm test
