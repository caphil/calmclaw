import pytest


@pytest.fixture
def tmp_calmclaw(tmp_path, monkeypatch):
    """Redirect all file I/O to a temp directory and patch file path constants."""
    monkeypatch.setattr('main._CALMCLAW', str(tmp_path))
    monkeypatch.setattr('main.NOTES_FILE', str(tmp_path / 'NOTES.md'))
    monkeypatch.setattr('main.MEMORY_FILE', str(tmp_path / 'MEMORY.md'))
    monkeypatch.setattr('main.REMINDERS_FILE', str(tmp_path / 'REMINDERS.md'))
    monkeypatch.setattr('main.TASKS_FILE', str(tmp_path / 'TASKS.md'))
    monkeypatch.setattr('main.STATE_FILE', str(tmp_path / 'state.json'))
    monkeypatch.setattr('main.SOUL_FILE', str(tmp_path / 'SOUL.md'))
    monkeypatch.setattr('main.SYSTEM_RULES_FILE', str(tmp_path / 'SYSTEM_RULES.md'))
    return tmp_path
