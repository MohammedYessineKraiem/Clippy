from clippy.platform_actions import extract_path, extract_url


def test_extracts_safe_quick_action_targets():
    assert extract_url("Read https://example.com/docs.") == "https://example.com/docs"
    assert str(extract_path(r"C:\Users\Ada\notes.txt")) == r"C:\Users\Ada\notes.txt"
    assert extract_url("javascript:alert(1)") is None
