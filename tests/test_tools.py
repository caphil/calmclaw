import subprocess
import pytest
from main import call_tool


@pytest.mark.asyncio
async def test_bash_executes_command(monkeypatch):
    monkeypatch.setattr('main.execute_command', lambda cmd: f"ran: {cmd}")
    result = await call_tool('bash', {}, 'echo hi')
    assert result == 'ran: echo hi'


@pytest.mark.asyncio
async def test_bash_malformed_returns_none():
    result = await call_tool('bash', {}, '')
    assert result is None


@pytest.mark.asyncio
async def test_bash_timeout(monkeypatch):
    def raise_timeout(cmd):
        raise subprocess.TimeoutExpired(cmd, 60)
    monkeypatch.setattr('main.execute_command', raise_timeout)
    result = await call_tool('bash', {}, 'sleep 999')
    assert "timed out" in result


@pytest.mark.asyncio
async def test_browse_calls_browse_url(monkeypatch):
    monkeypatch.setattr('main.browse_url', lambda url: f"page content for {url}")
    result = await call_tool('browse', {'url': 'https://example.com'}, '')
    assert "example.com" in result


@pytest.mark.asyncio
async def test_browse_missing_url():
    result = await call_tool('browse', {}, '')
    assert "no url" in result.lower()


@pytest.mark.asyncio
async def test_strip_tags(tmp_path):
    html_file = tmp_path / 'page.html'
    html_file.write_text('<html><body><p>Hello</p></body></html>')
    result = await call_tool('strip_tags', {'file_path': str(html_file)}, '')
    assert 'Hello' in result


@pytest.mark.asyncio
async def test_strip_tags_missing_path():
    result = await call_tool('strip_tags', {}, '')
    assert "no file_path" in result.lower()


@pytest.mark.asyncio
async def test_save_note_tool(tmp_calmclaw):
    result = await call_tool('save_note', {'title': 'T', 'content': 'C'}, '')
    assert result is not None
    assert "error" not in result.lower()


@pytest.mark.asyncio
async def test_save_note_missing_title():
    result = await call_tool('save_note', {'content': 'C'}, '')
    assert "no title" in result.lower()


@pytest.mark.asyncio
async def test_read_notes_tool(tmp_calmclaw):
    from main import note_save
    note_save("X", "content x")
    result = await call_tool('read_notes', {}, '')
    assert "content x" in result


@pytest.mark.asyncio
async def test_unknown_tool():
    result = await call_tool('nonexistent_tool', {}, '')
    assert result.startswith("Error: unknown tool")
    assert "nonexistent_tool" in result
