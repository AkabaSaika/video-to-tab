# 识谱界面与 .gp 导出（子项目 2）

## Context
子项目 1 已经把识谱引擎合并进来了：`backend/app/omr/`，用 `recognize_images(images) -> Score`。在首个样本上的准确率是品格 99.9%、时值 99.9%（样本内成绩）。

但识别不可能对所有谱面都 100% 准确。用户的目标是：拿到一份能在 Guitar Pro 里直接打开的 `.gp` 文件，内容和视频里的谱一致。所以本子项目要做三件事：
1. 在界面上把识别结果渲染出来，和原图对照；
2. 标出低置信度的位置，方便逐拍修正；
3. 导出 `.gp`。

### 需求理解（已与用户确认）
- 入口放在现有"校对页面"之后：用户调好页面顺序、删掉多余页后，点"识谱"。
- 修正方式是逐拍编辑面板，不是完整的制谱软件。
- 修改自动保存到后端；刷新页面或重启程序后能继续编辑。
- 导出 Guitar Pro 7/8 的 `.gp`。
- 功能要进入打包发布版。

### 成功标准
- 用首个样本（bilibili `BV1yBcEeXEVn`，Mutsumi 声部）走完整流程。导出的 `.gp` 用 `app.omr.evaluate` 的对比逻辑与标准答案比较，指标与识别引擎自身一致，即导出过程无损。
- 导出的文件能在 Guitar Pro 8 中打开。
- 低置信度的拍会被标出，每处修正几次点击就能完成。

## 已确认的决策
- **架构（方案 A）：**
  - 后端只负责识别和保存 Score JSON；
  - 前端用纯函数把 JSON 转成 alphaTex，交给 alphaTab 渲染；
  - 编辑直接修改 JSON 后重新渲染；
  - 在浏览器里用 alphaTab 的 `Gp7Exporter` 导出 `.gp`。
- **可行性已用探针验证**（alphaTab 1.8.4，在 Node 中运行）：alphaTex 导入后导出 `.gp`，再用 `app.omr.gpif.read_track` 读回。以下内容全部保留：7 弦 Drop A 定弦（`\tuning (E4 B3 G3 D3 A2 E2 A1)`）、速度、双音、闷音 `x`、休止 `r`、附点 `{d}`、三连音 `{tu 3}`。
- **弦号换算：** alphaTex 中 1 = 最高音弦，而 Score 中 0 = 最低音弦，所以 `tex_string = strings − string`。

## 设计

### 使用流程
1. 在校对页点"识谱"。前端提交页面顺序，后端在后台识别，前端显示进度条。
2. 识别完成后进入识谱页：
   - **顶部设置：** 标题；速度（默认 120，识别不读速度标记）；定弦（按弦数给预设，6 弦为 E 标准 / Drop D / 降半音，7 弦为 B 标准 / Drop A，也可以自定义音名，如 `E4 B3 G3 D3 A2 E2`）。
   - **谱面：** alphaTab 渲染整份 tab。低置信度的拍用半透明色块覆盖标出，判定条件为拍置信度 < 0.7、任一音符置信度 < 0.7，或所在小节置信度 < 1。"下一个待检查"按钮按顺序跳到下一个被标出的拍，并选中它。
   - **编辑面板：** 点击某一拍后打开，显示：
     - 该小节的原图片段；
     - 各弦品格输入框：留空表示没有音，填 `x` 表示闷音，品格范围 0–30；
     - 时值（1/2/4/8/16/32）、附点、三连音、休止；
     - "前插一拍""后插一拍""删除此拍""确认无误"（把这一拍和其中音符的置信度设为 1）；
     - 小节时值检查：没填满或超出拍号时显示提示。
3. 每次修改后防抖约 1 秒，自动 `PUT` 到后端。
4. "导出 .gp"在浏览器中生成文件并下载，文件名为 `<标题>.gp`，标题为空时用 `tab.gp`。

### 后端
- **Score 模型：**
  - `Score` 新增字段 `title: str = ""`；
  - `Score.from_dict` 做结构校验，缺字段用默认值，类型错误抛出 `ValueError`。
- **任务：**
  - 新增状态 `recognizing` 和 `ready_for_score`；
  - `Job` 新增 `stage` 取值 `recognize`；
  - 识别结果存为任务目录里的 `score.json`。
- **接口：**
  - `POST /api/jobs/{id}/recognize`：请求体 `{order: [page ids]}`。允许从 `ready_for_review`、`ready_for_score`、`failed` 进入，用 `JobStore.transition` 原子切换到 `recognizing`。后台按顺序读取页面图片，调用 `recognize_images`，写入 `score.json`，再切换到 `ready_for_score`。
  - 识别不到任何小节时，任务失败，错误信息为"没有识别到谱表"。
  - `GET /api/jobs/{id}/score`：返回 JSON；还没有识别结果时返回 404。
  - `PUT /api/jobs/{id}/score`：校验后原子写入（先写临时文件再改名）；不合法时返回 422，附中文说明。
  - `GET /api/jobs`：最近的任务列表（id、创建时间、状态、标题或来源），按时间倒序。
- **跨重启持久化：**
  - `JobStore` 启动时扫描数据目录，从各个 `state.json` 恢复任务；
  - 恢复时，处于 `downloading`、`analyzing`、`recognizing` 的任务标为 `failed`，错误信息为"程序重启，处理被中断，请重试"。
- **发布包：** PyInstaller 加入 `app/omr/models`。训练字体不需要打包。

### 前端
- `src/lib/alphatex.js` 提供 `scoreToTex(score) -> string`。Score 到 alphaTex 的映射：
  - 头部：`\title`、`\tempo`；轨道使用 `\staff {tabs}`；`\tuning` 由 MIDI 转换成音名，从最高音弦写到最低音弦；`\ts 4 4`。
  - 每一拍：
    - 和弦写成 `(f.s f.s)`；
    - 闷音写成 `x.s`，休止写成 `r`；
    - 时值写 `.d`，附点加 `{d}`，三连音加 `{tu 3}`。
  - 空小节写成全休止 `r.1`；小节之间用 `|` 分隔。
- `src/lib/scoreEdit.js`：纯函数，都返回新的 Score，不修改原对象。
  - `setFret(score, m, b, string, value)`：`value` 为 `null`、`'x'` 或数字；
  - `setDuration`、`toggleDot`、`toggleTriplet`、`toggleRest`；
  - `insertBeat(score, m, b, where)`；
  - `deleteBeat`：删除小节中最后一拍时，改为一个全休止拍；
  - `confirmBeat`；
  - `measureFill(measure) -> {used, capacity}`（分数运算）；
  - `needsReview(measure, beat) -> bool`；
  - `nextToReview(score, from) -> {m, b} | null`。
- `src/lib/tuning.js`：预设表，`midiToName`、`nameToMidi`、`parseTuning(text, strings)`。
- 组件：
  - `ScoreView.vue`：页面本身，负责顶部设置、自动保存和导出；
  - `TabRenderer.vue`：封装 alphaTab。
    - 输入 Score，调用 `api.tex(scoreToTex(score))` 渲染；
    - 渲染完成后用 `boundsLookup` 取每一拍的位置，画出低置信度覆盖块和选中框；
    - 点击时由 `beatMouseDown` 取得小节序号和拍序号，这两个序号就是 Score 中的下标；
    - `exportGp()` 返回 `Uint8Array`。
  - `BeatEditor.vue`：编辑面板，以原图片段 `api.fileUrl(job, page.file)` 按 `measure.x0..x1` 裁剪显示。
- **网址与恢复：**
  - 当前任务写入 `location.hash`，格式为 `#job=<id>`；页面加载时如果网址带着任务号，就恢复该任务；
  - 输入页显示"最近的任务"，点击即可恢复。
- **alphaTab 集成：** 依赖 `@coderline/alphatab@1.8.4`，使用官方 Vite 插件处理字体和 worker。
- **识别结果到原图的对应：** `Measure.line` 是识别时的行序号，对应提交的 `order[line]` 那一页，也就是那一页的图片文件。

## 错误处理
- 识别失败：任务进入 `failed` 并显示中文原因，可以回到校对页重试。
- 保存失败：页面顶部显示"未保存"提示，并在下次修改时重试；不打断编辑。
- 导出失败（alphaTab 抛出异常）：显示错误信息，不影响已保存的 Score。
- alphaTex 转换遇到非法数据（例如品格超出范围）：在编辑面板中阻止输入，不进入 Score。

## 测试
- **前端（Vitest）：**
  - `alphatex`：弦号换算、7 弦定弦、和弦、闷音、休止、附点、三连音、空小节；
  - `scoreEdit`：每个操作的输入输出，以及不修改原对象；
  - `tuning`：音名与 MIDI 的往返转换、预设、错误输入；
  - Node 中的往返：`scoreToTex` → alphaTab 导入 → `Gp7Exporter` 导出，产物非空，并且读回的拍数和品格一致。
- **后端（pytest）：**
  - 在合成视频上跑识别接口（状态流转、`score.json`）；
  - `GET` / `PUT` score（校验、422、原子写入）；
  - `GET /api/jobs` 列表；
  - 重启恢复，以及中断任务被标为失败。
- **端到端：**
  - 用首个样本走完整流程：导出 `.gp` 后，用 `gpif.read_track` 读回并与标准答案对比，要求和识别引擎自身指标一致；
  - 在 Guitar Pro 8 中打开导出的文件（手动）。

## 不在范围内
播放和试听、演奏技巧编辑、多声部、识别速度标记和拍号（统一按 4/4）、键盘快捷键、同时编辑多个声部。
