from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from clippy.embeddings import vector_to_blob
from clippy.models import Classification
from clippy.security import VaultLockedError, VaultManager
from clippy.storage import Storage


def test_capture_dedup_pin_and_cleanup(tmp_path):
    storage = Storage(tmp_path / "test.db")
    classification = Classification(None, "test")
    assert storage.add_entry("alpha", classification, None)
    assert storage.add_entry("alpha", classification, None) is None
    storage.add_entry("beta", classification, None)
    storage.add_entry("alpha", classification, None)
    newest = storage.list_entries()[0]
    storage.set_pinned(newest.id, True)

    assert storage.merge_exact_duplicates() == 1
    assert len([entry for entry in storage.list_entries() if entry.text == "alpha"]) == 1
    storage.close()


def test_vault_encrypts_text_and_embedding_at_rest(tmp_path):
    vault = VaultManager(auto_lock_seconds=60)
    storage = Storage(tmp_path / "test.db", vault)
    storage.configure_vault("correct horse battery staple")
    entry_id = storage.add_entry(
        "sensitive value",
        Classification(None, "test"),
        vector_to_blob(np.asarray([0.1, 0.2], dtype=np.float32)),
    )
    storage.move_to_vault(entry_id)
    row = storage._conn.execute("SELECT * FROM entries WHERE id=?", (entry_id,)).fetchone()

    assert row["text"] is None and row["embedding"] is None
    assert b"sensitive value" not in row["text_cipher"]
    assert storage.get_entry(entry_id).text == "sensitive value"
    vault.lock()
    with pytest.raises(VaultLockedError):
        storage.get_entry(entry_id)
    storage.close()


def test_expiry_uses_capture_time_even_when_pinned(tmp_path):
    storage = Storage(tmp_path / "test.db")
    section = storage.get_section("commands")
    section.expiry_seconds = 3600
    storage.save_section(section)
    entry_id = storage.add_entry("git status", Classification(section.id, "test"), None)
    storage.set_pinned(entry_id, True)
    old = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    storage._conn.execute("UPDATE entries SET created_at=? WHERE id=?", (old, entry_id))
    storage._conn.commit()

    assert storage.sweep_expired() == 1
    assert storage.get_entry(entry_id) is None
    storage.close()
