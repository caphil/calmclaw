from main import note_save, note_read, load_notes


def test_save_and_read_note(tmp_calmclaw):
    note_save("Shopping List", "Milk, eggs, bread")
    result = note_read("Shopping List")
    assert "Milk, eggs, bread" in result


def test_read_includes_title(tmp_calmclaw):
    note_save("My Note", "Some content")
    result = note_read("My Note")
    assert "My Note" in result


def test_overwrite_note(tmp_calmclaw):
    note_save("Test Note", "First version")
    note_save("Test Note", "Second version")
    result = note_read("Test Note")
    assert "Second version" in result
    assert "First version" not in result


def test_read_all_notes(tmp_calmclaw):
    note_save("Note A", "Content A")
    note_save("Note B", "Content B")
    result = note_read(None)
    assert "Content A" in result
    assert "Content B" in result


def test_read_missing_note_returns_not_found(tmp_calmclaw):
    result = note_read("Nonexistent")
    assert "not found" in result.lower() or "no notes" in result.lower()


def test_read_all_empty(tmp_calmclaw):
    result = note_read(None)
    assert "no notes" in result.lower()


def test_load_notes_returns_list(tmp_calmclaw):
    note_save("A", "content a")
    note_save("B", "content b")
    notes = load_notes()
    assert len(notes) == 2
    titles = [n['title'] for n in notes]
    assert "A" in titles
    assert "B" in titles
