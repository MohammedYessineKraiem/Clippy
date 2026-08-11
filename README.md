# Clippy

<p align="center">
  <img src="resources/Clippy%20Logo.png" alt="Clippy logo" width="520">
</p>

Clippy is a private, local-first clipboard manager for Windows 11. It captures text copied to
the Windows clipboard, classifies it into useful sections, and provides fast fuzzy and semantic
search from a compact keyboard-driven popup. Clipboard data, settings, embeddings, and vault
contents stay on the machine. Clippy contains no HTTP client, cloud integration, telemetry, or
runtime model downloader.

The default global hotkey is **Ctrl+Alt+V**. It is remappable from the configuration panel. Press
the hotkey again, click outside the popup, press Escape, or use the popup's X control to dismiss it.
Use **Quit Clippy** in configuration to stop the background application completely.

## What it does

- Captures text clipboard changes and skips an immediately repeated value.
- Shows every entry in **All** and classified entries in one additional section.
- Includes Passwords, Directories, App names, Code, Commands, Python code, Java code, URLs,
  API keys, and the opt-in encrypted Vault.
- Single-clicks select entries without closing the popup. Double-click or Enter copies one entry
  back to the clipboard and dismisses the popup.
- Provides row-local actions for pin, preview, Vault, URL, and Explorer without changing selection.
- Opens detected HTTP(S) URLs in the default browser and reveals detected paths in Explorer.
- Merges selected entries with newlines and compares exactly two entries in a neon, aligned,
  side-by-side line diff.
- Finds and merges exact duplicates while retaining the newest record.
- Supports per-section expiry based on capture time. Pinned entries remain subject to expiry;
  Vault defaults to never expiring.

Clippy never executes clipboard text. Commands and code are classified and displayed only.

## Classification and search

Classification stops at the first confident match:

1. Structural patterns detect API keys, URLs, and paths.
2. Syntax patterns detect Python, Java, and command-shaped text.
3. Local semantic prototypes classify remaining entries into Passwords, App names, Code, or a
   custom semantic section. Uncertain entries remain in All only.

The config panel can edit patterns and semantic examples, reorder priority, hide default sections,
and add or delete custom sections. Classification reasons and semantic scores are available in each
row's tooltip.

Search has two exclusive modes controlled in configuration. **Fast** uses substring and light
typo-tolerant matching. **Semantic** ranks the section/operator-filtered entries by meaning only,
using the local embedding model. Operators can be combined in either mode:

```text
section:python-code model loader after:2026-08-01
yesterday report
before:tuesday section:directories .bak
```

Every custom section automatically gets a `section:<slug>` operator.

## Encrypted vault

The Vault uses a PBKDF2-derived Fernet key. Both entry text and embedding are encrypted at rest.
The passphrase and derived key are never written to disk; the key exists in process memory only
while unlocked. The default auto-lock is one minute after the last vault activity. Set the timeout
to zero to keep it unlocked until the explicit Lock button is used.

Losing the passphrase means losing access to vault contents. There is no recovery or cloud copy.

## Run from source

Requirements:

- Windows 11
- Python 3.11 or 3.12, 64-bit
- A local copy of `sentence-transformers/all-MiniLM-L6-v2`

Create the environment and install the application plus development tools:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Place a complete, previously downloaded `all-MiniLM-L6-v2` model directory at:

```text
models/all-MiniLM-L6-v2/
```

For a source run, set its path explicitly and launch Clippy:

```powershell
$env:CLIPPY_MODEL_PATH = (Resolve-Path "models\all-MiniLM-L6-v2")
clippy
```

Clippy runs the same MiniLM weights through CPU-only ONNX Runtime and reads the tokenizer directly
from local files. A checkout without the model can run in an explicitly announced degraded mode for
development, but packaged releases must include it. The development-only `scripts/export_model.py`
converts a previously downloaded model snapshot; it does not download anything.

Runtime data is stored under `%LOCALAPPDATA%\Clippy`. For isolated development, set
`CLIPPY_DATA_DIR` to a directory outside the repository or to `local-data` (which is ignored).

## Tests and lint

```powershell
pytest
ruff check src tests
```

Core storage, classification, search parsing, vault encryption, expiry, and target extraction are
tested without loading Qt or the embedding model.

## Build the Windows executable

The build is deliberately offline. Install dependencies, place the model at
`models/all-MiniLM-L6-v2`, and make sure it contains `model.onnx` (generate it once with the
development-only exporter if necessary), then run:

```powershell
python scripts\export_model.py models\all-MiniLM-L6-v2
```

Build the executable:

```powershell
.\scripts\build.ps1
```

The script runs tests, checks that the model is present, and builds `dist\Clippy.exe` with
PyInstaller. The executable contains the local model and runtime assets. PyInstaller must build a
Windows executable on Windows; build output is ignored by Git.

Files under `src/clippy` and the bundled model/runtime assets ship in the executable. `tests`, the
implementation plan, developer tooling, and build scripts are development-only.

## Visual and audio identity

Clippy uses a near-black panel, violet hairline borders, restrained magenta focus glow, monospace
clipboard content, and fixed-duration eased motion. Opening expands from the cursor; closing
contracts like a small machine shutter. Four short synthetic cues cover capture, open, close, and
copy confirmation. Sound is opt-in and disabled on first install.

## Privacy and scope

Clippy supports text only. It does not sync, make network requests, capture images/files, mask
passwords, execute copied code, or run copied commands under any setting.

## License

MIT. See [LICENSE](LICENSE).
