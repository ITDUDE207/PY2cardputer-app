# Py2Cardputer repository notes

## Purpose

Desktop tool (CustomTkinter) that converts UIFlow 2.0 MicroPython apps into
Arduino firmware for the M5Stack Cardputer ADV. Inputs may be one `.py` file, a
project folder or a `.zip` archive. Conversion runs in OpenHands Cloud V1
against a GitHub branch; compilation runs locally with Arduino CLI.

## Commands

```bash
python main.py                         # GUI
python main.py --check                 # config + OpenHands + GitHub + Arduino status
python main.py --history               # list recorded jobs
python main.py --cli --file app.py     # headless conversion
python -m pytest                       # tests (no credentials needed)
python -m compileall -q .              # syntax check
```

## Architecture

- `core/` owns config, models, validation, job persistence, logging,
  notifications and the pipeline. Apart from `core/pipeline.py`, it must not
  import `ui`, `ai`, `github` or `compiler`.
- `ai/`, `github/` and `compiler/` are service adapters. They raise typed errors
  from `core/errors.py` and never print to stdout.
- `ui/api_key_dialog.py` is the only in-app API key entry point; it calls
  `Py2CardputerApp.save_api_key`, which writes only to `.env`.
- `ui/` only renders state and submits work; all network/Git/compiler work runs
  on `ThreadPoolExecutor` and reports through a `queue.Queue` drained by
  `after()`.
- `core/pipeline.py` is the only place that sequences the workflow. Inject
  components through `Components` for tests.

## Invariants

- Never delete branches, files or repositories automatically; never merge to
  `main`; never push conversion output to `main`.
- Never execute uploaded Python. Read, hash and `ast.parse` only.
- Folder/ZIP inputs become an in-memory bundle. ZIPs are never extracted; reject
  traversal, drive/stream paths, symlinks, encryption and oversized archives.
  Dotfiles and cache/VCS directories are excluded.
- API key comes from `.env`/environment or the in-app Dashboard/Settings save
  dialog. Never write it to `config.json`, logs, job metadata, GitHub or a pull
  request; the full key must not appear in GUI output. `core.logger.register_secret`
  + `redact` protect logs.
- New jobs must never overwrite an existing build directory.
- Keep the GUI thread free; no blocking calls in widget callbacks.

## Config precedence

Environment variables > `config.json` > dataclass defaults. API key is read only
from `OPENHANDS_API_KEY`. `config.json` is safe to commit; `.env` is ignored.

## Tests and environment limits

- 204 tests, including a real-git round trip against a local bare repo
  (`tests/test_git_integration.py`), skipped if git is absent.
- `tests/test_ui_imports.py` stubs `tkinter`/`customtkinter`; Tk rendering cannot
  be tested headlessly.
- Native Windows toasts use PowerShell and are best-effort; the in-app banner is
  the reliable path. Notification tests inject the platform and process launcher.
- Unit tests never need credentials. A one-off live OpenHands + Arduino CLI
  smoke test was run manually; do not describe it as part of the automated
  suite, and do not start more live conversations without consent.
- The configured workspace repository has no `main`; GitHub promoted the first
  pushed conversion branch to default. `default_branch()` must never return
  `"HEAD"` or a `<branch_prefix>/...` conversion branch. `create_branch` creates
  an orphan branch when no stable base exists.
- A live smoke conversion is preserved on branch
  `py2cardputer/20261121-052503-demo` (Demo sketch). Do not delete it. Its
  generated `firmware/Demo/Demo.ino` compiled with Arduino CLI 1.6.0,
  m5stack:esp32@3.3.10 and M5Cardputer@1.1.1 on Linux.
