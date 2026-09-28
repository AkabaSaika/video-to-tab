# video-to-tab

把吉他演奏视频下方逐页切换的 tab 谱提取出来，去掉播放光标，拼接成完整的长图 / PDF。

## 下载可直接运行版

在 [Releases](https://github.com/AkabaSaika/video-to-tab/releases) 下载对应系统的 zip，解压后运行 `video-to-tab`（Windows 为 `video-to-tab.exe`），会自动打开浏览器，无需安装任何依赖。

## 从源码安装

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

## 打包

    cd frontend && npm ci && npm run build
    cd ../backend && uv sync --group build && uv run --group build python ../packaging/build.py v0.01

生成 `build-release/video-to-tab-<版本>-<系统>.zip`。推送 `v*` 标签后，GitHub Actions（`.github/workflows/release.yml`）会在 Windows / macOS / Linux 上分别打包并发布到 Releases。

## 识谱（实验中）

把截图拼接得到的 tab 行图识别成结构化乐谱（弦、品格、休止、时值），并可以用 Guitar Pro 文件评测准确率：

    cd backend
    uv run python -m app.omr.evaluate VIDEO_OR_PAGE_DIR 谱.gp --track "声部名" [--from 13 --to 148]
    uv run python -m app.omr.train --per-class 2000   # 重新训练字形分类器（约 3 分钟）

识别结果是 `app.omr.model.Score`（可转为 JSON），后续用于识谱界面和导出 .gp。
