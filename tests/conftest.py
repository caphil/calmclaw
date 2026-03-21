import pytest


def pytest_addoption(parser):
    parser.addoption('--run-evals', action='store_true', default=False,
                     help='Run LLM evals (requires a running MLX server)')


def pytest_collection_modifyitems(config, items):
    if not config.getoption('--run-evals'):
        skip = pytest.mark.skip(reason='pass --run-evals to run (requires MLX server)')
        for item in items:
            if 'evals' in str(item.fspath):
                item.add_marker(skip)


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
