# video-to-tab：从吉他演奏视频中提取并拼接 Tab 谱

## Context
吉他演奏视频的下方通常叠加着当前段落的 tab 谱，谱面**整页/整行切换**，并可能带有移动的播放光标或高亮。用户希望有一个**本地 Web 应用**：输入本地视频（mp4/mkv/webm/mov/flv 等）或 B站/YouTube 链接，自动定位谱面区域（允许手动微调），识别每一页不同的谱面，去掉光标等干扰后按顺序拼接成**完整的长图 / PDF**。本期不做符号识别（OCR 成 ASCII/GP）。

项目目录 `/home/akaba/workspace/video-to-tab` 目前为空，也还不是 git 仓库。环境：Python 3.12、Node 24、NVIDIA GPU（WSL2）；尚未安装 ffmpeg 和 yt-dlp。

## 已确认的决策
- 形态：本地 Web 应用，FastAPI 后端 + Vite/Vue 3 前端
- 输出：拼接后的 PNG 长图 + PDF
- 滚动模式：整页切换
- 区域定位：自动检测 + 手动微调
- 核心算法：方案 A（帧差分段 + 时间中值去光标 + pHash/SSIM 去重）

## 架构
```
video-to-tab/
  backend/
    app/
      main.py            # FastAPI 入口、路由、静态文件
      jobs.py            # 内存中的任务表 + 后台线程执行 + 进度
      source.py          # 输入获取：上传文件落盘 / yt-dlp 下载 URL
      frames.py          # PyAV 解码 + 按 fps 采样（在 ROI 内裁剪）
      region.py          # 自动检测谱面 ROI
      segment.py         # 稳定段切分（换页检测）
      compose.py         # 段内时间中值 → 干净页面；pHash/SSIM 去重
      export.py          # 拼接长图 + img2pdf 生成 PDF
    tests/               # pytest，使用合成视频夹具
    pyproject.toml       # 依赖：fastapi uvicorn opencv-python-headless av yt-dlp imagehash scikit-image img2pdf pillow numpy
  frontend/              # Vite + Vue 3
    src/views/            Input.vue  RegionEditor.vue  Review.vue
  data/jobs/<job_id>/    # 源视频、采样帧、页面 PNG、导出结果
```
每个模块只负责一件事，模块之间传递 numpy 数组或文件路径，可以单独测试。

## 处理流程
1. **获取视频（source.py）**
   - 上传文件：直接保存。
   - URL：调用 `yt_dlp` 的 Python API，只下载视频流，选 ≤1080p（谱面清晰即可，不需要音频）。
   - B站需要支持 `BV` 号、`b23.tv` 短链和分 P，必要时允许用户提供 cookies 文件路径。
   - 统一用 PyAV 解码；PyAV 自带 ffmpeg 库，所以视频格式的支持面很广。系统级 ffmpeg 只在 yt-dlp 合并流时需要，安装说明写进 README。
2. **自动定位区域（region.py）**
   - 均匀抽约 20 帧，用 Canny 边缘 + 水平 Hough 直线检测"6 条（或 4 条贝斯谱线）等间距的长水平线组"，同时利用谱面区域亮度高、方差低的背景特征。
   - 候选矩形取跨帧的中位数，返回 `bbox + 置信度`。检测失败时默认取画面下 1/3。
3. **手动微调（前端 RegionEditor）**：在代表帧上显示检测框，可以拖拽调整；确认后提交 ROI。
4. **采样（frames.py）**：默认 5 fps，只保留 ROI 内的灰度图，降低内存占用。
5. **换页检测（segment.py）**
   - 对二值化后的相邻帧计算"变化像素占比"。光标只引起局部、窄条状的变化（占比低，或者变化集中在少数几列），换页则是大面积变化。
   - 用阈值加最短持续时间（例如 ≥0.8s）切出稳定段，并忽略过渡动画中的帧（淡入淡出期间差异连续偏高的帧）。
   - 另外过滤没有谱面的段，例如片头片尾，用"谱线检测失败"作为判断依据。
6. **生成干净页面（compose.py）**
   - 对每个稳定段内的帧逐像素取时间中值（使用原彩色 ROI 帧），得到去掉光标和高亮的页面。
   - 段太短（帧数 <3）时，改取与段内中值最接近的单帧。
7. **去重（compose.py）**
   - 相邻页面先比 pHash 汉明距离，接近时再用 SSIM 复核，确认相同就合并。
   - 非相邻的重复页（比如副歌重现）**保留**，因为那本来就是乐谱的一部分，只在界面上标注"与第 N 页相同"。
8. **人工校对（前端 Review）**：按页显示缩略图和时间戳，可以删除、合并、拖动排序、点击跳转查看原帧。
9. **导出（export.py）**：纵向拼接成 PNG 长图（页与页之间留白），同时用 img2pdf 按 A4 宽度自动分页生成 PDF。

## API
- `POST /api/jobs`：接收文件上传或 `{url}`，返回 `job_id`，并开始下载/预处理
- `GET  /api/jobs/{id}`：返回状态、进度、阶段
- `GET  /api/jobs/{id}/region`：返回代表帧和自动检测框；`PUT` 提交 ROI 后开始分析
- `GET  /api/jobs/{id}/pages`：返回页面列表；`PUT` 提交校对后的页面顺序和删除项
- `POST /api/jobs/{id}/export?fmt=png|pdf`：导出，返回下载地址

任务在后台线程中执行，状态保存在内存里并写入 `data/jobs/<id>/state.json`，前端轮询进度。这是单用户本地应用，不引入队列或数据库。

## 错误处理
- URL 下载失败时（地区限制、需要登录、链接无效），把 yt-dlp 的错误信息原样显示在界面上，并提示可以改用 cookies 或直接上传文件。
- 视频无法解码时提示不支持的格式。
- 区域自动检测置信度低时，界面上给出醒目提示，要求用户手动框选。
- 一个稳定段都没找到时，提示用户检查 ROI 或降低阈值（高级参数：采样 fps、变化阈值、最短段时长）。

## 测试与验证
- **单元测试（pytest）**：用 OpenCV 合成测试视频，内容包括上半部分的随机噪声"演奏画面"、下半部分的 3 页不同 tab 图、一条移动的竖直光标、页间淡入淡出、一页重复出现。断言：
  - region 检测框与真实框的 IoU > 0.9
  - 切出 3 个（或 4 个，含重复页）稳定段，边界误差 < 0.5s
  - 中值合成后的页面与原始 tab 图的 SSIM > 0.95（证明光标被去掉）
  - 相邻重复页被合并，非相邻重复页被保留
- **端到端**：启动 `uvicorn` 和 `vite dev`，分别用一个本地 mp4、一个 YouTube 链接和一个 B站链接跑完整流程，人工检查导出的 PNG/PDF。
- `ruff` 做静态检查，`vitest` 做少量前端组件测试（ROI 编辑器的坐标换算）。

## 实施顺序
1. 初始化 git、项目骨架和依赖；README 写明需要安装系统 ffmpeg
2. 合成测试视频夹具
3. frames → segment → compose → export（核心流水线，TDD），外加一个 CLI 入口 `python -m app.cli video.mp4 --roi x,y,w,h`，便于调试
4. region 自动检测
5. source（上传 + yt-dlp）
6. FastAPI 任务与 API
7. Vue 前端：Input → RegionEditor → Review → 导出
8. 用真实视频做端到端调参

## 暂不包含（YAGNI）
符号级 OCR 与 ASCII/GP 导出、横向连续滚动模式、多用户和公网部署、GPU 加速（CPU 上的 OpenCV 已经够用）。
