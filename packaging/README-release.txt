video-to-tab — 从吉他演奏视频中提取 tab 谱，拼成完整的长图 / PDF；
              识别钢琴演奏视频中的五线谱，导出 MusicXML

运行
  Windows : 双击 video-to-tab.exe
  macOS   : 在终端中运行 ./video-to-tab（首次运行如被系统拦截：
            系统设置 → 隐私与安全性 → 仍要打开）
  Linux   : 在终端中运行 ./video-to-tab

启动后会自动打开浏览器（默认 http://127.0.0.1:8000）。关闭命令行窗口即退出。

使用
  1. 上传本地视频，或粘贴 bilibili / YouTube 链接、BV 号
  2. 确认谱面区域（蓝框），不准时在图上拖拽重新框选
  3. 校对页面：拖动调整顺序，× 删除多余页面
  4. 导出长图 PNG 或 PDF

钢琴谱
  页面顶部切换到“钢琴谱”，上传视频或粘贴链接，等待截取和识别完成后，
  对照原图检查，可删除或重新识别某一组，最后“导出 MusicXML”。
  识别模型已随程序附带，无需联网；每个识别进程约占 1 GB 内存。

说明
  - 处理数据保存在程序旁边的 data/ 文件夹中，可随时删除。
  - B 站需要登录或受地区限制时：把浏览器导出的 cookies（Netscape 格式）
    保存为程序旁边的 cookies.txt，重新启动即可。
  - 分段横向滚动的谱面会自动拼接去重并按小节重新排行。

许可证：GNU AGPL-3.0（见 LICENSE），钢琴谱识别基于 homr（AGPL-3.0）。

项目主页：https://github.com/AkabaSaika/video-to-tab
