# ES MinerU Batch

把 PDF / Word / PPT / Excel / 图片 / HTML 拖进窗口，自动转成 Markdown（基于 MinerU 精准解析 API）。

## 使用者（拿到 exe 的人）

1. 双击 `ES MinerU Batch.exe`（无需安装任何东西）。
2. 首次打开会要求填 Key：去 https://mineru.net/apiManage 登录并生成 API Key，粘贴保存。
3. 拖入文件或文件夹：
   - 单个文件 → 在同目录生成同名 `.md`。
   - 文件夹 → 在源文件夹旁边自动新建「文件夹名（MinerU）」文件夹（如 `Downloads\香港法律` → `Downloads\香港法律（MinerU）`），在里面生成整批 `.md`（子文件夹结构保留，不支持的文件自动跳过）。
4. 超过 200 页的 PDF 会自动分段转换后合并成一个 `.md`；中途失败重试会从断点续跑。
5. 「排队中」的任务可点「取消」（尚未提交给 MinerU，不消耗额度）；「转换中」的任务可点「放弃」——注意：已提交的部分 MinerU 服务端可能仍会完成转换并消耗额度，已完成的分段会保留、重试可续跑。
   - 想一次性收手，点右下角「**全部停止**」：中断当前转换，其余排队任务一律不再提交。
   - 文件名过长时 MinerU 会拒绝（限制 128 字符），此时程序会自动改为逐个转换，只让该文件失败并提示"请改短文件名"。
6. 转换结果随手可达：任务行右侧「打开」按钮、双击任务行可打开输出文件夹；全部完成后会弹系统通知，并可按设置自动打开输出文件夹。
7. 除了拖拽，也可以用「选择文件… / 选择文件夹…」按钮；还支持命令行：`ES MinerU Batch.exe a.pdf D:\资料`。
8. 在「⚙ 设置」里可以调整：
   - **启用 OCR**：扫描版 PDF / 图片文字识别需要勾选（默认关闭）。
   - **文档语言**：中英文（默认）/ 英文 / 繁体中文 / 日文 / 韩文 / 拉丁语系 / 西里尔语系 / 阿拉伯语系。
   - **输出目录**：留空则输出到源文件旁（文件夹 → 同级「同名（MinerU）」目录）；也可指定统一的输出目录。
   - **同名输出自动加序号**：开启后生成 `a.md`、`a(1).md`，不再互相覆盖。
   - **批量提速**：一次最多 50 个文件一起提交（默认开启），速度更快；超过 200 页的 PDF 与 HTML 仍逐个转换。
   - **全部完成后自动打开输出文件夹**。
   - **打开日志**：日志在 `%LOCALAPPDATA%\ES MinerU Batch\app.log`，只记录任务与错误摘要，不记录 API Key。

注意：每个人需要自己的 Key；每天有用量额度；单个文件不能超过 200MB。

## 开发者

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash
pip install -r requirements-dev.txt
python -m pytest tests/         # 运行测试
python -m app.main              # 启动程序
```

打包：`packaging\build.bat`（或手动跑其中的 pyinstaller 命令），产物在 `dist\ES MinerU Batch.exe`。

## 设计文档

UI 主题方案见 `docs/design/theme-proposals.html`。
