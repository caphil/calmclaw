from main import (
    _title_to_slug,
    dedup_links,
    filter_links,
    clean_llm_output,
    estimate_tokens,
    extract_native_tool_call,
    extract_analysis,
)


# --- _title_to_slug ---

def test_slug_basic():
    assert _title_to_slug("Hello World") == "hello-world"

def test_slug_special_chars():
    assert _title_to_slug("My Note! #1") == "my-note-1"

def test_slug_leading_trailing():
    assert _title_to_slug("  spaces  ") == "spaces"


# --- dedup_links ---

def test_dedup_links_removes_duplicates():
    links = [("Page A", "https://a.com"), ("Page B", "https://b.com"), ("Dup A", "https://a.com")]
    result = dedup_links(links)
    assert len(result) == 2

def test_dedup_links_truncates_text():
    long_text = "x" * 100
    result = dedup_links([(long_text, "https://a.com")])
    assert len(result) == 1
    assert len(result[0]) < 120

def test_dedup_links_skips_empty_text():
    result = dedup_links([("", "https://a.com"), ("Page", "https://b.com")])
    assert len(result) == 1


# --- filter_links ---

def test_filter_links_caps_at_max_links(monkeypatch):
    monkeypatch.setattr('main.MAX_LINKS', 3)
    lines = [f"[Page {i}](https://example{i}.com)" for i in range(10)]
    result = filter_links(lines)
    assert len(result) == 3

def test_filter_links_removes_skip_domains():
    lines = [
        "[Google Account](https://accounts.google.com/login)",
        "[Real Page](https://example.com/article)",
    ]
    result = filter_links(lines)
    assert len(result) == 1
    assert "example.com" in result[0]

def test_filter_links_passes_non_markdown():
    result = filter_links(["plain text line"])
    assert result == ["plain text line"]


# --- clean_llm_output ---

def test_clean_strips_think_tags():
    text = "<think>internal reasoning</think>Final answer"
    assert clean_llm_output(text) == "Final answer"

def test_clean_strips_special_tokens():
    text = "<|end|>Hello<|assistant|>"
    result = clean_llm_output(text)
    assert "<|" not in result
    assert "Hello" in result

def test_clean_final_channel():
    text = "stuff<|channel|>final<|message|>The real answer"
    assert clean_llm_output(text) == "The real answer"


# --- estimate_tokens ---

def test_estimate_tokens_basic():
    messages = [{'role': 'user', 'content': 'Hello world'}]
    assert estimate_tokens(messages) > 0

def test_estimate_tokens_empty():
    assert estimate_tokens([]) == 0

def test_estimate_tokens_scales_with_length():
    short = [{'role': 'user', 'content': 'hi'}]
    long = [{'role': 'user', 'content': 'hi' * 1000}]
    assert estimate_tokens(long) > estimate_tokens(short)


# --- extract_native_tool_call ---

def test_extract_bash_tool_call():
    text = 'to=functions.bash<|message|>{"command": "ls ~"}'
    result = extract_native_tool_call(text)
    assert result is not None
    name, args_json, command = result
    assert name == 'bash'
    assert command == 'ls ~'

def test_extract_browse_tool_call():
    text = 'to=functions.browse<|message|>{"url": "https://example.com"}'
    result = extract_native_tool_call(text)
    assert result is not None
    name, _, _ = result
    assert name == 'browse'

def test_extract_returns_none_for_no_match():
    assert extract_native_tool_call("just some plain text") is None


# --- extract_analysis ---

def test_extract_analysis_found():
    text = "<|channel|>analysis<|message|>My thinking here<|end|>"
    assert extract_analysis(text) == "My thinking here"

def test_extract_analysis_not_found():
    assert extract_analysis("no analysis here") is None
