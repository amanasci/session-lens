# Contributing

## Develop

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python server.py
```

The source launcher preserves workspace data in `./data`. The installed CLI uses the user data directory unless `--data-dir` is supplied. On Windows activate with `.venv\Scripts\activate`.

Source layout:

- `src/session_lens/server.py`: JSONL parsing, annotations, HTTP handlers, and CLI.
- `src/session_lens/static/`: HTML, CSS, and JavaScript packaged with the application.
- `src/session_lens/examples/demo.jsonl`: fabricated example, safe to distribute.
- `tests/`: parser, request-handler, CLI, and frontend review regression tests.
- `scripts/smoke_install.py`: verifies an installed wheel outside the source import path.

## Check

```sh
python -m unittest discover -s tests -v
node --check src/session_lens/static/app.js
node tests/test_review.cjs
```

Python HTTP tests run actual request bytes through handlers in memory, so they do not need sockets. Frontend tests use a lightweight document stand-in and do not replace visual browser testing. For manual QA, run the app, import a session, flag an event, save a note, reload, and verify the flagged filter and call/result links. The sandbox used during initial development blocked localhost sockets, so browser appearance could not be verified there.

## Build and verify

```sh
python -m pip install build
python -m build
python -m venv .venv-smoke
.venv-smoke/bin/python -m pip install --no-deps dist/codex_session_lens-0.1.0-py3-none-any.whl
.venv-smoke/bin/python -I scripts/smoke_install.py
.venv-smoke/bin/session-lens --version
```

On Windows use `.venv-smoke\Scripts\python` and `.venv-smoke\Scripts\session-lens`. Build outputs are a wheel and a source archive in `dist/`; neither should contain real sessions, annotations, credentials, or local configuration. CI runs tests and verifies the wheel and source archive. Version changes belong in both `pyproject.toml` and `src/session_lens/__init__.py`.

## Prepare a Git push

No remote or hosting account is configured. From a writable checkout:

```sh
git init -b main
git add .
git status --short
git diff --cached --stat
```

Review the staged paths before committing. Only the fabricated `src/session_lens/examples/demo.jsonl` should be staged as JSONL. Real `data/`, databases, build outputs, virtual environments, and agent configuration should remain ignored. A GitHub Actions workflow is included for pull requests and pushes to `main`.

Then commit and connect the repository you create:

```sh
git commit -m "Initial Session lens release"
git remote add origin <your-repository-url>
git push -u origin main
```

Some agent workspaces mount `.git` read-only. Initialize and push from a normal writable checkout in that case.
