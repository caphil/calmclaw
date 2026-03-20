# CalmClaw

<img src="assets/calmclaw.jpg" width="500"/>

CalmClaw is a local-first AI agent built specifically to work with LLMs on consumer hardware. By removing cloud dependencies and subscriptions, it reduces long-term costs and ensures your data never leaves your device. This project is a hands-on way to develop local agentic workflows while managing the specific limits of memory, context windows, and the slower speeds of on-device processing.

Local models aren't as fast or capable as cloud-based models yet, so CalmClaw is really just a starting point for what's possible right now. Even if the gap with cloud models stays huge, it will be interesting to see when the performance actually becomes good enough for daily use.

---

## What it does

- **Chat**: Talk to your agent via Telegram
- **Web browsing**: The agent can browse the web using your local Chrome via CDP
- **Scheduled tasks**: Run autonomous LLM tasks on a schedule (e.g., daily news briefing, weekly report)
- **Reminders**: Schedule one-time or recurring reminders sent directly to you via Telegram
- **Persistent memory**: The agent remembers context and your preferences
- **Terminal commands**: The agent can run shell commands on your Mac

---

## Working within local constraints

Local models have small context windows and slow inference; CalmClaw addresses these limitations:

- **Context compression**: When the agent exceeds the token limit, it automatically trims its own history before continuing. The compression planner is pluggable. The current implementation uses a Genetic Algorithm that decides whether to **Keep**, **Compress** (summarize), or **Throw** earlier messages while keeping recent activity and important tool results intact.
- **Temporal awareness**: The agent is injected with the current date and time on every request to avoid unnecessary tool calls.

---

## Tested hardware and model

CalmClaw has been developed and tested on:

- **Hardware**: MacBook Pro M1 Pro, 16 GB RAM, running macOS Tahoe
- **Model**: [gpt-oss-safeguard-20b-MLX-MXFP4](https://huggingface.co/lmstudio-community/gpt-oss-safeguard-20b-MLX-MXFP4) (4-bit quantized, ~10 GB)

The current model uses OpenAI's **Harmony response format**, a native multi-channel tool-call protocol with special tokens (`<|channel|>`, `<|message|>`, `to=functions.*`). The parser in `main.py` is built specifically around this format. Other MLX-compatible models may work with adjustments to `ENDPOINT_SUFFIX` and `MLX_SERVER_MODULE` in your `.env`, but will require parser changes for their tool-call format.

---

## Requirements

- macOS Tahoe with Apple Silicon and at least 16 GB RAM
- Python 3.14+
- A Telegram bot token ([create one via @BotFather](https://t.me/BotFather))
- Your Telegram user ID ([get it via @userinfobot](https://t.me/userinfobot))
- The gpt-oss-safeguard-20b-MLX-MXFP4 model (or another MLX-compatible model using OpenAI's **Harmony response format**)
- Google Chrome (for web browsing via CDP)

---

## Safety

> [!WARNING]
> Early-stage project. The agent has full terminal access, LLM outputs can be unpredictable. Review commands carefully. There are no safeguards in place. If you want real isolation, run this in a Docker container or VM.

---

## Setup

**1. Install uv** (if not already installed):
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**2. Clone and install:**
```bash
git clone https://github.com/caphil/calmclaw.git
cd calmclaw
uv venv --python 3.14
uv pip install -r requirements-lock.txt
```

**3. Run setup** (creates `~/.calmclaw/` with config templates):
```bash
./setup.sh
```

**4. Configure credentials:**

Edit `~/.calmclaw/.env.local`:
```
TELEGRAM_BOT_TOKEN=your-telegram-bot-token-here
ALLOWED_TELEGRAM_ID=your-telegram-id-here
```

Edit `~/.calmclaw/.env` and set your model path:
```
MLX_MODEL_PATH=/path/to/your/model
MLX_SERVER_MODULE=mlx_lm.server
```

**5. Start everything:**
```bash
./start.sh
```

This opens Terminal windows for: the MLX server, Chrome (with remote debugging), the agent, memory viewer, reminders viewer, tasks viewer, and the live conversation log.

Happy chatting 😊

> **Note**: After testing, you may want to modify the environmental parameters to get the best performance on your hardware.

---

## Current scope

- CalmClaw currently runs as a single agent instance. Multi-agent coordination is not yet supported.
- CalmClaw refrains from using a secondary lightweight model for compression. DeepSeek-R1-Distill-Qwen-1.5B was tested but could not produce summaries accurate enough for reliable compression; therefore, the primary model handles this task.

---

## Configuration

All personal configurations lives in `~/.calmclaw/`:

| File | Purpose |
|------|---------|
| `.env` | Model paths, token limits, server settings |
| `.env.local` | Telegram credentials (keep secret) |
| `SOUL.md` | Agent personality and tone |
| `SYSTEM_RULES.md` | Bot capabilities and tool rules |
| `MEMORY.md` | Persistent memory |
| `REMINDERS.md` | Active reminders |
| `TASKS.md` | Scheduled autonomous tasks |

---

## Reminders

Ask the agent to set reminders, or edit `~/.calmclaw/REMINDERS.md` directly:

```markdown
## reminder-daily-standup
- type: recurring
- due: 2026-01-01 09:00:00
- every: daily 09:00
- message: Time for the daily standup. Review your open tasks and priorities.

## reminder-client-follow-up
- type: once
- due: 2026-01-15 14:00:00
- message: Follow up with client on the Q1 proposal.
```

---

## Scheduled tasks

Tasks run autonomously: the agent browses, runs commands, prepares reports and sends the results via Telegram:

```markdown
## task-morning-briefing
- type: recurring
- due: 2026-01-01 07:30:00
- every: daily 07:30
- task: Browse for today's top business news. Summarize the 3 most relevant topics in bullet points in markdown format, save to file on desktop using format YYYY-MM-DD_news.md and then inform user.

## task-weekly-summary
- type: once
- due: 2026-01-05 17:00:00
- task: Run a summary of this week's activity: check recent bash history, open files, and provide a short executive summary.
```

---

## Telegram commands

| Command | Description |
|---------|-------------|
| `/reset` | Clear conversation history |
| `/messages` | Show message count, total chars and tokens |
| `/compress` | Manually trigger conversation compression |
| `/throw <idx> [idx ...]` | Remove messages by index (index 0 protected) |
| `/thrown <N>` | Remove the last N messages |
| `/reminders` | List active reminders |
| `/clearreminders` | Remove all reminders |
| `/tasks` | List scheduled tasks |
| `/cleartasks` | Remove all tasks |
| `/ram` | Show current RAM usage |
| `/env` | Show current environment configuration |
| `/quit` | Shut down the agent |

