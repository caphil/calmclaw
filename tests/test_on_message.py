import pytest
from unittest.mock import AsyncMock, MagicMock
import main


def make_update(user_id="123", text="hello"):
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.username = "testuser"
    update.effective_chat.id = int(user_id)
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


def make_context():
    context = MagicMock()
    context.bot.send_chat_action = AsyncMock()
    return context


@pytest.fixture(autouse=True)
def reset_state(tmp_calmclaw, monkeypatch):
    """Reset global conversation state and allow test user before each test."""
    main.conversations.clear()
    main.message_history.clear()
    main.user_counters.clear()
    monkeypatch.setattr('main.ALLOWED_IDS', ["123"])
    monkeypatch.setattr('main.typing_indicator', AsyncMock())


@pytest.mark.asyncio
async def test_plain_reply(monkeypatch):
    """LLM returns plain text — bot replies once with that text."""
    monkeypatch.setattr('main.call_llm', lambda msgs: ("Hello there!", "Hello there!", {}))

    update = make_update()
    await main.on_message(update, make_context())

    update.message.reply_text.assert_called_once()
    assert "Hello there!" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_unauthorized_user_ignored(monkeypatch):
    """Messages from non-allowed user IDs are silently dropped."""
    monkeypatch.setattr('main.ALLOWED_IDS', ["999"])

    update = make_update(user_id="123")
    await main.on_message(update, make_context())

    update.message.reply_text.assert_not_called()


@pytest.mark.asyncio
async def test_tool_call_then_reply(monkeypatch):
    """LLM first returns a bash tool call, then a plain reply after the tool result."""
    tool_response = 'to=functions.bash<|message|>{"command": "echo hi"}'
    final_response = "The command ran."

    call_count = 0
    def mock_llm(msgs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return (tool_response, tool_response, {})
        return (final_response, final_response, {})

    monkeypatch.setattr('main.call_llm', mock_llm)
    monkeypatch.setattr('main.execute_command', lambda cmd: "hi")

    update = make_update(text="run echo hi")
    await main.on_message(update, make_context())

    assert call_count == 2
    last_call = update.message.reply_text.call_args_list[-1][0][0]
    assert "The command ran." in last_call


@pytest.mark.asyncio
async def test_conversation_state_persists(monkeypatch):
    """Second message from same user reuses existing conversation."""
    monkeypatch.setattr('main.call_llm', lambda msgs: ("ok", "ok", {}))

    update = make_update()
    await main.on_message(update, make_context())
    await main.on_message(update, make_context())

    assert len(main.conversations["123"]) > 2
