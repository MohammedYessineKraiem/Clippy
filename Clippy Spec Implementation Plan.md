# Clipboard Manager — Full Spec V2

**Change from V1**: classifier is now hybrid (deterministic rules + local semantic matching), not purely rule-based — see §3.

Part of the "Companion Suite" — standalone .exe, shares visual/audio identity with Jarvis-lite and Screenshot Memory Search for later linking.

---

## 1. Visual & Motion Identity (shared across the whole suite)

**Theme**: Retro neon purple, minimal, thin lines, dark background.

- **Palette**: near-black base (`#0B0710` / `#120A1C`), thin neon purple/violet accent lines (`#B24BF3` / `#8A2BE2`), soft magenta glow on active/focused elements (`#E040FB` at low opacity for glow, not fill), muted gray-violet for secondary text (`#9C8AA6`)
- **Typography**: monospace for data/content (clipboard entries, paths, code), clean geometric sans for UI chrome (labels, buttons) — keeps the "machine" feel on data, "interface" feel on controls
- **Line language**: 1px hairline borders throughout, no heavy fills — boxes are outlined, not filled, until hover/focus (which adds a thin glow, not a background color change)
- **Corners**: sharp-to-slightly-rounded (2–4px) — reads as "machine panel," not "soft app"
- **Motion principle**: everything is *deterministic* — fixed-duration eased transitions (no springy/bouncy easing), consistent timing curve across the whole suite (e.g. `cubic-bezier(0.4, 0, 0.2, 1)`, ~150–220ms for most transitions)
- **Signature open animation**: popup expands from the hotkey-invocation point (or screen center) with a thin outline that draws itself first, then content fades/scales in — like a machine panel powering on
- **Signature close animation ("machine closing")**: iris/shutter-style close — content fades out fast (~80ms), then the outline itself contracts to a point or a thin horizontal line before disappearing, echoing a CRT-power-off / aperture-closing feel
- **Sound design**: short, synthetic, low-volume cues — a soft rising "blip" on capture (new clipboard entry recorded), a subtle "thunk"/click on popup open, a descending "power-down" tick on close, a faint confirmation tick on copy-back-to-clipboard. All toggleable, all off by default on first install (opt-in, since background sound-on-copy could surprise a first-time user), volume slider in config.
- **Glow accents used sparingly**: only on the currently-focused search bar, the selected result row, and section-tab active state — not decorative everywhere, to keep it feeling minimal rather than gamer-RGB-cluttered

---

## 2. Core Behavior

### Capture
- Background listener watches the system clipboard for changes
- **Text only** for v0 (per your scope decision) — images/files explicitly out of scope
- Every new clipboard text event is:
  1. Deduplicated against the immediately preceding entry (skip if identical)
  2. Timestamped
  3. Passed through the **Classifier** (see §3) to assign a section
  4. Stored in the local database
  5. A subtle capture sound plays (if enabled)

### Invocation
- Global hotkey (default: **Ctrl+Alt+V** — avoids the Windows language-switcher conflict on Win+Space; remappable in config) opens the popup
- Popup opens near the cursor position (falls back to screen-center on multi-monitor edge cases) with the signature open animation
- Popup is always-on-top, loses focus → auto-dismiss with the close animation (configurable: pin-open toggle for users who want it to stay)

### Popup Layout
```
┌──────────────────────────────────────────────┐
│  [ search bar ................... ] [gear]   │
├──────────────────────────────────────────────┤
│  All | Passwords | Directories | Apps | Code  │
│  Commands | Python | Java | + (config)        │
├──────────────────────────────────────────────┤
│  * pinned entry preview...             [->][/]│
│  entry preview text, truncated...      [->]   │
│  entry preview text, truncated...      [/]    │
│  ...                                          │
└──────────────────────────────────────────────┘
```
- Section tabs are horizontally scrollable if the user has added custom sections
- Each result row: truncated preview text, section icon, timestamp on hover, quick-action icon(s) on the right (only shown if applicable — link icon for URLs, folder icon for paths), pin icon on hover
- Selecting a row (click or Enter) copies it back to the system clipboard and closes the popup (with the close animation + confirmation tick sound)
- **Preview button**: opens a larger inline expansion (not a new window) showing the full untruncated text, for long entries — dismiss returns to the list without losing search state

### Search & Filtering
- Live filter-as-you-type across the currently selected section (or "All")
- **Search operators**:
  - `section:code`, `section:passwords`, etc. — scope to a section from within "All"
  - `before:` / `after:` / `today` / `yesterday` — time-based filtering (e.g. `before:tuesday`)
  - Free text still does substring/fuzzy match against entry content
  - Operators are combinable: `yealio .bak section:directories`
- Matching is a two-layer pass:
  1. **Fast layer**: substring + light fuzzy matching (typo-tolerant) on the raw text — instant, runs on every keystroke
  2. **Semantic layer**: the query and all candidate entries are compared via a small local embedding model, re-ranking results by meaning — this is what makes a query like "python code for loading a model" surface a snippet that never contains those exact words
- Semantic layer only re-ranks the set already narrowed by section/operator filters, so it's never scoring the whole database — keeps it fast even as history grows
- Every entry's embedding is computed **once, at capture time**, and cached in the database — search time never pays the embedding cost for existing entries, only for the live query text itself (a few milliseconds)

---

## 3. Classifier (Sections)

### Default sections
`All` (implicit, shows everything) - `Passwords` - `Directories` - `App names` - `Code` - `Commands` - `Python code` - `Java code` - `URLs` - `API keys`

Every captured entry is always included in `All`. A classified entry is also shown in its assigned section. Classification assigns at most one non-`All` section, based on tier priority and the first confident match. Entries that do not clear the semantic confidence threshold remain visible in `All` only.

### Classification approach — hybrid, tiered for speed
Structural facts are cheap to detect with regex and are unambiguous — no reason to spend model time on them. Meaning-based grouping (topic, intent, "what is this snippet actually for") is not something regex can do, so that tier uses the same small local embedding model as search. Every entry runs through the tiers below **in order, top to bottom** — as soon as a tier confidently matches, classification stops, so most entries never reach the semantic tier at all and stay instant:

**Tier 1 — Structural regex (near-zero cost, runs first)**
- **Directories**: path-like patterns (`C:\...`, `/home/...`, path separators + known extensions)
- **API keys**: curated pattern library for known key formats (`sk-...`, `ghp_...`, `AIza...`, `AKIA...`, etc.) plus a generic high-entropy-string fallback — the same approach real secret-scanners (gitleaks, truffleHog) use, no ML needed
- **URLs**: standard URL pattern

**Tier 2 — Syntax signatures (near-zero cost, runs second)**
- **Python code**: syntax signatures (`def `, `import `, indentation patterns)
- **Java code**: syntax signatures (`public class`, `void`, semicolon-terminated blocks)
- **Commands**: shell-command-like patterns (known verbs, flag syntax `--`/`-x`) — classification only, **the app never executes these**

**Tier 3 — Semantic matching (only for what's left)**
- Anything that didn't confidently match Tier 1 or 2 — including **Passwords** (genuinely ambiguous without a source-app signal), **App names**, general **Code**, and any user-defined **custom/topic section** — falls to this tier
- Each section has a small set of **example snippets** (a few-shot prototype, defined by you or auto-seeded from the first few entries you manually sort into that section)
- The section's prototype examples are embedded once and cached; a new entry's embedding is compared against each section's prototype via cosine similarity, and it lands in the closest match above a confidence threshold — or stays in "All" only, uncategorized, if nothing clears the threshold, rather than being forced into a bad guess
- This is the same embedding model as the search layer (see §Search), so there's no second model to load — one small local model serves both jobs, keeping things fast and minimal

### Config panel
- **Structural/syntax sections** (Tier 1–2): edit the underlying pattern list — add a keyword, regex, or known key-format signature
- **Semantic sections** (Tier 3): add or remove example snippets that define what "belongs" there — no training step, the prototype just re-embeds when examples change (instant, since it's a handful of short embeddings)
- Reorder tier priority, hide default sections, add/edit/delete custom sections of either kind
- Classification stays inspectable: each entry can show *why* it landed where it did (matched pattern, or closest semantic prototype + similarity score)

### Noted for later (not in v0)
- Deeper intent detection beyond simple prototype-matching (e.g. reliably distinguishing "loads a Gemma model" from "loads a different HF model" within Python code) — flagged by you as a future refinement; V2's semantic tier handles general topic grouping well, but that level of specificity would want richer prototypes or a slightly stronger model down the line.

---

## 4. Accepted Feature Details

- **Pin/favorite**: pin icon on hover/row-select toggles pin state; pinned entries float to the top of their section (and of "All") regardless of recency
- **Quick actions** (only these two, nothing else):
  - **Open URL**: if entry matches a URL pattern, a link icon opens it in the default browser
  - **Open in Explorer**: if entry matches a directory/file path pattern, a folder icon opens that path in Explorer — no execution of anything, purely a "reveal in file manager" action
- **Duplicate cleanup**: a button (in config or a toolbar icon) scans for exact text matches only and offers a one-click merge, keeping the most recent timestamp and its current pin/vault state
- **Multi-select**: shift/ctrl-click multiple rows -> a "Copy Merged" action joins the selected entries (newline-separated) onto the clipboard as one paste
- **Diff view**: select exactly two entries -> a diff button shows a simple side-by-side or inline diff (line-level, using a standard diff algorithm) — useful for comparing two similar paths/configs/snippets
- **Encrypted vault section**: a config toggle creates a special section where both entry text and embeddings are encrypted at rest (local key derived from a user-set passphrase, e.g. via a standard KDF + symmetric encryption); entries can be manually moved into the vault from any other section; vault contents require the passphrase to view/search within that session; the vault auto-locks after one minute of inactivity, with a user option to disable auto-lock until the user presses a Lock button
- **Auto-expiry rules per section**: in config, each section (default or custom) gets an optional expiry duration (e.g. "Commands: 24h," "Code: never," "All others: 30 days" as a fallback); expiry is based on the original capture timestamp; pinned entries still expire when their section has an expiry duration; vault entries have their own expiry setting, defaulting to `Never`; a background sweep removes expired entries silently
- **Sound design**: as described in §1, all toggleable with a master volume slider
- **"Closing machine" dismiss animation**: as described in §1, applied consistently to popup dismiss, preview-expansion close, and config panel close

---

## 5. Explicitly Out of Scope (kept minimal on purpose)

- No running of copied shell commands or code — ever, under any config option
- No images or file-object clipboard support in v0 (text only)
- No cloud sync, no network calls anywhere in the app
- No heavy or cloud-based models — one small local embedding model (~80MB, CPU-only, no network calls) does double duty for both search ranking and Tier 3 classification, nothing larger
- No deep code-intent detection (e.g. distinguishing exactly what a snippet loads or does) — noted as a future idea, not built now; V2's semantic tier handles general topic/meaning grouping, not fine-grained intent
- No password masking/hiding — everything local, shown as-is, vault is opt-in for anything the user personally wants extra-protected

---

## 6. Suggested Tech Stack

- **Language**: Python (fast to build in a day; consistent with the other two apps for shared code reuse)
- **Clipboard listener**: `pyperclip` + polling thread, or a native clipboard-changed hook if available on target OS for lower overhead
- **Storage**: SQLite (single local `.db` file) — one `entries` table with `text, section, timestamp, pinned, vault_flag, embedding`; embeddings stored as a blob column so no separate vector database service is needed for this scale of data (a few thousand entries at most)
- **Embedding model**: `sentence-transformers` (`all-MiniLM-L6-v2`), local, CPU-only, ~80MB — loaded once at app startup and kept warm in memory; computes one embedding per new capture (a few ms) and re-embeds a live query at search time; entry embeddings are never recomputed once cached
- **UI**: a lightweight always-on-top overlay window — `PyQt`/`PySide` recommended over Tkinter here since the animation/glow/rounded-corner requirements are easier to achieve cleanly with Qt's styling and animation framework
- **Global hotkey**: `keyboard` or `pynput` for system-wide hotkey registration
- **Diff**: Python's built-in `difflib`
- **Encryption (vault)**: `cryptography` library (Fernet symmetric encryption, key derived from passphrase via PBKDF2/Argon2)
- **Sound**: short pre-rendered `.wav`/`.ogg` cues played via a lightweight audio lib (`simpleaudio` or Qt's own multimedia module, to avoid adding a second dependency)
- **Platform**: Windows 11 only for v0
- **Packaging**: PyInstaller -> single `.exe`; the release package must include the local embedding model and all runtime assets so first run never downloads anything

---

## 7. Build Order (one day)

1. SQLite schema + clipboard listener + capture pipeline (with dedup)
2. Tier 1–2 structural/syntax classifier + default sections
3. Load local embedding model, wire up embed-on-capture, add Tier 3 semantic classification + prototype config
4. Popup UI shell: search bar, section tabs, result list (no animation yet, just functional)
5. Search operators + fast-layer filtering, then semantic re-ranking on top
6. Quick actions (URL/Explorer), pin, preview expansion
7. Visual pass: neon purple theme, hairline borders, glow states
8. Motion pass: open/close animations, signature "machine" dismiss
9. Sound design + toggle/volume config
10. Multi-select merge, duplicate cleanup, diff view
11. Encrypted vault + auto-expiry config
12. Config panel: custom sections, hotkey remap, semantic-section prototype editor, all toggles in one place
13. Package as `.exe`, smoke-test

---

## 8. Finalized decisions

- v0 targets Windows 11 only. Linux/Ubuntu support is intentionally deferred.
- The app is fully local: no cloud calls, HTTP requests, telemetry, or model downloads at runtime.
- The local embedding model is `all-MiniLM-L6-v2`, bundled with releases and loaded in offline mode.
- The packaged runtime uses a CPU-only ONNX export of the same `all-MiniLM-L6-v2` weights. This preserves the model's embeddings while avoiding a large Torch/CUDA runtime; model conversion is development-only and the app never downloads weights.
- URLs and API keys have visible default sections in addition to their structural matching and quick-action metadata.
- There is no manual reclassification action. Semantic-section examples are managed through the config panel's prototype editor.
- Every entry appears in `All`; a confidently classified entry also appears in one assigned non-`All` section.
- Vault auto-lock is measured from the last vault activity. The default is one minute; users may choose never to auto-lock and use an explicit Lock button.
- Vault text and embeddings are encrypted at rest. The passphrase-derived key is held only in memory for the unlocked session and is never persisted in plaintext.
- Auto-expiry uses the original capture timestamp. Pinned entries are still subject to expiry. Vault expiry defaults to `Never` and can be configured separately.
- Duplicate cleanup removes exact text duplicates only, keeps the newest timestamp, and preserves the newest record's pin/vault state.
- Custom sections automatically support `section:<name>` search operators.
- The project uses the MIT license.

The former open question is resolved by the decision above: custom sections automatically receive `section:<name>` search operators.
