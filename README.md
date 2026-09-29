# video-to-tab

把吉他演奏视频下方逐页切换的 tab 谱提取出来，去掉播放光标，拼接成完整的长图 / PDF。
也可以识别钢琴演奏视频里的五线谱（大谱表），导出 MusicXML（见“钢琴谱”）；以及鼓演奏视频里的鼓谱，导出 MusicXML 和 MIDI（见“鼓谱”）。

## 下载可直接运行版

在 [Releases](https://github.com/AkabaSaika/video-to-tab/releases) 下载对应系统的 zip，解压后运行 `video-to-tab`（Windows 为 `video-to-tab.exe`），会自动打开浏览器，无需安装任何依赖。

## 从源码安装

需要 Python 3.12+、[uv](https://docs.astral.sh/uv/)、Node 20+。

    cd backend && uv sync
    uv run python -m app.piano.engine --download   # 钢琴谱识别模型（约 160 MB，只需一次）
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

生成 `build-release/video-to-tab-<版本>-<系统>.zip`。打包时会把钢琴谱识别模型一起放进去（缺少时先自动下载），发布版离线可用。推送 `v*` 标签后，GitHub Actions（`.github/workflows/release.yml`）会在 Windows / macOS / Linux 上分别打包并发布到 Releases。

## 识谱（实验中）

把截图拼接得到的 tab 行图识别成结构化乐谱（弦、品格、休止、时值），并可以用 Guitar Pro 文件评测准确率：

    cd backend
    uv run python -m app.omr.evaluate VIDEO_OR_PAGE_DIR 谱.gp --track "声部名" [--from 13 --to 148]
    uv run python -m app.omr.train --per-class 2000   # 重新训练字形分类器（约 3 分钟）

识别结果是 `app.omr.model.Score`（可转为 JSON），后续用于识谱界面和导出 .gp。

## 识谱与导出 .gp

在校对页点“识谱”，识别完成后进入识谱页：

- 顶部可设置标题、速度（识别不读速度，默认 120）和定弦（按弦数给预设，也可自定义音名）。
- 橙色块是需要检查的拍；“下一个待检查”逐个跳转。点击任意一拍打开编辑面板：对照原图片段修改各弦品格（留空 = 无音，x = 死音）、时值、附点、三连音、休止，前后插入或删除拍，“确认无误”清除标记。
- 修改自动保存；刷新页面或重启程序后，可在首页“最近的任务”中继续。
- 小节编号与原谱一致：视频未出现的开头小节补为休止；中间漏识别的小节补为休止并标为待检查。
- 演奏技巧会一并识别并导出：推弦（½ / 全音 / 1½，推放）、滑音（连滑 sl.、移滑、滑入、滑出）、击勾弦（H / P 或连线）、泛音（<12> 自然泛音、品格后的 <n> 人工泛音）、颤音（波浪线）、顿音（拍上方的点）、闷音（P.M. 及其虚线范围）。编辑面板中点某根弦的品格框后可修改该弦的推弦 / 滑音 / 击勾弦 / 泛音 / 颤音；顿音、闷音按整拍切换。
- “导出 .gp”生成 Guitar Pro 7/8 文件。

## 钢琴谱

页面顶部切换到“钢琴谱”（网址 `#/piano`），上传钢琴演奏视频或粘贴链接：

- 程序按约 5 帧/秒扫描视频，截取每一组完整的大谱表（高音谱表 + 低音谱表，由小节线相连）。连续滚动和整页翻页的谱面都可以；被画面边缘截断的谱表不会被截取，同一组谱表只保留最清晰的一张，按出现顺序排列。
- 每组谱表用 [homr](https://github.com/liebharc/homr) 识别为 MusicXML，结果页左边是视频截图，右边是用 [Verovio](https://www.verovio.org)（LGPL）画出的识别结果，可逐组“删除”或“重新识别”（换一种缩放再读一次）。
- “导出 MusicXML”把各组按顺序合并为一首曲子（一个钢琴声部、两行谱表，小节连续编号，谱号/调号/拍号不重复），可在 MuseScore 等软件中打开继续编辑。逐音符编辑不在本程序内。
- 数据保存在 `data/piano/`（`VTT_PIANO_DATA_DIR` 可修改）。每个识别进程约占 1 GB 内存；识别一组约 2 秒（CPU）。

识别模型（3 个 ONNX 文件，约 160 MB）的位置：环境变量 `VTT_HOMR_MODELS`；未设置时，发布版用程序自带的 `homr_models/`，源码运行用 `data/models/homr/`。缺少模型时第一次识别会从 homr 的 GitHub Releases 下载一次，也可以提前运行 `uv run python -m app.piano.engine --download`。没有模型时，相关测试会自动跳过。

依赖说明：homr 声明需要 OpenCV < 5，但实测在本项目使用的 OpenCV 5 上正常工作，`backend/pyproject.toml` 用 uv 的 `override-dependencies` 放开了这一限制；homr 只用于识别标题的 `rapidocr` 会额外安装带界面的 OpenCV，已排除，程序里用空实现代替（不识别标题）。

## 鼓谱

页面顶部切换到“鼓谱”（网址 `#/drums`），上传鼓演奏视频或粘贴链接：

- 先裁出画面中的谱面区域（明亮的面板，排除上方的摄像画面），再判断谱面形式：
  - 只有一行谱表：Guitar Pro 风格的横向分段滚动条带。程序跟随黄色的小节高亮，每个被演奏的小节只取一次（即使节奏型重复、画面在小节中间滚动），按小节线切下后重新排成与画面同宽的页。没有高亮时，按小节线取整小节并去掉与上一屏重复的部分。
  - 多行谱表（翻页或纵向滚动）：逐行跟踪，每一行只保留最清晰的一张，按出现顺序排列。
- 识别用程序自带的经典图像方法（不需要模型）：找谱线、× 形 / 圈 × / 实心 / 空心符头、符干方向（分声部）、符尾和横梁、附点、休止符（沿用吉他 tab 的字形分类器）、开镲的“o”、鬼音括号、重音，再按拍号求出每个小节的时值。Guitar Pro 的单声部写法（第二声部、甚至两个声部都不写休止符）按横向位置对齐求起点。拍号读取谱号后的数字，读不到时按 4/4。
- 结果页每页一行：左边是视频截图，右边是 Verovio 画出的识别结果，可“删除”或“重新识别”。
- “乐器对应”：识别结果只记录位置和符头形状，导出时再按对应表换算成鼓件（通用约定、Guitar Pro、MuseScore 三个预设，也可以逐个位置修改），修改后立即重新生成预览和导出文件，不需要重新识别。
- 可以修改拍号（按新拍号重新识别每一页）和速度（只影响导出）。
- “导出 MusicXML”（unpitched 音符、打击乐谱号、每种鼓件一个乐器定义）和“导出 MIDI”（自写的 SMF type 1，GM 第 10 通道，重音 / 鬼音影响力度）。逐音符编辑请在 MuseScore 等软件中进行。
- 数据保存在 `data/drums/`（`VTT_DRUMS_DATA_DIR` 可修改）。识别一页约 0.2 秒。
- 测试数据：`backend/tests/make_drum_fixture.py` 用 Verovio 和 LilyPond 生成 `backend/tests/data/drums`（8 段有标准答案的鼓谱、4 种渲染），需要单独装有 verovio、cairosvg、pillow 的环境。

## 许可证

本项目以 [GNU AGPL-3.0](LICENSE) 发布：钢琴谱识别使用的 homr 采用 AGPL-3.0，因此整个项目随之采用 AGPL-3.0。修改后通过网络向他人提供服务时，也需要提供对应的源代码。前端使用的 Verovio 为 LGPL-3.0，alphaTab 为 MPL-2.0。
