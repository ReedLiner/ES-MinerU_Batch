[English](README.md) | [简体中文](README.zh-CN.md)

# ES MinerU Batch

Drag & drop PDF / Word / PPT / Excel / images / HTML into the window and get Markdown automatically — powered by the MinerU parsing API.

## For Users (the `.exe`)

1. Double-click `ES MinerU Batch.exe` — nothing to install. The window edges can be dragged to resize; launching a second instance shows an "already running" notice.
2. On first launch you'll be asked for an API Key: sign in at https://mineru.net/apiManage, generate a key, paste it in and save.
3. Drag in files or folders:
   - Single file → a same-named `.md` is generated next to it.
   - Folder → a sibling folder named `FolderName（MinerU）` is created automatically (e.g. `Downloads\BVI Laws` → `Downloads\BVI Laws（MinerU）`), containing the `.md` for the whole batch (subfolder structure preserved; unsupported files are skipped automatically).
4. PDFs over 200 pages are converted in segments automatically and merged into a single `.md`; retries resume from where they left off.
5. Tasks that are **Queued** can be cancelled (not yet submitted to MinerU, no quota used); tasks **Converting** can be abandoned — note: parts already submitted may still finish on MinerU's servers and consume quota. Completed segments are kept and retries will resume.
   - To stop everything at once, click **Stop All** at the bottom right: the current conversion is interrupted and no queued tasks will be submitted anymore.
   - Overly long filenames are rejected by MinerU (128-character limit); the program then automatically switches to one-by-one conversion so only that file fails, with a "please shorten the filename" hint.
6. Results are always within reach: the "Open" button on each task row, double-click a task row to open its output folder; a system notification pops up when everything finishes, and the output folder can be opened automatically per settings.
7. Besides drag & drop, you can use the "Select Files… / Select Folder…" buttons; command line is also supported: `ES MinerU Batch.exe a.pdf D:\资料`.
8. In "⚙ Settings" you can adjust:
   - **Enable OCR**: required for scanned PDFs / images with text (off by default).
   - **Document language**: Chinese & English (default) / English / Traditional Chinese / Japanese / Korean / Latin / Cyrillic / Arabic.
   - **Output directory**: leave empty to output next to the source (folders → a sibling `FolderName（MinerU）` directory), or set a unified output directory.
   - **Auto-number duplicate outputs**: when enabled, generates `a.md`, `a(1).md` instead of overwriting.
   - **Batch acceleration**: up to 50 files submitted together (on by default) for faster throughput; PDFs over 200 pages and HTML files are still converted one by one.
   - **Auto-open output folder when everything finishes**.
   - **Open log**: logs live at `%LOCALAPPDATA%\ES MinerU Batch\app.log`, recording only task and error summaries; the API Key is never logged, and signature parameters in result links are sanitized before being written.
   - Configuration is stored at `%APPDATA%\MinerUBatch\config.json` (the Key is encrypted with Windows DPAPI, decryptable only by the current user on this machine).

Note: everyone needs their own Key; daily usage quotas apply; a single file must not exceed 200 MB.

## For Developers

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash
pip install -r requirements-dev.txt
python -m pytest tests/         # run tests
python -m app.main              # launch the app
```

Packaging: run `packaging\build.bat` (or the pyinstaller commands inside it); the artifact lands at `dist\ES MinerU Batch.exe`.

## Design Document

See `docs/superpowers/specs/2026-09-08-mineru-batch-design.md`.
