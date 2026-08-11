from clippy.classification import Classifier
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
