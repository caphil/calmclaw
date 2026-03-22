"""
LLM evals — require a running MLX server.
Run with: pytest tests/evals/ -v --run-evals
"""
import pytest
import requests
from main import build_system_prompt, extract_native_tool_call
import main


def _sys():
    return [{'role': 'developer', 'content': build_system_prompt()}]


def _call(messages):
    try:
        return main.call_llm(messages)
    except requests.exceptions.ConnectionError:
        pytest.skip("MLX server not running — start the model server first")


def test_tool_call_format():
    """Model should emit a properly structured bash tool call."""
    messages = _sys() + [{'role': 'user', 'content': 'List files in my home directory'}]
    _, raw, _ = _call(messages)
    result = extract_native_tool_call(raw)
    assert result is not None, f"No tool call found in output:\n{raw[:400]}"
    name, _, command = result
    assert name == 'bash', f"Expected bash tool, got: {name}"
    assert command, f"Tool call had no command: {raw[:400]}"


def test_reddit_uses_curl_not_browse():
    """Model should follow SYSTEM_RULES: use bash+curl for Reddit, not browse."""
    messages = _sys() + [{'role': 'user', 'content': 'Search Reddit for latest news about Python'}]
    _, raw, _ = _call(messages)
    result = extract_native_tool_call(raw)
    assert result is not None, f"No tool call found:\n{raw[:400]}"
    name, _, command = result
    assert name == 'bash', f"Expected bash, got {name} — model used browse instead of curl"
    assert 'curl' in (command or '').lower(), f"Expected curl in command:\n{command}"
    assert 'reddit' in (command or '').lower(), f"Expected reddit in command:\n{command}"


def test_basic_coherence():
    """Model should return a sensible, non-empty answer to a trivial question."""
    messages = _sys() + [{'role': 'user', 'content': 'What is 2 + 2?'}]
    cleaned, _, _ = _call(messages)
    assert cleaned.strip(), "Model returned empty response"
    assert len(cleaned) > 2, f"Response suspiciously short: {repr(cleaned)}"
    assert '4' in cleaned, f"Expected '4' in response to '2+2', got:\n{cleaned}"
