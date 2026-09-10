# ES MinerU Batch

Drag PDF / Word / PPT / Excel / image / HTML files into the window and get clean Markdown back — powered by the [MinerU](https://mineru.net) precision parsing API.

[中文说明](README.zh-CN.md)

## Features

- **Drag & drop** files or whole folders. Sub-folder structure is preserved; unsupported files are skipped automatically.
- **Batch conversion**: up to 50 files per submission (toggleable). PDFs over 200 pages and HTML files are still converted one by one.
- **Large PDF support**: PDFs longer than 200 pages are split into segments, converted, then merged into a single `.md`. A failed run resumes from the last completed segment.
- **OCR** toggle for scanned PDFs and images (off by default).
- **8 document languages**: Chinese (simplified) / English / Traditional Chinese / Japanese / Korean / Latin / Cyrillic / Arabic.
- **Flexible output**: next to the source file by default; for a folder, a sibling `FolderName (MinerU)` folder is created; or pick one fixed output directory.
- **Duplicate handling**: optionally auto-number colliding outputs (`a.md`, `a(1).md`) instead of overwriting.
- **Task control**: cancel a *Queued* task before it is submitted (no quota consumed); abandon a *Converting* task (already submitted segments may still complete on the server side and consume quota).
- **Quick access**: per-row **Open** button, double-click a row to open its output folder, desktop notification when everything finishes, and an optional auto-open of the output folder.
- **Command line**: `ES MinerU Batch.exe a.pdf D:\Docs`.
- **Privacy**: the API key is stored per-user and encrypted with Windows DPAPI; it is never written to the log.

## Supported input formats

`.pdf` `.doc` `.docx` `.ppt` `.pptx` `.xls` `.xlsx` `.png` `.jpg` `.jpeg` `.bmp` `.webp` `.html` `.htm`

## Requirements

- Windows 10 / 11 (Qt desktop app; the key is protected with Windows DPAPI)
- Python 3.9+ (only needed when running from source)
- Your own MinerU API key — generate one at <https://mineru.net/apiManage>

Limits imposed by the MinerU service: a single file must be under 200 MB, and each account has a daily quota.

## For users (no Python needed)

1. Download `ES MinerU Batch.exe` from **Releases** and double-click it.
2. On first launch, paste your API key and save it.
3. Drop files or folders into the window, or use **Select files… / Select folder…**.
4. Open **⚙ Settings** to tune OCR, language, output directory, batch size, duplicate naming and auto-open.

Logs are written to `%LOCALAPPDATA%\ES MinerU Batch\app.log` (task and error summaries only).

## For developers

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements-dev.txt
python -m pytest tests/         # run tests
python -m app.main              # launch the app
```

On Windows you can also just double-click `启动 ES MinerU Batch.bat`.

Build a standalone exe:

```bash
packaging\build.bat             # output: dist\ES MinerU Batch.exe
```

## Project layout

```
app/
  core/      config (key storage, settings), collect (path → task mapping), app_log
  engine/    MinerU API client, conversion pipeline, error types
  ui/        Qt main window, settings dialog, task widgets, theme, worker threads
tests/       pytest suite
packaging/   PyInstaller spec, build script, Windows version info
docs/        design spec, plan and UI theme proposals
```

Design document: `docs/superpowers/specs/2026-09-08-mineru-batch-design.md`

## Security notes

- The API key lives in `%APPDATA%\MinerUBatch\config.json` and is encrypted with `CryptProtectData` (current Windows user only). If DPAPI is unavailable it falls back to plaintext.
- Only a masked preview (`abcd****`) is shown in the UI, and the key is never logged.
- Nothing is uploaded anywhere except to the MinerU API you configure.

## License

MIT — see [LICENSE](LICENSE).

This is an unofficial client for the MinerU API. "MinerU" is a trademark of its respective owner; this project is not affiliated with or endorsed by it.
