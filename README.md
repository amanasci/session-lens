# Session lens

A local viewer for Codex coding sessions. Follow every recorded event, inspect tool calls and results, and flag suspicious steps with review notes.

- Three-pane interface: sessions, searchable event timeline, and event inspector.
- Readable content and original JSON, with source line numbers.
- Filters for messages, tools, reasoning, system records, and flagged events.
- Links between tool calls and results using recorded call IDs.
- Persistent flags and notes, with a cross-session review list.
- Local only: no accounts, API keys, analytics, CDN assets, or runtime dependencies.

Requires **Python 3.10+** with SQLite support. A browser is the only UI requirement. Node.js is needed only for frontend development tests. This project is independent of OpenAI.

## Install

From a clone or downloaded source directory:

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install .
session-lens --demo
```

On Windows, activate with `.venv\Scripts\activate` instead. If you already use pipx, `pipx install .` installs the CLI into its own environment.

Open **http://127.0.0.1:8765**. The demo is entirely synthetic; no real conversations are included in the package. Stop the server with Ctrl+C.

Import your own saved sessions at startup:

```sh
session-lens --import-dir ~/.codex/sessions
```

Or use **Import session** in the UI for individual JSONL files up to 32 MB. Startup directory imports have no 32 MB limit. Imports copy snapshots; the originals are never edited. Refresh reloads the copies, not the original Codex files. Run the import command again for fresh snapshots.

`python -m session_lens` is equivalent to `session-lens`. The package is not published to PyPI; the commands above install from local source.

## Data and configuration

```sh
session-lens --port 9000
session-lens --data-dir ./data
session-lens --version
session-lens --help
```

The data directory contains `sessions/*.jsonl` and `flags.sqlite3`. Installed copies default to:

| Platform | Default data directory |
| --- | --- |
| Linux | `$XDG_DATA_HOME/session-lens` or `~/.local/share/session-lens` |
| macOS | `~/Library/Application Support/session-lens` |
| Windows | `%LOCALAPPDATA%\session-lens` |

Set `SESSION_LENS_DATA_DIR` or pass `--data-dir` to choose another location. `--data-dir` takes precedence. Back up the whole directory to retain both sessions and review notes. Upgrading the app does not move or remove this data.

**Existing source-checkout users:** `python server.py` continues using the repository's `data/` folder. To use those same sessions and saved flags with the installed command, run `session-lens --data-dir /absolute/path/to/this/repo/data`. No migration is required.

## Review a session

Select a session in the sidebar, then an event in the timeline. Filter by category or search readable text, types, line numbers, and saved review notes. Every nonblank source line appears in source order, including metadata, mirrored completion records, unfamiliar types, and malformed records.

- **Readable** shows extracted text; **Raw JSON** loads the original parsed record on demand.
- Tool calls and results link to each other. Mirrored completion records are labelled “Item completed”.
- `j` / `k` select the next / previous visible event; `/` focuses search.
- Times use your browser's timezone. `L42` means source line 42, regardless of filters.

To save something for investigation, select an event and click **⚑ Flag event**. Add an optional note about the suspected failure, then click **Save note**.

- **⚑ Flagged** shows flagged events in the current session.
- **⚑ Flagged events** in the sidebar shows sessions with flags and opens their flagged timelines. Click again to return to all sessions.
- **Remove flag** deletes the flag and its saved note.
- Unsaved drafts survive switching events within the page; save before closing. The page warns about unsaved notes.

Saved flags survive page reloads and server restarts. A source fingerprint prevents old notes from appearing on different events if a snapshot's lines change. Copies imported under different filenames have separate review lists.

## Privacy and limitations

The server binds to `127.0.0.1` and serves only imported snapshots. Your local machine's users/processes with access to that port can view them; this is a local development app without authentication. Do not expose its port publicly.

Session snapshots and review notes can contain private conversation text, source code, and tool output. They are excluded from Git and distribution archives. No remote services are called. The only bundled example is synthetic.

The parser supports the saved rollout formats observed during development, not a guaranteed stable Codex schema. Unknown events fall back to JSON. It does not automatically judge failures, decrypt reasoning, render media, or reconstruct historical repository state. Readable text is not executed as HTML or Markdown. Raw JSON preserves values but is reserialized with indentation rather than preserving original whitespace. Large sessions are loaded into memory; this version targets manual review of individual sessions.

## Development and distribution

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, checks, building wheels, and preparing a Git push. Release history is in [CHANGELOG.md](CHANGELOG.md).

Licensed under the [MIT License](LICENSE).
