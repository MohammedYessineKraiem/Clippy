from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from .config import app_data_dir
from .models import Classification, Entry, Section, SectionKind
from .risk_detection import detect_risk
from .security import VaultLockedError, VaultManager, new_salt

DEFAULT_SECTION_CONTENT_VERSION = b"2"

DEFAULT_SECTIONS: tuple[dict[str, object], ...] = (
    {
        "name": "Malicious",
        "slug": "malicious",
        "kind": "structural",
        "priority": 0,
        "patterns": [],
    },
    {
        "name": "API Keys",
        "slug": "api-keys",
        "kind": "structural",
        "priority": 10,
        "patterns": [
            r"re:\bsk-[A-Za-z0-9_-]{20,}\b",
            r"re:\bghp_[A-Za-z0-9]{30,}\b",
            r"re:\bgithub_pat_[A-Za-z0-9_]{40,}\b",
            r"re:\bglpat-[A-Za-z0-9_-]{20,}\b",
            r"re:\bAIza[A-Za-z0-9_-]{30,}\b",
            r"re:\bAKIA[A-Z0-9]{16}\b",
            r"re:\bnpm_[A-Za-z0-9]{30,}\b",
            r"re:\bxox[baprs]-[A-Za-z0-9-]{20,}\b",
            r"re:\bsk_(?:live|test)_[A-Za-z0-9]{20,}\b",
            r"re:\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b",
            r"re:-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
            r"re:\b(?:Authorization:\s*Bearer|Bearer)\s+[A-Za-z0-9._~+/=-]{20,}",
            "entropy",
        ],
    },
    {
        "name": "URLs",
        "slug": "urls",
        "kind": "structural",
        "priority": 20,
        "patterns": [r"re:https?://[^\s]+"],
    },
    {
        "name": "Email addresses",
        "slug": "email-addresses",
        "kind": "structural",
        "priority": 22,
        "patterns": [
            r"re:(?<![\w.+-])[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@"
            r"(?:[A-Z0-9-]+\.)+[A-Z]{2,63}(?![\w.-])"
        ],
    },
    {
        "name": "IP addresses",
        "slug": "ip-addresses",
        "kind": "structural",
        "priority": 24,
        "patterns": [
            r"re:(?<![\d.])(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
            r"(?:\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}(?![\d.])"
        ],
    },
    {
        "name": "Directories",
        "slug": "directories",
        "kind": "structural",
        "priority": 30,
        "patterns": [
            r"re:(?:[A-Za-z]:\\|\\\\)[^\r\n<>|?*]+",
            r"re:/(?:home|Users|usr|var|opt|tmp|etc|srv)/[^\r\n]+",
            r"re:file:///(?:[A-Za-z]:/|/)[^\r\n]+",
            r"re:(?m)^\s*(?:\.\.?[/\\])(?:[\w .-]+[/\\])+[\w .-]+\s*$",
        ],
    },
    {
        "name": "JSON",
        "slug": "json",
        "kind": "syntax",
        "priority": 34,
        "patterns": [
            r"re:(?s)^\s*\{\s*\"[^\"\r\n]+\"\s*:\s*"
            r"(?:\"|\{|\[|-?\d|true\b|false\b|null\b)",
            r"re:(?s)^\s*\[\s*\{\s*\"[^\"\r\n]+\"\s*:",
        ],
    },
    {
        "name": "SQL",
        "slug": "sql",
        "kind": "syntax",
        "priority": 36,
        "patterns": [
            r"re:(?is)\bSELECT\b.{1,800}\bFROM\b.{1,800}"
            r"(?:\bWHERE\b|\bJOIN\b|\bGROUP\s+BY\b|\bORDER\s+BY\b|\bLIMIT\b|\bUNION\b|;)",
            r"re:(?is)\bINSERT\s+INTO\b.{1,800}\bVALUES\s*\(",
            r"re:(?is)\bUPDATE\s+[\w.\[\]`\"]+\s+SET\b",
            r"re:(?is)\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:TABLE|VIEW|INDEX)\b",
            r"re:(?is)\bALTER\s+TABLE\b.{1,800}\b(?:ADD|DROP|ALTER)\b",
        ],
    },
    {
        "name": "Python code",
        "slug": "python-code",
        "kind": "syntax",
        "priority": 40,
        "patterns": [
            r"re:(?m)^\s*(?:async\s+)?def\s+[A-Za-z_]\w*\s*\(",
            r"re:(?m)^\s*class\s+[A-Za-z_]\w*(?:\([^\r\n]*\))?\s*:",
            r"re:(?m)^\s*from\s+[\w.]+\s+import\s+(?:[A-Za-z_*]\w*|\([^\r\n]+\))"
            r"(?:\s+as\s+[A-Za-z_]\w*)?\s*(?:#.*)?$",
            r"re:(?m)^\s*import\s+[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*"
            r"(?:\s+as\s+[A-Za-z_]\w*)?(?:\s*,\s*[A-Za-z_]\w*"
            r"(?:\.[A-Za-z_]\w*)*)*\s*(?:#.*)?$",
            r"re:(?m)^\s*(?:if|elif|for|while|with|try|except)\b[^\r\n]*:\s*$",
            "keyword:if __name__ ==",
            "keyword:__name__",
        ],
    },
    {
        "name": "JavaScript & TypeScript",
        "slug": "javascript-typescript",
        "kind": "syntax",
        "priority": 44,
        "patterns": [
            r"re:(?m)^\s*(?:const|let|var)\s+[A-Za-z_$][\w$]*\s*=",
            r"re:\bfunction\s+[A-Za-z_$][\w$]*\s*\(",
            r"re:(?:\([^\r\n()]*\)|[A-Za-z_$][\w$]*)\s*=>",
            r"re:\b(?:console\.(?:log|warn|error)|document\.querySelector|"
            r"JSON\.(?:parse|stringify))\s*\(",
            r"re:(?m)^\s*import\s+[^\r\n;]+\s+from\s+['\"][^'\"]+['\"]",
            r"re:\binterface\s+[A-Za-z_$][\w$]*\s*\{",
            r"re:\b(?:type|enum|namespace)\s+[A-Za-z_$][\w$]*\s*[={]",
        ],
    },
    {
        "name": "Java code",
        "slug": "java-code",
        "kind": "syntax",
        "priority": 50,
        "patterns": [
            "keyword:public class",
            "keyword:public static void main",
            "keyword:System.out.",
            r"re:(?m)^\s*package\s+[a-z]\w*(?:\.[a-z]\w*)*;\s*$",
            r"re:(?m)^\s*import\s+java(?:x)?\.[\w.*]+;",
            r"re:\b(?:class|interface|enum)\s+[A-Z]\w*\s*(?:extends|implements|\{)",
            r"re:@(?:Override|Deprecated|SuppressWarnings)\b",
            r"re:\b(?:private|protected|public)\s+\w+(?:<[^>]+>)?\s+\w+\s*\(",
        ],
    },
    {
        "name": "Configuration",
        "slug": "configuration",
        "kind": "syntax",
        "priority": 54,
        "patterns": [
            r"re:(?m)^\s*\[[A-Za-z0-9_.:-]+\]\s*$\r?\n\s*[A-Za-z_][\w.-]*\s*=",
            r"re:(?m)^\s*[A-Za-z_][\w.-]*:\s+[^\r\n]+\r?\n"
            r"(?:\s{2,}[A-Za-z_][\w.-]*:\s*|[A-Za-z_][\w.-]*:\s+)",
            r"re:(?m)^\s*[A-Z][A-Z0-9_]{1,60}=.*\r?\n[A-Z][A-Z0-9_]{1,60}=",
            r"re:(?s)^\s*<\?xml\b.{0,3000}<[A-Za-z_][\w:.-]*(?:\s|>)",
        ],
    },
    {
        "name": "Markdown",
        "slug": "markdown",
        "kind": "syntax",
        "priority": 56,
        "patterns": [
            r"re:(?m)^```[A-Za-z0-9_-]*\s*$",
            r"re:(?m)^#{1,6}\s+\S.+$",
            r"re:\[[^\]\r\n]+\]\((?:https?://|\./|\.\./|/)[^)\r\n]+\)",
            r"re:(?m)^\s*[-*+]\s+\[[ xX]\]\s+\S",
        ],
    },
    {
        "name": "Commands",
        "slug": "commands",
        "kind": "syntax",
        "priority": 60,
        "patterns": [
            r"re:^\s*(?:git|npm|pnpm|yarn|pip|pipx|python|py|node|deno|docker|"
            r"podman|kubectl|helm|cargo|rustup|dotnet|winget|choco|scoop|curl|wget|"
            r"ssh|scp|rsync|make|cmake|gradle|mvn|go)\s+[^\r\n]+$",
            r"re:^\s*(?:sudo\s+)?[A-Za-z][\w.-]*(?:\.exe)?\s+(?:--?[\w-]+)"
            r"[^\r\n]*$",
            r"re:(?m)^\s*(?:PS\s+[^>\r\n]+>|\$)\s+[A-Za-z][^\r\n]+$",
            r"re:^\s*(?:Get|Set|New|Remove|Start|Stop|Invoke)-[A-Za-z]+\b[^\r\n]*$",
        ],
    },
    {
        "name": "Errors & Logs",
        "slug": "errors-logs",
        "kind": "syntax",
        "priority": 64,
        "patterns": [
            "keyword:Traceback (most recent call last)",
            r"re:(?m)^\s*(?:Caused by:\s+)?[A-Za-z_$][\w.$]*(?:Exception|Error):\s+.+$",
            r"re:(?m)^\s*at\s+[A-Za-z_$][\w.$<>]*\s*\([^\r\n]+:\d+(?::\d+)?\)\s*$",
            r"re:(?m)^\[?\d{4}-\d{2}-\d{2}[T ][^\]\r\n]+\]?\s*"
            r"(?:ERROR|WARN|WARNING|CRITICAL|FATAL)\b",
            r"re:\bHTTP/(?:1\.\d|2)\s+[45]\d\d\b",
            r"re:\b(?:Unhandled|Uncaught)\s+(?:exception|error|rejection)\b",
        ],
    },
    {
        "name": "Passwords",
        "slug": "passwords",
        "kind": "semantic",
        "priority": 70,
        "patterns": [
            r"re:(?im)^\s*(?:password|passphrase|passwd|pwd|wifi password)\s*[:=]\s*\S+\s*$"
        ],
        "examples": [
            "temporary login password for an account",
            "account passphrase copied from a password manager",
            "wifi network password",
            "one-time access password",
            "database user password",
            "router admin passphrase",
            "recovery password for an encrypted backup",
            "PIN or secret phrase used to sign in",
        ],
    },
    {
        "name": "App names",
        "slug": "app-names",
        "kind": "semantic",
        "priority": 80,
        "patterns": [
            r"re:^\s*(?:Visual Studio Code|Windows Terminal|PowerShell|PyCharm|IntelliJ IDEA|"
            r"Android Studio|Adobe Photoshop|Figma|Notion|Discord|Slack|Firefox|Google Chrome)\s*$"
        ],
        "examples": [
            "Visual Studio Code source editor",
            "Windows Terminal command-line application",
            "Adobe Photoshop image editor",
            "PyCharm Python development environment",
            "IntelliJ IDEA Java development environment",
            "Figma interface design application",
            "Notion notes and workspace app",
            "Mozilla Firefox web browser",
            "Docker Desktop container application",
            "Microsoft Teams communication app",
        ],
    },
    {
        "name": "Code",
        "slug": "code",
        "kind": "semantic",
        "priority": 90,
        "patterns": [
            r"re:(?m)^\s*#include\s*[<\"][^>\"\r\n]+[>\"]",
            r"re:(?m)^\s*using\s+System(?:\.[A-Za-z_]\w*)*;\s*$",
            r"re:(?m)^\s*namespace\s+[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*\s*[;{]",
            r"re:(?m)^\s*package\s+[a-z]\w*\s*$[\s\S]{0,2000}^\s*func\s+",
            r"re:(?m)^\s*(?:pub\s+)?fn\s+[a-z_]\w*\s*(?:<[^\r\n>]+>)?\(",
            r"re:(?is)<(?:html|body|main|section|div|button|script|style)\b[^>]*>"
            r".{0,5000}</(?:html|body|main|section|div|button|script|style)>",
            r"re:(?m)^\s*(?:[.#][A-Za-z_-][\w-]*|[A-Za-z][\w-]*)"
            r"(?:\s+[.#]?[A-Za-z_-][\w-]*)?\s*\{\s*$",
        ],
        "examples": [
            "function that transforms a value",
            "programming source code snippet",
            "class with methods and properties",
            "algorithm implementation",
            "unit test for a software component",
            "unit test asserting that invalid input is rejected",
            "regular expression and parsing logic",
            "helper function that parses an API response payload",
            "data parser that returns typed objects",
            "error handling and input validation code",
            "typed data structure definition",
            "API client method implementation",
            "HTML component markup",
            "CSS styling rules",
            "programming language code block",
        ],
    },
    {
        "name": "Vault",
        "slug": "vault",
        "kind": "vault",
        "priority": 1000,
        "visible": False,
        "examples": [],
        "expiry_seconds": None,
    },
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class Storage:
    def __init__(self, path: Path | None = None, vault: VaultManager | None = None) -> None:
        self.path = path or app_data_dir() / "clippy.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.vault = vault or VaultManager()
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._create_schema()
        self._seed_sections()
        self._enrich_default_sections()
        if self.get_meta("risk_detector_backfill_v1") is None:
            self.flag_existing_risks()
            self.set_meta("risk_detector_backfill_v1", b"1")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _create_schema(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sections (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    slug TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    visible INTEGER NOT NULL DEFAULT 1,
                    system INTEGER NOT NULL DEFAULT 0,
                    patterns_json TEXT NOT NULL DEFAULT '[]',
                    examples_json TEXT NOT NULL DEFAULT '[]',
                    expiry_seconds INTEGER
                );
                CREATE TABLE IF NOT EXISTS entries (
                    id INTEGER PRIMARY KEY,
                    text TEXT,
                    text_cipher BLOB,
                    section_id INTEGER REFERENCES sections(id),
                    created_at TEXT NOT NULL,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    vault_flag INTEGER NOT NULL DEFAULT 0,
                    embedding BLOB,
                    embedding_cipher BLOB,
                    reason TEXT,
                    similarity REAL,
                    CHECK ((vault_flag = 0 AND text IS NOT NULL AND text_cipher IS NULL)
                        OR (vault_flag = 1 AND text IS NULL AND text_cipher IS NOT NULL))
                );
                CREATE INDEX IF NOT EXISTS ix_entries_created ON entries(created_at DESC);
                CREATE INDEX IF NOT EXISTS ix_entries_section ON entries(section_id);
                CREATE TABLE IF NOT EXISTS app_meta (
                    key TEXT PRIMARY KEY,
                    value BLOB NOT NULL
                );
                """
            )

    def _seed_sections(self) -> None:
        with self._lock, self._conn:
            for section in DEFAULT_SECTIONS:
                self._conn.execute(
                    """INSERT OR IGNORE INTO sections
                    (name, slug, kind, priority, visible, system,
                     patterns_json, examples_json, expiry_seconds)
                    VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)""",
                    (
                        section["name"],
                        section["slug"],
                        section["kind"],
                        section["priority"],
                        int(section.get("visible", True)),
                        json.dumps(section.get("patterns", [])),
                        json.dumps(section.get("examples", [])),
                        section.get("expiry_seconds"),
                    ),
                )
            self._conn.execute(
                """UPDATE sections SET name='Malicious', slug='malicious', kind='structural',
                priority=0, visible=1, system=1 WHERE slug='malicious'"""
            )

    def _enrich_default_sections(self) -> None:
        if self.get_meta("default_section_content_version") == DEFAULT_SECTION_CONTENT_VERSION:
            return
        with self._lock, self._conn:
            for defaults in DEFAULT_SECTIONS:
                row = self._conn.execute(
                    "SELECT system, patterns_json, examples_json FROM sections WHERE slug=?",
                    (defaults["slug"],),
                ).fetchone()
                if row is None or not row["system"]:
                    continue
                patterns = json.loads(row["patterns_json"])
                examples = json.loads(row["examples_json"])
                for pattern in defaults.get("patterns", []):
                    if pattern not in patterns:
                        patterns.append(pattern)
                for example in defaults.get("examples", []):
                    if example not in examples:
                        examples.append(example)
                self._conn.execute(
                    "UPDATE sections SET patterns_json=?, examples_json=? WHERE slug=?",
                    (json.dumps(patterns), json.dumps(examples), defaults["slug"]),
                )
            self._conn.execute(
                """INSERT INTO app_meta(key, value) VALUES('default_section_content_version', ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (DEFAULT_SECTION_CONTENT_VERSION,),
            )

    def list_sections(self, visible_only: bool = False) -> list[Section]:
        sql = "SELECT * FROM sections"
        if visible_only:
            sql += " WHERE visible = 1"
        sql += " ORDER BY priority, id"
        with self._lock:
            return [self._row_to_section(row) for row in self._conn.execute(sql)]

    def get_section(self, slug: str) -> Section | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM sections WHERE slug = ?", (slug,)).fetchone()
        return self._row_to_section(row) if row else None

    def save_section(self, section: Section) -> Section:
        with self._lock, self._conn:
            if section.id:
                stored = self._conn.execute(
                    "SELECT slug FROM sections WHERE id=?", (section.id,)
                ).fetchone()
                if stored and stored["slug"] == "malicious":
                    section.name = "Malicious"
                    section.slug = "malicious"
                    section.kind = SectionKind.STRUCTURAL
                    section.priority = 0
                    section.visible = True
                self._conn.execute(
                    """UPDATE sections SET name=?, slug=?, kind=?, priority=?, visible=?,
                    patterns_json=?, examples_json=?, expiry_seconds=? WHERE id=?""",
                    (
                        section.name,
                        section.slug,
                        section.kind.value,
                        section.priority,
                        section.visible,
                        json.dumps(section.patterns),
                        json.dumps(section.examples),
                        section.expiry_seconds,
                        section.id,
                    ),
                )
                return section
            cursor = self._conn.execute(
                """INSERT INTO sections
                (name, slug, kind, priority, visible, system,
                 patterns_json, examples_json, expiry_seconds)
                VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)""",
                (
                    section.name,
                    section.slug,
                    section.kind.value,
                    section.priority,
                    section.visible,
                    json.dumps(section.patterns),
                    json.dumps(section.examples),
                    section.expiry_seconds,
                ),
            )
            section.id = int(cursor.lastrowid)
            return section

    def delete_section(self, section_id: int) -> None:
        with self._lock, self._conn:
            system = self._conn.execute(
                "SELECT system FROM sections WHERE id=?", (section_id,)
            ).fetchone()
            if system and system[0]:
                raise ValueError("Default sections cannot be deleted; hide them instead")
            self._conn.execute(
                "UPDATE entries SET section_id=NULL WHERE section_id=?", (section_id,)
            )
            self._conn.execute("DELETE FROM sections WHERE id=?", (section_id,))

    def flag_existing_risks(self) -> int:
        section = self.get_section("malicious")
        if section is None:
            return 0
        flagged = 0
        with self._lock, self._conn:
            rows = self._conn.execute(
                "SELECT id, text, section_id FROM entries WHERE vault_flag=0"
            ).fetchall()
            for row in rows:
                reason = detect_risk(row["text"], section.patterns)
                if reason and row["section_id"] != section.id:
                    self._conn.execute(
                        "UPDATE entries SET section_id=?, reason=?, similarity=NULL WHERE id=?",
                        (section.id, f"local risk indicator: {reason}", row["id"]),
                    )
                    flagged += 1
        return flagged

    def last_plain_text(self) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT text FROM entries WHERE vault_flag=0 ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return row[0] if row else None

    def add_entry(
        self, text: str, classification: Classification, embedding: bytes | None
    ) -> int | None:
        if not text:
            return None
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT text, vault_flag FROM entries ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if row and not row["vault_flag"] and row["text"] == text:
                return None
            cursor = self._conn.execute(
                """INSERT INTO entries
                (text, section_id, created_at, embedding, reason, similarity)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    text,
                    classification.section_id,
                    _utc_now().isoformat(),
                    embedding,
                    classification.reason,
                    classification.similarity,
                ),
            )
            return int(cursor.lastrowid)

    def list_entries(
        self,
        section_slug: str | None = None,
        before: datetime | None = None,
        after: datetime | None = None,
        limit: int = 500,
    ) -> list[Entry]:
        clauses: list[str] = []
        values: list[object] = []
        if section_slug and section_slug != "all":
            clauses.append("s.slug = ?")
            values.append(section_slug)
        if before:
            clauses.append("e.created_at < ?")
            values.append(before.astimezone(UTC).isoformat())
        if after:
            clauses.append("e.created_at >= ?")
            values.append(after.astimezone(UTC).isoformat())
        if not self.vault.is_unlocked:
            clauses.append("e.vault_flag = 0")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        values.append(limit)
        sql = f"""SELECT e.*, s.name AS section_name FROM entries e
                  LEFT JOIN sections s ON s.id=e.section_id{where}
                  ORDER BY e.pinned DESC, e.created_at DESC LIMIT ?"""
        with self._lock:
            rows = list(self._conn.execute(sql, values))
        return [self._row_to_entry(row) for row in rows]

    def get_entry(self, entry_id: int) -> Entry | None:
        with self._lock:
            row = self._conn.execute(
                """SELECT e.*, s.name AS section_name FROM entries e
                LEFT JOIN sections s ON s.id=e.section_id WHERE e.id=?""",
                (entry_id,),
            ).fetchone()
        return self._row_to_entry(row) if row else None

    def set_pinned(self, entry_id: int, pinned: bool) -> None:
        with self._lock, self._conn:
            self._conn.execute("UPDATE entries SET pinned=? WHERE id=?", (int(pinned), entry_id))

    def move_to_vault(self, entry_id: int) -> None:
        vault = self.get_section("vault")
        if not vault:
            raise RuntimeError("Vault section is missing")
        with self._lock, self._conn:
            row = self._conn.execute("SELECT * FROM entries WHERE id=?", (entry_id,)).fetchone()
            if not row or row["vault_flag"]:
                return
            text_cipher = self.vault.encrypt(row["text"].encode("utf-8"))
            embedding_cipher = self.vault.encrypt(row["embedding"]) if row["embedding"] else None
            self._conn.execute(
                """UPDATE entries SET text=NULL, text_cipher=?, embedding=NULL,
                embedding_cipher=?, section_id=?, vault_flag=1, reason='manually moved to vault'
                WHERE id=?""",
                (text_cipher, embedding_cipher, vault.id, entry_id),
            )

    def merge_exact_duplicates(self) -> int:
        removed = 0
        with self._lock, self._conn:
            plain_groups = self._conn.execute(
                """SELECT text, GROUP_CONCAT(id) ids, COUNT(*) count FROM entries
                WHERE vault_flag=0 GROUP BY text HAVING count > 1"""
            ).fetchall()
            groups = [([int(value) for value in group["ids"].split(",")]) for group in plain_groups]
            if self.vault.is_unlocked:
                vault_rows = self._conn.execute(
                    "SELECT id, text_cipher FROM entries WHERE vault_flag=1"
                ).fetchall()
                vault_groups: dict[str, list[int]] = {}
                for row in vault_rows:
                    text = self.vault.decrypt(row["text_cipher"]).decode("utf-8")
                    vault_groups.setdefault(text, []).append(row["id"])
                groups.extend(ids for ids in vault_groups.values() if len(ids) > 1)
            for ids in groups:
                placeholders = ",".join("?" for _ in ids)
                rows = self._conn.execute(
                    f"SELECT id FROM entries WHERE id IN ({placeholders}) "
                    "ORDER BY created_at DESC, id DESC",
                    ids,
                ).fetchall()
                delete_ids = [row["id"] for row in rows[1:]]
                if delete_ids:
                    self._conn.execute(
                        f"DELETE FROM entries WHERE id IN ({','.join('?' for _ in delete_ids)})",
                        delete_ids,
                    )
                    removed += len(delete_ids)
        return removed

    def sweep_expired(self, now: datetime | None = None) -> int:
        current = (now or _utc_now()).astimezone(UTC).timestamp()
        expired_ids: list[int] = []
        with self._lock:
            rows = self._conn.execute(
                """SELECT e.id, e.created_at, s.expiry_seconds FROM entries e
                LEFT JOIN sections s ON s.id=e.section_id WHERE s.expiry_seconds IS NOT NULL"""
            ).fetchall()
            for row in rows:
                created = datetime.fromisoformat(row["created_at"]).timestamp()
                if current - created >= row["expiry_seconds"]:
                    expired_ids.append(row["id"])
            if expired_ids:
                with self._conn:
                    self._conn.execute(
                        f"DELETE FROM entries WHERE id IN ({','.join('?' for _ in expired_ids)})",
                        expired_ids,
                    )
        return len(expired_ids)

    def get_meta(self, key: str) -> bytes | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM app_meta WHERE key=?", (key,)).fetchone()
        return bytes(row[0]) if row else None

    def set_meta(self, key: str, value: bytes) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO app_meta(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def vault_is_configured(self) -> bool:
        return (
            self.get_meta("vault_salt") is not None and self.get_meta("vault_verifier") is not None
        )

    def configure_vault(self, passphrase: str) -> None:
        if self.vault_is_configured():
            raise ValueError("Vault is already configured")
        salt = new_salt()
        verifier = self.vault.initialize(passphrase, salt)
        self.set_meta("vault_salt", salt)
        self.set_meta("vault_verifier", verifier)
        vault_section = self.get_section("vault")
        if vault_section:
            vault_section.visible = True
            self.save_section(vault_section)

    def unlock_vault(self, passphrase: str) -> None:
        salt = self.get_meta("vault_salt")
        verifier = self.get_meta("vault_verifier")
        if not salt or not verifier:
            raise ValueError("Vault is not configured")
        self.vault.unlock(passphrase, salt, verifier)

    def _row_to_section(self, row: sqlite3.Row) -> Section:
        return Section(
            id=row["id"],
            name=row["name"],
            slug=row["slug"],
            kind=SectionKind(row["kind"]),
            priority=row["priority"],
            visible=bool(row["visible"]),
            system=bool(row["system"]),
            patterns=json.loads(row["patterns_json"]),
            examples=json.loads(row["examples_json"]),
            expiry_seconds=row["expiry_seconds"],
        )

    def _row_to_entry(self, row: sqlite3.Row) -> Entry:
        if row["vault_flag"]:
            if not self.vault.is_unlocked:
                raise VaultLockedError("Vault is locked")
            text = self.vault.decrypt(row["text_cipher"]).decode("utf-8")
            embedding = (
                self.vault.decrypt(row["embedding_cipher"]) if row["embedding_cipher"] else None
            )
        else:
            text, embedding = row["text"], row["embedding"]
        return Entry(
            id=row["id"],
            text=text,
            section_id=row["section_id"],
            section_name=row["section_name"],
            created_at=datetime.fromisoformat(row["created_at"]),
            pinned=bool(row["pinned"]),
            vault=bool(row["vault_flag"]),
            reason=row["reason"],
            similarity=row["similarity"],
            embedding=bytes(embedding) if embedding else None,
        )
