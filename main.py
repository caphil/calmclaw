import os
import sys
import json
import re
import subprocess
import signal
import time
from datetime import datetime, timedelta
import asyncio
import logging
import requests
from html.parser import HTMLParser
from urllib.parse import urlparse
from dotenv import load_dotenv
_COMPRESSION_PLANNER = os.getenv('COMPRESSION_PLANNER', 'ga')
if _COMPRESSION_PLANNER == 'ga':
    from compression_planners.compression_planner_ga import run_compression_planner
else:
    raise ImportError(f"Unknown COMPRESSION_PLANNER: {_COMPRESSION_PLANNER!r}")
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes
)

_CALMCLAW = os.path.expanduser(os.getenv('CALMCLAW_DIR', '~/.calmclaw'))

load_dotenv(os.path.join(_CALMCLAW, '.env'))
load_dotenv(os.path.join(_CALMCLAW, '.env.local'), override=True)

TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ALLOWED_IDS = [id.strip() for id in os.getenv('ALLOWED_TELEGRAM_ID', '').split(',')]
MODEL_PATH = os.getenv('MLX_MODEL_PATH')
PYTHON_PATH = os.getenv('MLX_PYTHON_PATH')
ENDPOINT_SUFFIX = os.getenv('ENDPOINT_SUFFIX')
MLX_PORT = os.getenv('PORT', '8000')
CDP_PORT = os.getenv('CDP_PORT', '9222')
MAX_TOKEN_INPUT_TO_LLM        = int(os.getenv('MAX_TOKEN_INPUT_TO_LLM', '3000'))
CHARS_PER_TOKEN               = float(os.getenv('CHARS_PER_TOKEN', '5'))
_out_factor     = float(os.getenv('MAX_TOKEN_OUTPUT_FACTOR',              '0.375'))
_summary_factor = float(os.getenv('MAX_TOKEN_COMPRESSION_SUMMARY_FACTOR', '0.15'))
_tool_factor    = float(os.getenv('MAX_TOOL_RESULT_CHARS_FACTOR',         '0.15'))
MAX_TOKEN_OUTPUT_FROM_LLM     = int(os.getenv('MAX_TOKEN_OUTPUT_FROM_LLM',      str(int(MAX_TOKEN_INPUT_TO_LLM * _out_factor))))
MAX_TOKEN_COMPRESSION_SUMMARY = int(os.getenv('MAX_TOKEN_COMPRESSION_SUMMARY',  str(int(MAX_TOKEN_INPUT_TO_LLM * _summary_factor))))
MAX_TOOL_RESULT_CHARS         = int(os.getenv('MAX_TOOL_RESULT_CHARS',          str(int(MAX_TOKEN_INPUT_TO_LLM * CHARS_PER_TOKEN * _tool_factor))))
MAX_COMMAND_ITERATIONS         = int(os.getenv('MAX_COMMAND_ITERATIONS',      '100'))
_summary_llm_factor        = float(os.getenv('SUMMARY_MAX_TOKEN_FACTOR', '0.8'))
SUMMARY_MAX_TOKENS         = int(MAX_TOKEN_INPUT_TO_LLM * _summary_llm_factor)
SUMMARY_REASONING_EFFORT   = os.getenv('SUMMARY_REASONING_EFFORT', 'medium')
MIN_COMPRESS_GROUP_TOKENS  = int(os.getenv('MIN_COMPRESS_GROUP_TOKENS', '50'))
GA_CAP_FACTOR              = float(os.getenv('GA_CAP_FACTOR', '0.65'))

MEMORY_FILE = os.path.join(_CALMCLAW, 'MEMORY.md')
REMINDERS_FILE = os.path.join(_CALMCLAW, 'REMINDERS.md')
TASKS_FILE = os.path.join(_CALMCLAW, 'TASKS.md')


def load_memory():
    """Load MEMORY.md content."""
    if not os.path.exists(MEMORY_FILE):
        return ''
    with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
        return f.read()


def build_system_prompt():
    """Build the developer system prompt fresh from disk on every call."""
    prompt = load_system_rules()
    content = load_memory()
    if content.strip():
        prompt += f"\n{content}\n"
    return prompt


def load_reminders():
    """Parse REMINDERS.md and return list of reminder dicts."""
    if not os.path.exists(REMINDERS_FILE):
        return []
    with open(REMINDERS_FILE, 'r', encoding='utf-8') as f:
        content = f.read()
    reminders = []
    blocks = re.split(r'^## ', content, flags=re.MULTILINE)
    for block in blocks:
        if not block.strip():
            continue
        reminder = {}
        lines = block.strip().split('\n')
        reminder['id'] = lines[0].strip()
        for line in lines[1:]:
            line = line.strip()
            if line.startswith('- '):
                line = line[2:]
            if ': ' in line:
                key, val = line.split(': ', 1)
                reminder[key.strip()] = val.strip()
        if 'due' in reminder and 'message' in reminder:
            reminders.append(reminder)
    return reminders


def save_reminders(reminders):
    """Write reminders list back to REMINDERS.md."""
    os.makedirs(_CALMCLAW, exist_ok=True)
    lines = ['# Reminders\n']
    for r in reminders:
        lines.append(f"## {r['id']}")
        lines.append(f"- type: {r.get('type', 'once')}")
        lines.append(f"- due: {r['due']}")
        if 'every' in r:
            lines.append(f"- every: {r['every']}")
        lines.append(f"- message: {r['message']}")
        lines.append('')
    with open(REMINDERS_FILE, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def load_tasks():
    """Parse TASKS.md and return list of task dicts."""
    if not os.path.exists(TASKS_FILE):
        return []
    with open(TASKS_FILE, 'r', encoding='utf-8') as f:
        content = f.read()
    tasks = []
    blocks = re.split(r'^## ', content, flags=re.MULTILINE)
    for block in blocks:
        if not block.strip():
            continue
        task = {}
        lines = block.strip().split('\n')
        task['id'] = lines[0].strip()
        for line in lines[1:]:
            line = line.strip()
            if line.startswith('- '):
                line = line[2:]
            if ': ' in line:
                key, val = line.split(': ', 1)
                task[key.strip()] = val.strip()
        if 'due' in task and 'task' in task:
            tasks.append(task)
    return tasks


def save_tasks(tasks):
    """Write tasks list back to TASKS.md."""
    os.makedirs(_CALMCLAW, exist_ok=True)
    lines = ['# Tasks\n']
    for t in tasks:
        lines.append(f"## {t['id']}")
        lines.append(f"- type: {t.get('type', 'once')}")
        lines.append(f"- due: {t['due']}")
        if 'every' in t:
            lines.append(f"- every: {t['every']}")
        lines.append(f"- task: {t['task']}")
        lines.append('')
    with open(TASKS_FILE, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def _parse_due(due_str):
    """Parse a due date string, accepting HH:MM or HH:MM:SS format."""
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
        try:
            return datetime.strptime(due_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse due date: {due_str}")


def _add_months(dt, months):
    """Add N calendar months to a datetime, clamping day to month end."""
    import calendar
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def compute_next_due(every_str, last_due_str):
    """Given an 'every' pattern and last due time, compute next due time string."""
    last_due = _parse_due(last_due_str)
    now = datetime.now()

    if every_str.startswith('daily '):
        time_part = every_str.split(' ', 1)[1]
        hour, minute = map(int, time_part.split(':'))
        next_due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if next_due <= now:
            next_due += timedelta(days=1)
        return next_due.strftime('%Y-%m-%d %H:%M:%S')

    # mo must come before m in the alternation to avoid partial match
    match = re.match(r'every\s+(\d+)(mo|[dhms])', every_str, re.IGNORECASE)
    if match:
        amount = int(match.group(1))
        unit = match.group(2).lower()
        if unit == 'h':
            delta = timedelta(hours=amount)
            next_due = last_due + delta
            while next_due <= now:
                next_due += delta
        elif unit == 'm':
            delta = timedelta(minutes=amount)
            next_due = last_due + delta
            while next_due <= now:
                next_due += delta
        elif unit == 's':
            delta = timedelta(seconds=amount)
            next_due = last_due + delta
            while next_due <= now:
                next_due += delta
        elif unit == 'd':
            delta = timedelta(days=amount)
            next_due = last_due + delta
            while next_due <= now:
                next_due += delta
        elif unit == 'mo':
            next_due = _add_months(last_due, amount)
            while next_due <= now:
                next_due = _add_months(next_due, amount)
        return next_due.strftime('%Y-%m-%d %H:%M:%S')

    return (last_due + timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')


async def reminder_check_loop(app):
    """Periodically check REMINDERS.md and fire due reminders."""
    while True:
        try:
            reminders = load_reminders()
            if reminders:
                now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                changed = False
                updated = []
                for r in reminders:
                    if r['due'] <= now_str:
                        target_id = int(ALLOWED_IDS[0]) if ALLOWED_IDS else None
                        if not target_id:
                            print("[Reminder] No ALLOWED_TELEGRAM_ID configured")
                            updated.append(r)
                            continue
                        try:
                            await app.bot.send_message(
                                chat_id=target_id,
                                text=f"\u23f0 Reminder: {r['message']}"
                            )
                            print(f"[Reminder] Fired: {r['message']} -> chat {target_id}")
                        except Exception as e:
                            print(f"[Reminder] Error sending to {target_id}: {e}")
                        if r.get('type') == 'recurring' and 'every' in r:
                            r['due'] = compute_next_due(r['every'], r['due'])
                            updated.append(r)
                            changed = True
                            print(f"[Reminder] Recurring, next due: {r['due']}")
                        else:
                            changed = True
                    else:
                        updated.append(r)
                if changed or len(updated) != len(reminders):
                    save_reminders(updated)
        except Exception as e:
            print(f"[Reminder] Check error: {e}")
        await asyncio.sleep(9)


async def _run_task(app, task):
    """Run a scheduled task: send task text to LLM, execute tool calls, send result to Telegram."""
    task_id = task['id']
    task_text = task['task']
    target_id = int(ALLOWED_IDS[0]) if ALLOWED_IDS else None
    if not target_id:
        print(f"[Tasks] No ALLOWED_TELEGRAM_ID configured, skipping task {task_id}")
        return

    print(f"[Tasks] Running: {task_id} — {task_text[:80]}")
    try:
        await app.bot.send_message(chat_id=target_id, text=f"\U0001f4cb Task: [{task_id}] {task_text[:200]}")
    except Exception as e:
        print(f"[Tasks] Error notifying task start: {e}")

    # Fresh isolated conversation — does not affect user's chat history
    messages = [
        {'role': 'developer', 'content': build_system_prompt()},
        {'role': 'user', 'content': task_text},
    ]

    for _ in range(MAX_COMMAND_ITERATIONS):
        try:
            messages[0]['content'] = build_system_prompt()
            comp_info = check_compression_needed(messages)
            if comp_info:
                print(f"[Tasks] Compressing {task_id} (~{comp_info['estimated']} tokens)")
                comp_result = await asyncio.get_event_loop().run_in_executor(None, do_compress, messages, comp_info)
                if 'error' in comp_result:
                    print(f"[Tasks] Compression failed: {comp_result['error']}")
                    return
                if comp_result.get('still_over'):
                    print(f"[Tasks] Still over token limit after compression — aborting task {task_id}")
                    return
            cleaned_output, raw_output, _ = await asyncio.get_event_loop().run_in_executor(
                None, call_llm, messages
            )

            native = extract_native_tool_call(raw_output)
            tool_name = None
            command = None

            if native:
                tool_name, args_json, command = native
                try:
                    tool_args = json.loads(args_json)
                except json.JSONDecodeError:
                    tool_args = {}
                analysis = extract_analysis(raw_output)
                assistant_msg = {
                    'role': 'assistant',
                    'tool_calls': [{'function': {'name': tool_name, 'arguments': args_json}}],
                }
                if analysis:
                    assistant_msg['thinking'] = analysis
                messages.append(assistant_msg)
            else:
                messages.append({'role': 'assistant', 'content': cleaned_output})

            if not native:
                # Final answer — send to user
                reply = f"\u2705 [{task_id}]\n{cleaned_output[:4000]}"
                try:
                    await app.bot.send_message(chat_id=target_id, text=reply)
                except Exception as e:
                    print(f"[Tasks] Error sending result: {e}")
                return

            # Execute tool call
            result = None
            if tool_name == 'bash' and command:
                try:
                    result = execute_command(command)
                except subprocess.TimeoutExpired:
                    result = "Command timed out after 60 seconds."
            elif tool_name == 'browse':
                url = tool_args.get('url', '')
                if url:
                    try:
                        result = await asyncio.get_event_loop().run_in_executor(None, browse_url, url)
                    except Exception as e:
                        result = f"Error: {e}"
                else:
                    result = "Error: no url provided"
            elif tool_name == 'strip_tags':
                file_path = tool_args.get('file_path', '')
                if file_path:
                    try:
                        result = strip_tags_from_file(file_path)
                    except Exception as e:
                        result = f"Error: {e}"
                else:
                    result = "Error: no file_path provided"
            else:
                available = ', '.join(t['function']['name'] for t in TOOLS)
                result = f"Error: unknown tool '{tool_name}'. Available: {available}"

            if result is None:
                result = "Error: could not execute tool call."

            # Truncate result
            if len(result) > MAX_TOOL_RESULT_CHARS:
                links_marker = "\n\n--- Links ---\n"
                if links_marker in result:
                    body, raw_links = result.split(links_marker, 1)
                    filtered = filter_links(raw_links.strip().split("\n"))
                    links_section = links_marker + "\n".join(filtered)
                    body_budget = MAX_TOOL_RESULT_CHARS - len(links_section)
                    body = body[:max(body_budget, 200)]
                    result = body + links_section
                else:
                    result = result[:MAX_TOOL_RESULT_CHARS]

            messages.append({'role': 'tool', 'content': result, 'useful': True})

        except Exception as e:
            print(f"[Tasks] Error running {task_id}: {e}")
            try:
                await app.bot.send_message(chat_id=target_id, text=f"[{task_id}] Error: {e}")
            except Exception:
                pass
            return

    # Max iterations reached
    try:
        await app.bot.send_message(chat_id=target_id, text=f"[{task_id}] Reached max iterations.")
    except Exception:
        pass


async def task_check_loop(app):
    """Periodically check TASKS.md and run due tasks."""
    while True:
        try:
            tasks = load_tasks()
            if tasks:
                now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                changed = False
                updated = []
                for t in tasks:
                    if t['due'] <= now_str:
                        asyncio.create_task(_run_task(app, t))
                        if t.get('type') == 'recurring' and 'every' in t:
                            t['due'] = compute_next_due(t['every'], t['due'])
                            updated.append(t)
                            changed = True
                            print(f"[Tasks] Recurring {t['id']}, next due: {t['due']}")
                        else:
                            changed = True
                            print(f"[Tasks] One-shot {t['id']} fired, removing.")
                    else:
                        updated.append(t)
                if changed or len(updated) != len(tasks):
                    save_tasks(updated)
        except Exception as e:
            print(f"[Tasks] Check error: {e}")
        await asyncio.sleep(9)


# File loggers for full message details
os.makedirs(_CALMCLAW, exist_ok=True)
logger = logging.getLogger('calmclaw')
logger.setLevel(logging.DEBUG)
# Plain text log
_fh_plain = logging.FileHandler(os.path.join(_CALMCLAW, 'conversation.log'), encoding='utf-8')
_fh_plain.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
logger.addHandler(_fh_plain)
# Colored log (ANSI escapes — view with: tail -f conversation_color.log)
color_logger = logging.getLogger('calmclaw.color')
color_logger.setLevel(logging.DEBUG)
_fh_color = logging.FileHandler(os.path.join(_CALMCLAW, 'conversation_color.log'), encoding='utf-8')
_fh_color.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
color_logger.addHandler(_fh_color)
color_logger.propagate = False

_startup_msg = f"=== CalmClaw started ==="
logger.debug(_startup_msg)
color_logger.debug(_startup_msg)

# ANSI color codes for roles
ROLE_COLORS = {
    'developer': '\033[36m',  # cyan
    'system':    '\033[36m',  # cyan
    'user':      '\033[32m',  # green
    'assistant': '\033[33m',  # yellow
    'tool':      '\033[35m',  # magenta
}
ROLE_COLORS_RAW = {
    'assistant': '\033[93m',  # light yellow
}
RESET_COLOR = '\033[0m'

SOUL_FILE = os.path.join(_CALMCLAW, 'SOUL.md')
SYSTEM_RULES_FILE = os.path.join(_CALMCLAW, 'SYSTEM_RULES.md')
SYSTEM_INSERT_FILE = os.path.join(_CALMCLAW, 'SYSTEM_INSERT.sh')
COMPRESSION_PROMPT_FILE = os.path.join(_CALMCLAW, 'COMPRESSION_RULES.md')

def load_compression_prompt():
    with open(COMPRESSION_PROMPT_FILE, 'r', encoding='utf-8') as f:
        return f.read().strip()

def load_system_rules():
    """Load SOUL.md + SYSTEM_RULES.md from ~/.calmclaw/."""
    parts = []
    for path in (SOUL_FILE, SYSTEM_RULES_FILE):
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                parts.append(f.read().strip())
    text = '\n\n'.join(parts)
    text = text.replace('$CALMCLAW_DIR', _CALMCLAW)
    if '$SYSTEM_INSERT' in text:
        insert = ''
        if os.path.exists(SYSTEM_INSERT_FILE):
            try:
                insert = subprocess.check_output(
                    ['bash', SYSTEM_INSERT_FILE], text=True
                ).strip()
            except Exception:
                pass
        text = text.replace('$SYSTEM_INSERT', insert)
    return text

TOOLS = [
    {
        'type': 'function',
        'function': {
            'name': 'bash',
            'description': 'Execute a shell command on macOS and return the output.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'command': {
                        'type': 'string',
                        'description': 'The shell command to execute, e.g. "ls ~/Desktop"',
                    }
                },
                'required': ['command'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'strip_tags',
            'description': 'Read a downloaded HTML file and return its text content with all HTML tags removed.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'file_path': {
                        'type': 'string',
                        'description': 'Path to the HTML file to strip tags from, e.g. "~/Desktop/page.html"',
                    }
                },
                'required': ['file_path'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'browse',
            'description': 'Load a URL in a browser and return the page text content. Use this instead of curl for web pages.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'url': {
                        'type': 'string',
                        'description': 'The URL to load, e.g. "https://grokipedia.com/page/Switzerland"',
                    }
                },
                'required': ['url'],
            },
        },
    },
    # {
    #     'type': 'function',
    #     'function': {
    #         'name': 'web_search',
    #         'description': 'Search the web and return results with titles, URLs, and snippets.',
    #         'parameters': {
    #             'type': 'object',
    #             'properties': {
    #                 'query': {
    #                     'type': 'string',
    #                     'description': 'The search query, e.g. "population of France"',
    #                 }
    #             },
    #             'required': ['query'],
    #         },
    #     },
    # },
    # {
    #     'type': 'function',
    #     'function': {
    #         'name': 'headless_browse',
    #         'description': 'Load a URL in a headless browser and return the page text content. May get blocked by anti-bot sites. Prefer browse instead.',
    #         'parameters': {
    #             'type': 'object',
    #             'properties': {
    #                 'url': {
    #                     'type': 'string',
    #                     'description': 'The URL to load, e.g. "https://en.wikipedia.org/wiki/France"',
    #                 }
    #             },
    #             'required': ['url'],
    #         },
    #     },
    # }
]


mlx_process = None
# Per-user conversation history: user_id -> list of messages (sent to LLM)
conversations = {}
# Per-user enriched message history with metadata (for compression/analysis)
message_history = {}
# Per-user counters: user_id -> {'req': int, 'msg': int}
user_counters = {}

STATE_FILE = os.path.join(_CALMCLAW, 'state.json')


def save_state():
    """Write all per-user state to disk."""
    data = {
        'conversations': conversations,
        'message_history': message_history,
        'user_counters': user_counters,
    }
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)


def load_state():
    """Load per-user state from disk on startup."""
    global conversations, message_history, user_counters, _req_counter
    if not os.path.exists(STATE_FILE):
        return
    with open(STATE_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    conversations = data.get('conversations', {})
    message_history = data.get('message_history', {})
    user_counters = data.get('user_counters', {})
    # Resume global log counter from where we left off
    if user_counters:
        _req_counter = max(uc['req'] for uc in user_counters.values())



def execute_command(command):
    result = subprocess.run(
        ['/bin/zsh', '-c', command], capture_output=True, timeout=60
    )
    stdout = result.stdout.decode('utf-8', errors='replace') if result.stdout else ''
    stderr = result.stderr.decode('utf-8', errors='replace') if result.stderr else ''
    return (stdout or stderr or "Command executed with no output.").strip()


class _TagStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        self._skip = tag in ('script', 'style')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            self._parts.append(data)

    def get_text(self):
        text = ' '.join(self._parts)
        return re.sub(r'\s+', ' ', text).strip()


def strip_tags_from_file(file_path):
    path = os.path.expanduser(file_path)
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        html = f.read()
    stripper = _TagStripper()
    stripper.feed(html)
    return stripper.get_text() or "No text content found."


# Domains to skip when extracting links (Google navigation junk)
SKIP_DOMAINS = {
    'accounts.google.com', 'support.google.com', 'policies.google.com',
    'maps.google.com', 'mail.google.com', 'play.google.com',
    'myaccount.google.com', 'consent.google.com',
}
MAX_LINKS = 15


def dedup_links(links):
    """Deduplicate links and format as markdown."""
    seen = set()
    result = []
    for text, href in links:
        if not text or href in seen:
            continue
        seen.add(href)
        result.append(f"[{text[:80]}]({href})")
    return result


def filter_links(link_lines):
    """Filter junk navigation links and cap at MAX_LINKS for LLM input."""
    filtered = []
    for line in link_lines:
        # Extract URL from markdown link format [text](url)
        m = re.match(r'\[.*?\]\((.+?)\)', line)
        if not m:
            filtered.append(line)
            continue
        href = m.group(1)
        parsed = urlparse(href)
        domain = parsed.hostname or ''
        if domain in SKIP_DOMAINS:
            continue
        if domain == 'www.google.com' and parsed.path.startswith(('/search', '/preferences', '/advanced_search')):
            continue
        filtered.append(line)
        if len(filtered) >= MAX_LINKS:
            break
    return filtered


def headless_browse_url(url):
    """Load a URL with headless Playwright and return the page text content + links."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, timeout=30000)
        text = page.inner_text('body')
        links = page.eval_on_selector_all(
            'a[href]',
            '(els) => els.map(e => [e.innerText.trim(), e.href]).filter(([t, h]) => t && h && !h.startsWith("javascript:"))'
        )
        browser.close()
    text = re.sub(r'\s+', ' ', text).strip()
    if links:
        unique = dedup_links(links)
        if unique:
            text += "\n\n--- Links ---\n" + "\n".join(unique)
    return text or "No text content found."


def browse_url(url):
    """Load a URL in real Chrome via CDP and return page text + links."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://localhost:{CDP_PORT}")
        context = browser.contexts[0]
        page = context.new_page()
        page.goto(url, timeout=30000, wait_until='domcontentloaded')
        text = page.inner_text('body')
        links = page.eval_on_selector_all(
            'a[href]',
            '(els) => els.map(e => [e.innerText.trim(), e.href]).filter(([t, h]) => t && h && !h.startsWith("javascript:"))'
        )
        page.close()
    text = re.sub(r'\s+', ' ', text).strip()
    if links:
        unique = dedup_links(links)
        if unique:
            text += "\n\n--- Links ---\n" + "\n".join(unique)
    return text or "No text content found."


def web_search(query, max_results=5):
    """Search the web using DuckDuckGo and return formatted results."""
    from ddgs import DDGS
    results = DDGS().text(query, max_results=max_results)
    if not results:
        return "No results found."
    parts = []
    for i, r in enumerate(results, 1):
        parts.append(f"{i}. {r['title']}\n   {r['href']}\n   {r['body']}")
    return "\n\n".join(parts)


def extract_native_tool_call(text):
    """Extract tool call from gpt-oss native format in raw output.
    Returns (tool_name, arguments_json, command_string) or None."""
    name_match = re.search(r'to=functions\.(\w[\w.]*)', text)
    json_match = re.search(r'<\|message\|>\s*(\{.+)', text, re.DOTALL)
    # Fallback: malformed format where JSON immediately follows the tool name (e.g. to=functions.browse}{"url":...})
    if name_match and not json_match:
        json_match = re.search(r'\}\s*(\{.+)', text[name_match.end():], re.DOTALL)
    # Fallback: tool name found but args are raw text (not JSON)
    if name_match and not json_match:
        tool_name = name_match.group(1)
        # Search AFTER the to=functions marker to skip analysis <|message|> tags
        after_tool = text[name_match.end():]
        raw_match = re.search(r'<\|message\|>\s*(.+)', after_tool, re.DOTALL)
        if raw_match and tool_name == 'bash':
            command = raw_match.group(1).strip()
            # Strip trailing malformed JSON wrapper artifacts
            command = re.sub(r'["\s}]+$', '', command)
            # Convert literal \n to real newlines (needed for heredocs)
            command = command.replace('\\n', '\n').replace('\\"', '"')
            args_json = json.dumps({'command': command})
            return tool_name, args_json, command
    if name_match and json_match:
        tool_name = name_match.group(1)
        args_json = json_match.group(1).strip()
        # Parse the JSON properly to handle escaped quotes etc.
        command = None
        try:
            args = json.loads(args_json)
            command = args.get('command')
            # Fallback: old cmd array format ["bash", "-lc", "actual command"]
            if not command and 'cmd' in args:
                cmd_val = args['cmd']
                if isinstance(cmd_val, list) and len(cmd_val) >= 3 and cmd_val[0] == 'bash' and cmd_val[1] == '-lc':
                    command = cmd_val[2]
                elif isinstance(cmd_val, str):
                    # Model sent cmd as string instead of array
                    command = re.sub(r'^bash\s+-lc\s+', '', cmd_val).strip().strip('"\'')
        except json.JSONDecodeError:
            # JSON malformed — try regex fallback to extract command
            # Pattern 1: "command":"..."
            m = re.search(r'"command"\s*:\s*"((?:[^"\\]|\\.)*)"', args_json)
            if m:
                command = m.group(1)
            else:
                # Pattern 2: "cmd":"bash -lc \"...\""  (cmd as string)
                m = re.search(r'"cmd"\s*:\s*"((?:[^"\\]|\\.)*)"', args_json)
                if m:
                    command = re.sub(r'^bash\s+-lc\s+', '', m.group(1)).strip().strip('"\'')
                else:
                    # Pattern 3: "cmd":["bash","-lc","..."]  (array but broken JSON)
                    m = re.search(r'"bash"\s*,\s*"-lc"\s*,\s*"((?:[^"\\]|\\.)*)"', args_json)
                    if m:
                        command = m.group(1)
            if command:
                command = command.replace('\\n', '\n').replace('\\"', '"').replace('\\\\', '\\')
        # Always re-serialize so args_json is clean valid JSON (model output may have
        # literal newlines or other control chars that the MLX server rejects when it
        # tries to parse the arguments field as JSON).
        if command:
            args_json = json.dumps({'command': command})
        return tool_name, args_json, command
    return None


def extract_analysis(text):
    """Extract analysis/thinking text from gpt-oss raw output."""
    match = re.search(r'<\|channel\|>analysis<\|message\|>(.*?)(?:<\|end\|>|$)', text, re.DOTALL)
    return match.group(1).strip() if match else None


def flatten_messages_to_prompt(messages):
    """Concatenate messages array into a single prompt string for legacy /chat endpoint."""
    parts = []
    for m in messages:
        if m['role'] in ('developer', 'system'):
            parts.append(m['content'])
        elif m['role'] == 'user':
            parts.append(m['content'])
        elif m['role'] == 'assistant':
            parts.append(f"[Assistant]: {m['content']}")
    return "\n\n".join(parts)



def clean_llm_output(text):
    """Strip special tokens, thinking blocks, and analysis channels from raw LLM output."""
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
    if '<|channel|>final' in text:
        text = re.sub(r'.*<\|channel\|>final<\|message\|>', '', text, flags=re.DOTALL).strip()
    elif '<|channel|>analysis' in text:
        text = re.sub(r'<\|channel\|>analysis<\|message\|>', '', text).strip()
    text = re.sub(r'<\|(?:end|start|assistant|user|channel|message)\|>', '', text).strip()
    text = re.sub(r'assistant(?:commentary)?\s*(?:to=\w+)?', '', text).strip()
    return text


def estimate_tokens(messages):
    """Estimate token count using CHARS_PER_TOKEN heuristic."""
    total = 0
    for m in messages:
        chars = ((len(m['content']) if m.get('content') else 0)
                 + (len(json.dumps(m['tool_calls'])) if 'tool_calls' in m else 0)
                 + (len(m['thinking']) if 'thinking' in m else 0))
        total += int(chars / CHARS_PER_TOKEN)
    return total


def check_compression_needed(messages, force=False, req_label=None):
    """Check if compression is needed. Returns pre-compression info dict or None.
    Pass force=True to build the info dict regardless of the token limit."""
    estimated = estimate_tokens(messages)
    if not force and estimated <= MAX_TOKEN_INPUT_TO_LLM:
        return None

    # Determine how many messages to keep at the tail.
    # If the last message is a 'tool' result, also keep its preceding 'assistant' (with tool_calls).
    tail_count = 1
    if len(messages) >= 4 and messages[-1]['role'] == 'tool':
        for i in range(len(messages) - 2, 1, -1):
            if messages[i]['role'] == 'assistant' and 'tool_calls' in messages[i]:
                tail_count = len(messages) - i
                break

    middle = messages[2:-tail_count]
    if not middle:
        return None

    total = len(messages)
    kept_ids = list(range(1, 3))
    compressed_ids = list(range(3, total - tail_count + 1))
    latest_ids = list(range(total - tail_count + 1, total + 1))

    kept_tokens = estimate_tokens(messages[:2])
    middle_tokens = estimate_tokens(middle)
    latest_tokens = estimate_tokens(messages[-tail_count:])

    # Log compression start with per-message breakdown
    last_two_start = max(1, total - 2)
    _rlabel = req_label if req_label is not None else _req_counter
    _ga_max_cap = int(MAX_TOKEN_INPUT_TO_LLM * GA_CAP_FACTOR)
    reason = ("manually requested" if force
              else f"conversation exceeds limit (~{estimated}t > {MAX_TOKEN_INPUT_TO_LLM}t)")
    lines = [
        f"=== INTERNAL (Req#{_rlabel}) === COMPRESSION START",
        f"  Reason  : {reason}  [MAX_TOKEN_INPUT_TO_LLM={MAX_TOKEN_INPUT_TO_LLM}]",
        f"  State   : {len(messages)} messages, ~{estimated}t total",
        f"  Goal    : reduce to fit within {MAX_TOKEN_INPUT_TO_LLM}t  [MAX_TOKEN_INPUT_TO_LLM]",
        f"  GA cap  : {_ga_max_cap}t  [MAX_TOKEN_INPUT_TO_LLM * GA_CAP_FACTOR={GA_CAP_FACTOR}]",
        f"  Messages:",
        f"    {'Idx':<4}  {'Role':<12}  {'Tokens':>6}  Constraint",
        f"    {'----':<4}  {'------------':<12}  {'------':>6}  --------------------",
    ]
    _constraint_colors = {'keep': '\033[32m', 'keep|compress': '\033[33m', 'keep|compress|throw': '\033[31m'}
    color_lines = list(lines)
    for idx, m in enumerate(messages):
        tokens = int(((len(m['content']) if m.get('content') else 0)
                      + (len(json.dumps(m['tool_calls'])) if 'tool_calls' in m else 0)
                      + (len(m['thinking']) if 'thinking' in m else 0)) / CHARS_PER_TOKEN)
        if idx == 0:
            constraint = 'keep'
        elif idx == 1 or idx >= last_two_start or (m['role'] == 'tool' and m.get('useful')):
            constraint = 'keep|compress'
        else:
            constraint = 'keep|compress|throw'
        lines.append(f"    [{idx:>2}] {m['role']:<12} {tokens:>4}t  [{constraint}]")
        tok_c = _constraint_colors[constraint]
        color_lines.append(f"    [{idx:>2}] {m['role']:<12} {tok_c}{tokens:>4}t{RESET_COLOR}  [{constraint}]")
    header = '\n'.join(lines)
    logger.debug(header)
    color_logger.debug('\n'.join(color_lines))
    print(header)

    return {
        'estimated': estimated, 'tail_count': tail_count,
        'kept_ids': kept_ids, 'compressed_ids': compressed_ids, 'latest_ids': latest_ids,
        'kept_tokens': kept_tokens, 'middle_tokens': middle_tokens, 'latest_tokens': latest_tokens,
        'num_middle': len(middle), 'req_label': _rlabel,
    }


def _call_summary_llm(text: str, max_tokens: int = MAX_TOKEN_COMPRESSION_SUMMARY) -> str:
    """Summarise `text` via the compression LLM. Returns cleaned summary or raises."""
    max_chars = max(100, int(max_tokens * CHARS_PER_TOKEN))
    system_prompt = load_compression_prompt().replace('$max_chars', str(max_chars))
    prompt = [
        {'role': 'developer', 'content': system_prompt},
        {'role': 'user',      'content': text},
    ]
    if 'chat/completions' in ENDPOINT_SUFFIX:
        body = {'model': MODEL_PATH, 'messages': prompt,
                'max_tokens': SUMMARY_MAX_TOKENS,
                'chat_template_kwargs': {'reasoning_effort': SUMMARY_REASONING_EFFORT}}
    else:
        body = {'model': MODEL_PATH,
                'prompt': flatten_messages_to_prompt(prompt),
                'max_tokens': max_tokens}
    _sum_prompt_log = (
        f"=== SUMMARY LLM === PROMPT\n"
        f"  [system] {system_prompt}\n"
        f"  [user]   {text}"
    )
    logger.debug(_sum_prompt_log); color_logger.debug(_sum_prompt_log); print(_sum_prompt_log)
    _sum_wait = f"=== SUMMARY LLM === waiting for response... (max_tokens={body['max_tokens']})"
    logger.debug(_sum_wait); color_logger.debug(_sum_wait); print(_sum_wait)

    response = requests.post(
        f"http://localhost:{MLX_PORT}/{ENDPOINT_SUFFIX}", json=body, timeout=120)
    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}")
    data = response.json()
    if 'choices' in data and data['choices']:
        raw = data['choices'][0]['message']['content'].strip()
    elif 'text' in data:
        raw = data['text'].strip()
    else:
        raise RuntimeError("unexpected response format")
    summary = clean_llm_output(raw)
    # If clean_llm_output discarded everything (e.g. analysis content + empty final channel),
    # fall back to the analysis block, then to the raw text.
    if not summary:
        summary = extract_analysis(raw) or raw.strip()
    alnum = sum(1 for c in summary if c.isalnum())
    if not summary or (len(summary) > 20 and alnum / len(summary) < 0.15):
        raise RuntimeError(
            f"LLM produced garbage summary (alnum={alnum}, len={len(summary)}): "
            f"{repr(summary[:200])}"
        )
    return summary


def _extract_text_from_group(msgs: list) -> str:
    """Convert a list of messages (any mix of roles) into a plain-text block for the summariser."""
    parts = []
    for m in msgs:
        role = m['role']
        if role == 'user':
            parts.append(f"User: {clean_llm_output(m.get('content', ''))}")
        elif role == 'assistant':
            if 'tool_calls' in m:
                for tc in m['tool_calls']:
                    try:
                        args = json.loads(tc['function']['arguments'])
                        cmd = args.get('command', str(args))
                    except (json.JSONDecodeError, KeyError):
                        cmd = tc['function'].get('arguments', '')
                    parts.append(f"Assistant ran: {cmd}")
            elif m.get('content'):
                parts.append(f"Assistant: {clean_llm_output(m['content'])}")
        elif role == 'tool':
            parts.append(f"Tool result: {m.get('content', '')}")
    return "\n---\n".join(parts)


def do_compress(messages, info):
    """Perform the actual compression via LLM summarization. Modifies messages in-place.
    Returns post-compression result dict."""
    _rlabel    = info.get('req_label', _req_counter)
    tail_count = info['tail_count']

    # --- GA: decide Keep / Compress / Throw for every message ---
    _roles     = [m['role'] for m in messages]
    _weights   = [
        int(((len(m['content']) if m.get('content') else 0)
             + (len(json.dumps(m['tool_calls'])) if 'tool_calls' in m else 0)
             + (len(m['thinking']) if 'thinking' in m else 0)) / CHARS_PER_TOKEN)
        for m in messages
    ]
    _important = [m.get('useful') if m['role'] == 'tool' else None for m in messages]
    n            = len(messages)
    last_two_start = max(1, n - 2)           # last min(2, n-1) messages — never index 0
    _constraints = []
    for i, m in enumerate(messages):
        if i == 0:
            c = 0                            # system: Keep only
        elif i >= last_two_start:
            c = 1                            # last 2 (or 1 if only 1): Keep or Compress
        elif i == 1:
            c = 1                            # first user: Keep or Compress
        elif m['role'] == 'tool' and m.get('useful'):
            c = 1                            # important tool: no Throw
        else:
            c = 2                            # everything else: any decision
        if _weights[i] < MIN_COMPRESS_GROUP_TOKENS:
            c = 0                            # too small to compress: Keep only
        _constraints.append(c)
    _ga_max_cap = int(MAX_TOKEN_INPUT_TO_LLM * GA_CAP_FACTOR)
    decisions, ga_feasible, _eff_w = run_compression_planner(_roles, _weights, _important,
                                             constraints=_constraints,
                                             max_cap=_ga_max_cap,
                                             min_compress_group_tokens=MIN_COMPRESS_GROUP_TOKENS)
    decisions = list(decisions)
    _cl_labels = {0: 'keep', 1: 'keep|compress', 2: 'keep|compress|throw'}
    _ga_status = 'feasible' if ga_feasible else f'INFEASIBLE — {_eff_w - _ga_max_cap:.1f}t over cap'
    _dec_colors = {'Keep': '\033[32m', 'Compress': '\033[33m', 'Throw': '\033[31m'}
    _ga_lines  = [
        f"=== INTERNAL (Req#{_rlabel}) === GA solution: eff={_eff_w:.1f}t / cap={_ga_max_cap}t ({_ga_status})",
        f"  Messages:",
        f"    {'Idx':<4}  {'Role':<12}  {'Tokens':>6}  {'Decision':<8}  Constraint",
        f"    {'----':<4}  {'------------':<12}  {'------':>6}  {'--------':<8}  --------------------",
    ]
    _ga_color_lines = list(_ga_lines)
    for i, (d, w, c) in enumerate(zip(decisions, _weights, _constraints)):
        role = messages[i]['role']
        _ga_lines.append(f"    [{i:2d}] {role:<12} {w:>4}t  {d:<8}  [{_cl_labels[c]}]")
        tok_c = _dec_colors.get(d, '')
        _ga_color_lines.append(f"    [{i:2d}] {role:<12} {tok_c}{w:>4}t{RESET_COLOR}  {d:<8}  [{_cl_labels[c]}]")
    _ga_log = '\n'.join(_ga_lines)
    logger.debug(_ga_log); color_logger.debug('\n'.join(_ga_color_lines)); print(_ga_log)

    _comp_waiting_msg = f"=== INTERNAL (Req#{_rlabel}) === executing compression plan..."
    logger.debug(_comp_waiting_msg); color_logger.debug(_comp_waiting_msg); print(_comp_waiting_msg)

    if not ga_feasible:
        over_by = _eff_w - _ga_max_cap
        fb_lines = [
            f"=== INTERNAL (Req#{_rlabel}) === GA FALLBACK",
            f"  The GA could not find a feasible solution within its budget.",
            f"  Effective weight of best solution: {_eff_w:.1f}t — exceeds GA cap {_ga_max_cap}t by {over_by:.1f}t  [MAX_TOKEN_INPUT_TO_LLM].",
            f"  Strategy: throw [keep|compress|throw] messages one by one until total fits within {MAX_TOKEN_INPUT_TO_LLM}t  [MAX_TOKEN_INPUT_TO_LLM].",
        ]

        unconstrained = [i for i, c in enumerate(_constraints) if c == 2]
        resolved = False
        for step, idx in enumerate(unconstrained, 1):
            decisions[idx] = 'Throw'
            est = sum(w for w, d in zip(_weights, decisions) if d != 'Throw')
            role = _roles[idx]
            fb_lines.append(
                f"  Step {step}: throw [{idx}] {role} ({_weights[idx]}t) → est {est}t"
                + (f" ≤ {MAX_TOKEN_INPUT_TO_LLM}t — resolved  [MAX_TOKEN_INPUT_TO_LLM]" if est <= MAX_TOKEN_INPUT_TO_LLM else f" > {MAX_TOKEN_INPUT_TO_LLM}t — still over")
            )
            if est <= MAX_TOKEN_INPUT_TO_LLM:
                resolved = True
                break

        fb_log = '\n'.join(fb_lines)
        logger.debug(fb_log); color_logger.debug(fb_log); print(fb_log)

        if not resolved:
            fail_lines = [
                f"=== INTERNAL (Req#{_rlabel}) === FALLBACK FAILED",
                f"  Threw all {len(unconstrained)} unconstrained messages — still over {MAX_TOKEN_INPUT_TO_LLM}t  [MAX_TOKEN_INPUT_TO_LLM].",
                f"  Cannot compress further. Aborting.",
            ]
            fail_log = '\n'.join(fail_lines)
            logger.debug(fail_log); color_logger.debug(fail_log); print(fail_log)
            return {'error': 'Cannot fit within token limit even after maximum compression. Please /reset.'}

    thrown_count = decisions.count('Throw')

    # Snapshot per-message decision detail before messages are reconstructed
    _decision_rows = []
    for idx, (m, d, w) in enumerate(zip(messages, decisions, _weights)):
        _decision_rows.append((idx, m['role'], w, d))

    # Step 1: remove Throw messages, preserving original indices
    remaining = [(orig_i, m, d)
                 for orig_i, (m, d) in enumerate(zip(messages, decisions))
                 if d != 'Throw']

    # Step 2: build groups of consecutive same-decision messages (all decisions, including Throw)
    groups = []
    all_indexed = list(enumerate(decisions))
    i = 0
    while i < len(all_indexed):
        orig_i, d = all_indexed[i]
        group_indices = []
        while i < len(all_indexed) and all_indexed[i][1] == d:
            group_indices.append(all_indexed[i][0])
            i += 1
        groups.append({
            'indices':          group_indices,
            'type':             d,
            'total_est_tokens': sum(_weights[idx] for idx in group_indices),
        })

    keep_groups     = [g for g in groups if g['type'] == 'Keep']
    compress_groups = [g for g in groups if g['type'] == 'Compress']
    compress_count  = sum(len(g['indices']) for g in compress_groups)

    # Step 3: distribute token budget among compress groups
    _SUMMARY_PREFIX = '[Summary of previous messages]\n'
    _ACK_TEXT       = 'Previous messages summarized.'
    tokens_for_keep = sum(g['total_est_tokens'] for g in keep_groups)
    tokens_per_ack  = int(len(_ACK_TEXT) / CHARS_PER_TOKEN) + 1
    tokens_per_pfx  = int(len(_SUMMARY_PREFIX) / CHARS_PER_TOKEN) + 1
    tokens_for_compressed_text = max(50, (
        MAX_TOKEN_INPUT_TO_LLM
        - tokens_for_keep
        - len(compress_groups) * (tokens_per_ack + tokens_per_pfx)
    ))
    total_compress_src = sum(g['total_est_tokens'] for g in compress_groups) or 1
    for g in compress_groups:
        g['max_summary_tokens'] = max(50, int(
            tokens_for_compressed_text * g['total_est_tokens'] / total_compress_src
        ))

    # Log execution plan
    _pt_colors = {'Keep': '\033[32m', 'Compress': '\033[33m', 'Throw': '\033[31m'}
    _ptok_colors = {'Keep': '\033[2;32m', 'Compress': '\033[33m', 'Throw': '\033[31m'}
    _plan_lines       = [
        f"=== INTERNAL (Req#{_rlabel}) === COMPRESSION PLAN",
        f"  {'Grp':<4}  {'Type':<8}  {'Idx':<4}  {'Role':<12}  {'Tokens':>6}  {'Action':<8}  {'PlanRed':>7}  Budget",
        f"  {'----':<4}  {'--------':<8}  {'----':<4}  {'------------':<12}  {'------':>6}  {'--------':<8}  {'-------':>7}  --------------------",
    ]
    _plan_color_lines = list(_plan_lines)
    for g_idx, g in enumerate(groups):
        _type  = g['type']
        _max_t = g.get('max_summary_tokens')
        _max_w = max(100, int(_max_t * CHARS_PER_TOKEN)) if _max_t else None
        _tc    = _pt_colors.get(_type, '')
        _tokc  = _ptok_colors.get(_type, '')
        _gtok  = g['total_est_tokens']
        if _type == 'Compress':
            _pa = 'skip' if _gtok < MIN_COMPRESS_GROUP_TOKENS else 'compress'
            _plan_red = 0 if _pa == 'skip' else _gtok - (_max_t or _gtok)
        elif _type == 'Throw':
            _pa = '-'
            _plan_red = _gtok
        else:
            _pa = '-'
            _plan_red = 0
        for row_i, idx in enumerate(g['indices']):
            _role    = messages[idx]['role']
            _tok     = _weights[idx]
            _g_str   = f"g{g_idx}" if row_i == 0 else "|"
            _typ_str = _type       if row_i == 0 else "|"
            _pa_str  = _pa         if row_i == 0 else ""
            _planred_str = f"{_plan_red:>6}t" if row_i == 0 else f"{'':>7}"
            _budget  = f"  max_chars={_max_w} max_tokens={_max_t}" if (row_i == 0 and _max_t) else ""
            _plain = f"  {_g_str:<4} {_typ_str:<8}  [{idx:>2}] {_role:<12} {_tok:>4}t  {_pa_str:<8}  {_planred_str}{_budget}"
            _color = (f"  {_g_str:<4} {_tc if row_i == 0 else ''}{_typ_str:<8}"
                      f"{RESET_COLOR if row_i == 0 else ''}  [{idx:>2}] {_role:<12} {_tokc}{_tok:>4}t{RESET_COLOR}  {_pa_str:<8}  {_planred_str}{_budget}")
            _plan_lines.append(_plain)
            _plan_color_lines.append(_color)
    _plan_log = '\n'.join(_plan_lines)
    logger.debug(_plan_log); color_logger.debug('\n'.join(_plan_color_lines)); print(_plan_log)

    # Step 4: build new_message_list
    new_message_list = []
    error = None
    summary_msgs = []
    compress_g_summary_tokens = {}  # g_idx -> tokens after compression (skipped=before, summarized=summary)

    try:
        for g_idx, g in enumerate(groups):
            if g['type'] == 'Keep':
                for idx in g['indices']:
                    new_message_list.append(messages[idx])
            elif g['type'] == 'Throw':
                continue  # already excluded; nothing to add
            else:  # Compress
                group_msgs = [messages[idx] for idx in g['indices']]
                if g['total_est_tokens'] < MIN_COMPRESS_GROUP_TOKENS:
                    _skip_msg = (f"=== INTERNAL (Req#{_rlabel}) === SKIP SUMMARIZING group g{g_idx}"
                                 f" ({g['total_est_tokens']}t < MIN_COMPRESS_GROUP_TOKENS={MIN_COMPRESS_GROUP_TOKENS}t) — keeping as-is")
                    logger.debug(_skip_msg); color_logger.debug(_skip_msg); print(_skip_msg)
                    for idx in g['indices']:
                        new_message_list.append(messages[idx])
                    compress_g_summary_tokens[g_idx] = g['total_est_tokens']  # unchanged
                    continue
                _max_t     = g['max_summary_tokens']
                _max_chars = max(100, int(_max_t * CHARS_PER_TOKEN))
                _llm_max_t = SUMMARY_MAX_TOKENS
                _sum_pre = (
                    f"=== INTERNAL (Req#{_rlabel}) === SUMMARIZING group g{g_idx}\n"
                    f"  Messages : {', '.join(f'[{idx}]({_weights[idx]}t)' for idx in g['indices'])}\n"
                    f"  Total    : {g['total_est_tokens']}t\n"
                    f"  max_chars: {_max_chars}  max_tokens (content): {_max_t}  max_tokens (LLM): {_llm_max_t}"
                )
                logger.debug(_sum_pre); color_logger.debug(_sum_pre); print(_sum_pre)
                text       = _extract_text_from_group(group_msgs)
                summary    = _call_summary_llm(text, _max_t)
                raw_msg = (f"=== INTERNAL (Req#{_rlabel}) === "
                           f"COMPRESSION RAW SUMMARY ({_max_t}t budget): "
                           f"{summary}")
                logger.debug(raw_msg)
                color_logger.debug(raw_msg)
                print(raw_msg)
                asst_msg = {'role': 'assistant',
                            'content': f'{_SUMMARY_PREFIX}{summary}'}
                user_ack = {'role': 'user', 'content': _ACK_TEXT}
                new_message_list.append(asst_msg)
                new_message_list.append(user_ack)
                summary_msgs.extend([asst_msg, user_ack])
                compress_g_summary_tokens[g_idx] = estimate_tokens([asst_msg, user_ack])
    except Exception as e:
        error = str(e)

    if error:
        fail_msg = (f"=== INTERNAL (Req#{_rlabel}) === "
                    f"COMPRESSION FAILED: {error}")
        logger.debug(fail_msg)
        color_logger.debug(fail_msg)
        print(fail_msg)
        return {'error': error}

    # Post-step: convert orphaned tool messages to user messages
    for i in range(len(new_message_list)):
        if new_message_list[i]['role'] == 'tool':
            prev = new_message_list[i - 1] if i > 0 else None
            if prev is None or prev.get('role') != 'assistant' or 'tool_calls' not in prev:
                msg = new_message_list[i]
                new_message_list[i] = {'role': 'user', 'content': msg.get('content', '')}

    # Step 5: replace messages in-place
    del messages[:]
    messages.extend(new_message_list)

    # Step 6: compute metrics
    new_estimated  = estimate_tokens(messages)
    keep_count     = sum(len(g['indices']) for g in keep_groups)
    summary_tokens = estimate_tokens(summary_msgs)
    kept_tokens    = estimate_tokens(messages[:2])
    last_tokens    = estimate_tokens(messages[-tail_count:])

    # Build per-message lookup tables for the done log
    idx_to_group_idx = {}
    for g_idx, g in enumerate(groups):
        for orig_idx in g['indices']:
            idx_to_group_idx[orig_idx] = g_idx

    _constraint_labels = {0: 'keep', 1: 'keep|compress', 2: 'keep|compress|throw'}

    fit_status = (f"fits within {MAX_TOKEN_INPUT_TO_LLM}t  [MAX_TOKEN_INPUT_TO_LLM]"
                  if new_estimated <= MAX_TOKEN_INPUT_TO_LLM
                  else f"STILL OVER {MAX_TOKEN_INPUT_TO_LLM}t  [MAX_TOKEN_INPUT_TO_LLM]")
    _C_BRIGHT_GREEN = '\033[92m'
    _C_DARK_GREEN   = '\033[2;32m'
    _dt_colors  = {'Keep': '\033[32m',   'Compress': '\033[33m',   'Throw': '\033[31m'}
    _dtok_colors = {'Keep': '\033[2;32m', 'Compress': '\033[33m',   'Throw': '\033[31m'}
    done_lines = [
        f"=== INTERNAL (Req#{_rlabel}) === COMPRESSION DONE",
        f"  Result  : ~{info['estimated']}t → ~{new_estimated}t  ({fit_status})",
        f"  Actions : kept {keep_count}, compressed {compress_count} into {len(compress_groups)} group(s), threw {thrown_count}",
        f"  Groups  :",
        f"  {'Grp':<4}  {'Type':<8}  {'Idx':<4}  {'Role':<12}  {'Before':>6}  {'After':>6}  {'GrpBefore':>9}  {'GrpAfter':>8}  {'Planned':<8}  {'Executed':<8}  {'PlanRed':>7}  {'ActRed':>6}",
        f"  {'----':<4}  {'--------':<8}  {'----':<4}  {'------------':<12}  {'------':>6}  {'------':>6}  {'---------':>9}  {'--------':>8}  {'--------':<8}  {'--------':<8}  {'-------':>7}  {'------':>6}",
    ]
    done_color_lines = list(done_lines)
    for g_idx, g in enumerate(groups):
        _type      = g['type']
        _tc        = _dt_colors.get(_type, '')
        _tokc      = _dtok_colors.get(_type, '')
        grp_before = g['total_est_tokens']
        grp_after  = (compress_g_summary_tokens.get(g_idx, 0) if _type == 'Compress'
                      else 0 if _type == 'Throw'
                      else grp_before)
        # Planned / Executed action
        if _type == 'Compress':
            _pa = 'skip' if grp_before < MIN_COMPRESS_GROUP_TOKENS else 'compress'
            _ea = 'skip' if compress_g_summary_tokens.get(g_idx, -1) == grp_before else 'compress'
        elif _type == 'Throw':
            _pa = _ea = '-'
        else:
            _pa = _ea = '-'
        # Planned / Achieved token reduction (positive = saved tokens)
        if _type == 'Throw':
            _plan_red = grp_before
            _act_red  = grp_before
        elif _type == 'Compress' and _pa == 'compress':
            _plan_red = grp_before - g.get('max_summary_tokens', grp_before)
            _act_red  = grp_before - grp_after
        else:
            _plan_red = 0
            _act_red  = 0
        for row_i, idx in enumerate(g['indices']):
            _role    = _decision_rows[idx][1]
            _tok     = _weights[idx]
            _g_str   = f"g{g_idx}" if row_i == 0 else "|"
            _typ_str = _type       if row_i == 0 else "|"
            # Per-message After (must be exactly 6 chars to match header {'After':>6})
            if _type == 'Keep':
                after_plain = f"{_tok:>5}t"
                after_color = f"{_C_DARK_GREEN}{_tok:>5}t{RESET_COLOR}"
            elif _type == 'Compress':
                after_plain = f"{grp_after:>4}t*" if row_i == 0 else f"{'':>6}"
                after_color = (f"{_C_BRIGHT_GREEN}{grp_after:>4}t*{RESET_COLOR}" if row_i == 0 else f"{'':>6}")
            else:  # Throw
                after_plain = f"{'0':>5}t"
                after_color = f"{_C_BRIGHT_GREEN}{'0':>5}t{RESET_COLOR}"
            # Group totals (first row only, 9 and 8 chars to match headers)
            grp_b_plain = f"{grp_before:>8}t" if row_i == 0 else f"{'':>9}"
            grp_a_plain = f"{grp_after:>7}t"  if row_i == 0 else f"{'':>8}"
            grp_a_color = ((f"{_C_DARK_GREEN}{grp_after:>7}t{RESET_COLOR}" if _type == 'Keep'
                            else f"{_C_BRIGHT_GREEN}{grp_after:>7}t{RESET_COLOR}") if row_i == 0 else f"{'':>8}")
            # Action + reduction columns (first row only)
            _pa_str      = _pa              if row_i == 0 else ""
            _ea_str      = _ea              if row_i == 0 else ""
            _planred_str = f"{_plan_red:>6}t" if row_i == 0 else f"{'':>7}"
            _actred_str  = f"{_act_red:>5}t"  if row_i == 0 else f"{'':>6}"
            _plain = (f"  {_g_str:<4}  {_typ_str:<8}  [{idx:>2}]  {_role:<12}  {_tok:>5}t  {after_plain}"
                      f"  {grp_b_plain}  {grp_a_plain}  {_pa_str:<8}  {_ea_str:<8}  {_planred_str}  {_actred_str}")
            _color = (f"  {_g_str:<4}  {_tc if row_i == 0 else ''}{_typ_str:<8}{RESET_COLOR if row_i == 0 else ''}"
                      f"  [{idx:>2}]  {_role:<12}  {_tokc}{_tok:>5}t{RESET_COLOR}  {after_color}"
                      f"  {grp_b_plain}  {grp_a_color}  {_pa_str:<8}  {_ea_str:<8}  {_planred_str}  {_actred_str}")
            done_lines.append(_plain)
            done_color_lines.append(_color)
    log_msg = '\n'.join(done_lines)
    logger.debug(log_msg)
    color_logger.debug('\n'.join(done_color_lines))
    print(log_msg)

    return {
        'after': new_estimated,
        'summary_tokens': summary_tokens, 'kept_tokens': kept_tokens, 'latest_tokens': last_tokens,
        'still_over': new_estimated > MAX_TOKEN_INPUT_TO_LLM,
    }


# Global counters for logging: request.message format
_req_counter = 0
_msg_counter = 1

def call_llm(messages):
    """Send messages array to LLM. Returns (cleaned_output, raw_output, response_data) tuple."""
    global _req_counter, _msg_counter
    _req_counter += 1
    _msg_counter = 1
    # Log full messages to both files
    header = f"=== REQUEST_TO_LLM (Req#{_req_counter}), Input Messages {len(messages)} ==="
    logger.debug(header)
    color_logger.debug(header)
    for i, m in enumerate(messages):
        role = m['role']
        # Build display content: tool_calls messages don't have 'content'
        if 'tool_calls' in m:
            display = f"[tool_call] {json.dumps(m['tool_calls'])}"
            if m.get('thinking'):
                display = f"[thinking] {m['thinking'][:200]}... {display}"
        else:
            display = m.get('content', '')
        if role == 'assistant':
            tag = f"[{_req_counter}.{_msg_counter}.cleaned]"
        else:
            tag = f"[{_req_counter}.{_msg_counter}]"
        logger.debug("%s %s: %s", tag, role, display)
        c = ROLE_COLORS.get(role, '')
        if i < len(messages) - 1:
            c = '\033[2m' + c   # dim all but the last input message
        color_logger.debug("%s%s %s: %s%s", c, tag, role, display, RESET_COLOR)
        _msg_counter += 1

    # Console output (same as plain log)
    print(header)
    for i, m in enumerate(messages):
        role = m['role']
        if 'tool_calls' in m:
            display = f"[tool_call] {json.dumps(m['tool_calls'])}"
            if m.get('thinking'):
                display = f"[thinking] {m['thinking'][:200]}... {display}"
        else:
            display = m.get('content', '')
        if role == 'assistant':
            tag = f"[{_req_counter}.{i + 1}.cleaned]"
        else:
            tag = f"[{_req_counter}.{i + 1}]"
        print(f"{tag} {role}: {display}")

    # Token summary: per-message and total (send)
    _tok_lines = [f"  [{i}] {m['role']:<12} {estimate_tokens([m])}t" for i, m in enumerate(messages)]
    _est_total = estimate_tokens(messages)
    _tok_lines.append(f"  Total (estimated): {_est_total}t ({len(messages)} messages)  [heuristic: chars/{CHARS_PER_TOKEN}]")
    _tok_send = f"=== REQUEST_TO_LLM (Req#{_req_counter}) === TOKENS (send)\n" + '\n'.join(_tok_lines)
    logger.debug(_tok_send); color_logger.debug(_tok_send); print(_tok_send)

    # Build request body based on endpoint format
    if 'chat/completions' in ENDPOINT_SUFFIX:
        body = {
            'model': MODEL_PATH,
            'messages': messages,
            'max_tokens': MAX_TOKEN_OUTPUT_FROM_LLM,
            'chat_template_kwargs': {'reasoning_effort': 'medium'},
            'stop': ['<|call|>'],
            'tools': TOOLS,
        }
    else:
        prompt_text = flatten_messages_to_prompt(messages)
        body = {
            'model': MODEL_PATH,
            'prompt': prompt_text,
            'max_tokens': MAX_TOKEN_OUTPUT_FROM_LLM,
        }

    _waiting_msg = f"=== REQUEST_TO_LLM (Req#{_req_counter}) === waiting for LLM response..."
    logger.debug(_waiting_msg); color_logger.debug(_waiting_msg); print(_waiting_msg)

    response = requests.post(f"http://localhost:{MLX_PORT}/{ENDPOINT_SUFFIX}", json=body, timeout=300)

    if response.status_code != 200:
        raise RuntimeError(f"LLM server returned HTTP {response.status_code}: {response.text[:500]}")

    data = response.json()

    # Token summary: usage from response (recv)
    _usage = data.get('usage', {})
    _prompt_t = _usage.get('prompt_tokens', '?')
    _compl_t  = _usage.get('completion_tokens', '?')
    _total_t  = _usage.get('total_tokens', '?')
    _tok_recv = (
        f"=== REQUEST_TO_LLM (Req#{_req_counter}) === TOKENS (recv)\n"
        f"  prompt={_prompt_t}t (actual, from server tokenizer)  estimated={_est_total}t  diff={(_prompt_t - _est_total) if isinstance(_prompt_t, int) else '?'}t\n"
        f"  completion={_compl_t}t  total={_total_t}t"
    )
    logger.debug(_tok_recv); color_logger.debug(_tok_recv); print(_tok_recv)

    if 'choices' in data and data['choices']:
        raw_output = data['choices'][0]['message']['content'].strip()
    elif 'text' in data:
        raw_output = data['text'].strip()
    else:
        raise RuntimeError(f"LLM server returned unexpected response: {json.dumps(data)[:500]}")

    # Save raw output before stripping
    raw_before_stripping = raw_output

    # Log raw output before any stripping
    tag_raw = f"[{_req_counter}.{_msg_counter}.raw]"
    logger.debug("%s assistant: %s", tag_raw, raw_output)
    c_raw = ROLE_COLORS_RAW.get('assistant', ROLE_COLORS.get('assistant', ''))
    color_logger.debug("%s\033[3m%s assistant: %s%s", c_raw, tag_raw, raw_output, RESET_COLOR)
    print(f"{tag_raw} assistant: {raw_output}")

    raw_output = clean_llm_output(raw_output)

    # Log cleaned output to both files
    tag_cleaned = f"[{_req_counter}.{_msg_counter}.cleaned]"
    logger.debug("%s assistant: %s", tag_cleaned, raw_output)
    c = ROLE_COLORS_RAW.get('assistant', ROLE_COLORS.get('assistant', ''))
    color_logger.debug("%s\033[3m%s assistant: %s%s", c, tag_cleaned, raw_output, RESET_COLOR)
    print(f"{tag_cleaned} assistant: {raw_output}")
    _msg_counter += 1

    time.sleep(0.5)

    return raw_output, raw_before_stripping, data


def start_mlx_server():
    global mlx_process
    if not PYTHON_PATH:
        print("[MLX] ERROR: MLX_PYTHON_PATH not set in .env — cannot start server")
        return
    if not MODEL_PATH:
        print("[MLX] ERROR: MLX_MODEL_PATH not set in .env — cannot start server")
        return
    server_module = os.getenv('MLX_SERVER_MODULE', 'mlx_lm.server')
    print(f"[MLX] Starting server ({server_module}): {MODEL_PATH}")
    mlx_process = subprocess.Popen(
        [PYTHON_PATH, '-m', server_module, '--model', MODEL_PATH, '--port', MLX_PORT],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )
    print(f"[MLX] Server PID: {mlx_process.pid} on port {MLX_PORT}")


async def typing_indicator(bot, chat_id):
    """Send typing indicator every 4s until cancelled."""
    try:
        while True:
            try:
                await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            except Exception as e:
                print(f"[Typing] Error sending chat action: {e}")
                return
            await asyncio.sleep(4)
    except asyncio.CancelledError:
        pass


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in ALLOWED_IDS:
        return

    user_text = update.message.text.strip()
    chat_id = update.effective_chat.id
    username = update.effective_user.username or 'Unknown'
    print(f"=== INCOMING === @{username}: {user_text}")

    # Get or create conversation for this user
    if user_id not in conversations:
        conversations[user_id] = [
            {'role': 'developer', 'content': build_system_prompt()},
        ]
        message_history[user_id] = []
        user_counters[user_id] = {'req': 0, 'msg': 1}

    uc = user_counters[user_id]
    history = message_history[user_id]
    messages = conversations[user_id]

    uc['req'] += 1
    uc['msg'] = 1

    # Record developer message on first request
    if uc['req'] == 1:
        history.append({'req': 1, 'msg': 1, 'role': 'developer', 'content': build_system_prompt()})
        uc['msg'] = 2

    # Record user message
    messages.append({'role': 'user', 'content': user_text})
    history.append({'req': uc['req'], 'msg': uc['msg'], 'role': 'user', 'content': user_text})
    uc['msg'] += 1
    save_state()

    for iteration in range(MAX_COMMAND_ITERATIONS):
        typing_task = asyncio.create_task(typing_indicator(context.bot, chat_id))
        try:
            messages[0]['content'] = build_system_prompt()

            # Compress conversation if it exceeds token limit
            comp_info = check_compression_needed(messages)
            if comp_info:
                await update.message.reply_text("Compressing...")
                comp_result = await asyncio.get_event_loop().run_in_executor(None, do_compress, messages, comp_info)
                if 'error' in comp_result:
                    await update.message.reply_text(
                        f"Compression failed: {comp_result['error']}\n"
                        f"Please /reset and try again."
                    )
                    return
                save_state()
                await update.message.reply_text("Done compressing.")
                if comp_result['still_over']:
                    await update.message.reply_text(
                        f"Still over token limit after compression (~{comp_result['after']} > {MAX_TOKEN_INPUT_TO_LLM}). "
                        f"Please /reset or send a shorter message."
                    )
                    return

            cleaned_output, raw_output, resp_data = await asyncio.get_event_loop().run_in_executor(
                None, call_llm, messages
            )

            # Check for native tool call (gpt-oss format)
            native = extract_native_tool_call(raw_output)
            tool_name = None
            command = None

            if native:
                tool_name, args_json, command = native
                # Parse tool arguments
                try:
                    tool_args = json.loads(args_json)
                except json.JSONDecodeError:
                    tool_args = {}
                # Store as proper tool_calls message for chat template
                analysis = extract_analysis(raw_output)
                assistant_msg = {
                    'role': 'assistant',
                    'tool_calls': [{'function': {'name': tool_name, 'arguments': args_json}}],
                }
                if analysis:
                    assistant_msg['thinking'] = analysis
                messages.append(assistant_msg)
            else:
                messages.append({'role': 'assistant', 'content': cleaned_output})

            history.append({'req': uc['req'], 'msg': uc['msg'], 'role': 'assistant', 'variant': 'raw', 'content': raw_output})
            history.append({'req': uc['req'], 'msg': uc['msg'], 'role': 'assistant', 'variant': 'cleaned', 'content': cleaned_output})
            uc['msg'] += 1
            save_state()

            _post_lines = [f"  [{i}] {m['role']:<12} {estimate_tokens([m])}t" for i, m in enumerate(messages)]
            _post_lines.append(f"  Total (estimated): {estimate_tokens(messages)}t ({len(messages)} messages)")
            _post_log = f"=== REQUEST_TO_LLM (Req#{_req_counter}) === MESSAGES (after LLM response)\n" + '\n'.join(_post_lines)
            logger.debug(_post_log); color_logger.debug(_post_log); print(_post_log)

            if not native:
                # No tool call — this is the final answer
                reply = "\u2705 " + cleaned_output[:4000]
                await update.message.reply_text(reply)
                return

            # On first tool call, send the LLM's thinking/analysis to the user
            if iteration == 0 and analysis:
                # Clean up the analysis for display: strip the repeated user question if present
                thinking_text = clean_llm_output(analysis)
                if thinking_text:
                    await update.message.reply_text(f"\U0001f4ad {thinking_text[:1000]}")

            # Dispatch by tool name
            internal_header = f"=== INTERNAL (Req#{_req_counter}) ==="
            logger.debug(internal_header)
            color_logger.debug(internal_header)
            print(internal_header)

            if tool_name == 'strip_tags':
                file_path = tool_args.get('file_path', '')
                if not file_path:
                    result = "Error: no file_path provided"
                else:
                    run_msg = f"[{_req_counter}.-] app: RUNNING: strip_tags({file_path})"
                    logger.debug(run_msg)
                    c_app = '\033[35m'
                    color_logger.debug("%s%s%s", c_app, run_msg, RESET_COLOR)
                    print(run_msg)
                    await update.message.reply_text(f"\U0001f4c4 Stripping tags: {file_path[:300]}")
                    try:
                        result = strip_tags_from_file(file_path)
                    except Exception as e:
                        result = f"Error: {e}"

            elif tool_name == 'browse':
                url = tool_args.get('url', '')
                if not url:
                    result = "Error: no url provided"
                else:
                    run_msg = f"[{_req_counter}.-] app: RUNNING: browse({url})"
                    logger.debug(run_msg)
                    c_app = '\033[35m'
                    color_logger.debug("%s%s%s", c_app, run_msg, RESET_COLOR)
                    print(run_msg)
                    await update.message.reply_text(f"\U0001f310 Browsing: {url[:300]}")
                    try:
                        result = await asyncio.get_event_loop().run_in_executor(None, browse_url, url)
                    except Exception as e:
                        result = f"Error: {e}"

            elif tool_name == 'headless_browse':
                url = tool_args.get('url', '')
                if not url:
                    result = "Error: no url provided"
                else:
                    run_msg = f"[{_req_counter}.-] app: RUNNING: headless_browse({url})"
                    logger.debug(run_msg)
                    c_app = '\033[35m'
                    color_logger.debug("%s%s%s", c_app, run_msg, RESET_COLOR)
                    print(run_msg)
                    await update.message.reply_text(f"\U0001f310 Headless browsing: {url[:300]}")
                    try:
                        result = await asyncio.get_event_loop().run_in_executor(None, headless_browse_url, url)
                    except Exception as e:
                        result = f"Error: {e}"

            elif tool_name == 'web_search':
                query = tool_args.get('query', '')
                if not query:
                    result = "Error: no query provided"
                else:
                    run_msg = f"[{_req_counter}.-] app: RUNNING: web_search({query})"
                    logger.debug(run_msg)
                    c_app = '\033[35m'
                    color_logger.debug("%s%s%s", c_app, run_msg, RESET_COLOR)
                    print(run_msg)
                    await update.message.reply_text(f"\U0001f50d Searching: {query[:300]}")
                    try:
                        result = await asyncio.get_event_loop().run_in_executor(None, web_search, query)
                    except Exception as e:
                        result = f"Error: {e}"

            elif tool_name == 'bash':
                if not command:
                    # Tool call detected but command extraction failed
                    warn = f"[{_req_counter}.-] MALFORMED TOOL CALL — retrying"
                    print(warn)
                    logger.debug(warn)
                    await update.message.reply_text(warn)
                    messages.append({'role': 'tool', 'content': 'Error: could not parse your tool call. Please try again with valid JSON.'})
                    history.append({'req': uc['req'], 'msg': uc['msg'], 'role': 'tool', 'content': 'Error: malformed tool call'})
                    uc['msg'] += 1
                    save_state()
                    continue


                run_msg = f"[{_req_counter}.-] app: RUNNING: {command}"
                logger.debug(run_msg)
                c_app = '\033[35m'
                color_logger.debug("%s%s%s", c_app, run_msg, RESET_COLOR)
                print(run_msg)
                await update.message.reply_text(f"\u2699\ufe0f Running: {command[:300]}")

                try:
                    result = execute_command(command)
                except subprocess.TimeoutExpired:
                    result = "Command timed out after 60 seconds."

            else:
                # Unknown tool — likely a hallucinated name. Feed back available tools and retry.
                available = ', '.join(t['function']['name'] for t in TOOLS)
                result = f"Error: unknown tool '{tool_name}'. Available tools: {available}. Please retry with a valid tool name."
                warn = f"[{_req_counter}.-] UNKNOWN TOOL '{tool_name}' — retrying"
                print(warn)
                logger.debug(warn)
                color_logger.debug(warn)
                messages.append({'role': 'tool', 'content': result})
                history.append({'req': uc['req'], 'msg': uc['msg'], 'role': 'tool', 'content': result})
                uc['msg'] += 1
                save_state()
                continue

            # Log result
            result_msg_log = f"[{_req_counter}.-] app: RESULT: {result}"
            logger.debug(result_msg_log)
            c_app = '\033[35m'  # magenta
            color_logger.debug("%s%s%s", c_app, result_msg_log, RESET_COLOR)
            print(result_msg_log)

            # Truncate result for context window, preserving links section
            if len(result) > MAX_TOOL_RESULT_CHARS:
                original_len = len(result)
                links_marker = "\n\n--- Links ---\n"
                if links_marker in result:
                    body, raw_links = result.split(links_marker, 1)
                    # Apply domain filtering and cap at MAX_LINKS for LLM
                    filtered = filter_links(raw_links.strip().split("\n"))
                    links_section = links_marker + "\n".join(filtered)
                    body_budget = MAX_TOOL_RESULT_CHARS - len(links_section)
                    if body_budget > 200:
                        body = body[:body_budget]
                    else:
                        body = body[:MAX_TOOL_RESULT_CHARS]
                        links_section = ""
                    result = body + f"\n... [truncated from {original_len} to ~{MAX_TOOL_RESULT_CHARS} chars]" + links_section
                else:
                    result = result[:MAX_TOOL_RESULT_CHARS] + f"\n... [truncated from {original_len} to {MAX_TOOL_RESULT_CHARS} chars]"
            result_msg = {'role': 'tool', 'content': result, 'useful': True}
            messages.append(result_msg)
            history.append({'req': uc['req'], 'msg': uc['msg'], 'role': 'tool', 'content': result})
            uc['msg'] += 1
            save_state()

        except Exception as e:
            print(f"=== ERROR (Req#{_req_counter}) === {e}")
            await update.message.reply_text(f"Error: {e}")
            return
        finally:
            typing_task.cancel()

    # Max iterations reached
    await update.message.reply_text("Reached maximum command iterations. Stopping.")


def log_command(cmd: str, update) -> None:
    username = update.effective_user.username or 'Unknown'
    msg = f"=== COMMAND === {cmd} from @{username}"
    print(msg)
    logger.debug(msg)
    c = ROLE_COLORS.get('user', '')
    color_logger.debug("%s%s%s", c, msg, RESET_COLOR)


async def on_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global conversations, message_history, user_counters, _req_counter
    user_id = str(update.effective_user.id)
    if user_id not in ALLOWED_IDS:
        return
    conversations.clear()
    message_history.clear()
    user_counters.clear()
    _req_counter = 0
    save_state()
    load_state()
    log_command('/reset', update)
    await update.message.reply_text("State cleared and reloaded. Ready for new messages.")



async def on_ram(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in ALLOWED_IDS:
        return
    try:
        vm = subprocess.run(['vm_stat'], capture_output=True, text=True, timeout=5)
        lines = vm.stdout.strip().split('\n')
        stats = {}
        for line in lines[1:]:
            if ':' in line:
                key, val = line.split(':', 1)
                val = val.strip().rstrip('.')
                if val.isdigit():
                    stats[key.strip()] = int(val)
        page_size = 16384  # Apple Silicon default
        free = stats.get('Pages free', 0) * page_size
        active = stats.get('Pages active', 0) * page_size
        inactive = stats.get('Pages inactive', 0) * page_size
        wired = stats.get('Pages wired down', 0) * page_size
        compressed = stats.get('Pages occupied by compressor', 0) * page_size
        used = active + wired + compressed
        total = free + active + inactive + wired + compressed
        gb = lambda b: f"{b / (1024**3):.1f}GB"
        msg = (
            f"RAM Usage:\n"
            f"  Used: {gb(used)} (active {gb(active)} + wired {gb(wired)} + compressed {gb(compressed)})\n"
            f"  Free: {gb(free)}\n"
            f"  Inactive: {gb(inactive)}\n"
            f"  Total: {gb(total)}"
        )
    except Exception as e:
        msg = f"Error reading RAM: {e}"
    log_command('/ram', update)
    await update.message.reply_text(msg)


async def on_quit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in ALLOWED_IDS:
        return
    log_command('/quit', update)
    await update.message.reply_text("Shutting down...")
    if mlx_process:
        mlx_process.terminate()
    os._exit(0)


async def on_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in ALLOWED_IDS:
        return
    log_command('/reminders', update)
    reminders = load_reminders()
    if not reminders:
        await update.message.reply_text("No active reminders.")
        return
    lines = []
    for r in reminders:
        prefix = "recurring" if r.get('type') == 'recurring' else "once"
        every = f" ({r['every']})" if 'every' in r else ""
        lines.append(f"[{prefix}] {r['due']}{every} - {r['message']}")
    await update.message.reply_text("Active reminders:\n" + "\n".join(lines))


async def on_clearreminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in ALLOWED_IDS:
        return
    log_command('/clearreminders', update)
    if os.path.exists(REMINDERS_FILE):
        os.remove(REMINDERS_FILE)
    await update.message.reply_text("All reminders cleared.")


async def on_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in ALLOWED_IDS:
        return
    log_command('/tasks', update)
    tasks = load_tasks()
    if not tasks:
        await update.message.reply_text("No scheduled tasks.")
        return
    lines = []
    for t in tasks:
        prefix = "recurring" if t.get('type') == 'recurring' else "once"
        every = f" ({t['every']})" if 'every' in t else ""
        lines.append(f"[{prefix}] {t['due']}{every}\n  {t['id']}: {t['task'][:80]}")
    await update.message.reply_text("Scheduled tasks:\n" + "\n".join(lines))


async def on_cleartasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in ALLOWED_IDS:
        return
    log_command('/cleartasks', update)
    if os.path.exists(TASKS_FILE):
        os.remove(TASKS_FILE)
    await update.message.reply_text("All tasks cleared.")


async def on_env(update: Update, _context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in ALLOWED_IDS:
        return
    log_command('/env', update)
    env_file = os.path.join(_CALMCLAW, '.env')
    if os.path.exists(env_file):
        lines = [l.rstrip() for l in open(env_file) if l.strip() and not l.strip().startswith('#')]
    else:
        lines = []
    lines += [
        '',
        '# Computed values',
        f'MAX_TOKEN_OUTPUT_FROM_LLM={MAX_TOKEN_OUTPUT_FROM_LLM}',
        f'MAX_TOKEN_COMPRESSION_SUMMARY={MAX_TOKEN_COMPRESSION_SUMMARY}',
        f'MAX_TOOL_RESULT_CHARS={MAX_TOOL_RESULT_CHARS}',
    ]
    await update.message.reply_text('\n'.join(lines) if lines else "No settings found.")


async def on_compress(update: Update, _context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in ALLOWED_IDS:
        return
    log_command('/compress', update)

    if user_id not in conversations:
        await update.message.reply_text("No conversation yet.")
        return

    messages = conversations[user_id]
    comp_info = check_compression_needed(messages, force=True, req_label='-')
    if comp_info is None:
        await update.message.reply_text("Nothing to compress (no middle messages).")
        return

    await update.message.reply_text("Compressing...")

    comp_result = await asyncio.get_event_loop().run_in_executor(None, do_compress, messages, comp_info)
    if 'error' in comp_result:
        await update.message.reply_text(f"Compression failed: {comp_result['error']}")
        return

    save_state()
    await update.message.reply_text("Done compressing.")


async def on_thrown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in ALLOWED_IDS:
        return
    log_command('/thrown', update)
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /thrown <N>")
        return
    n = int(context.args[0])
    if user_id not in conversations:
        await update.message.reply_text("No conversation yet.")
        return
    messages = conversations[user_id]
    throwable = len(messages) - 1  # index 0 is protected
    if n <= 0 or n > throwable:
        await update.message.reply_text(f"N must be between 1 and {throwable}.")
        return
    to_throw = list(range(len(messages) - n, len(messages)))
    thrown_msgs = [(i, messages[i]) for i in to_throw]
    for i in reversed(to_throw):
        del messages[i]
    save_state()
    lines = [f"Threw {n} message(s):"]
    for i, m in thrown_msgs:
        preview = str(m.get('content') or '[tool_call]')[:80]
        lines.append(f"  [{i}] {m['role']}: {preview}")
    await update.message.reply_text('\n'.join(lines))


async def on_throw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in ALLOWED_IDS:
        return
    log_command('/throw', update)
    if not context.args:
        await update.message.reply_text("Usage: /throw <idx> [idx ...]")
        return
    if user_id not in conversations:
        await update.message.reply_text("No conversation yet.")
        return
    messages = conversations[user_id]
    indices = []
    errors = []
    for arg in context.args:
        if not arg.isdigit():
            errors.append(f"'{arg}' is not a valid index")
            continue
        idx = int(arg)
        if idx == 0:
            errors.append("Cannot throw index 0 (system message)")
            continue
        if idx >= len(messages):
            errors.append(f"Index {idx} out of range (max {len(messages) - 1})")
            continue
        indices.append(idx)
    if errors:
        await update.message.reply_text("Errors:\n" + '\n'.join(errors))
        return
    if not indices:
        await update.message.reply_text("No valid indices provided.")
        return
    unique = sorted(set(indices))
    thrown_msgs = [(i, messages[i]) for i in unique]
    for i in reversed(unique):
        del messages[i]
    save_state()
    lines = [f"Threw {len(thrown_msgs)} message(s):"]
    for i, m in thrown_msgs:
        preview = str(m.get('content') or '[tool_call]')[:80]
        lines.append(f"  [{i}] {m['role']}: {preview}")
    await update.message.reply_text('\n'.join(lines))


async def on_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in ALLOWED_IDS:
        return
    log_command('/messages', update)
    messages = conversations.get(user_id, [])
    total_chars  = sum(len(str(m.get('content') or '')) for m in messages)
    total_tokens = estimate_tokens(messages)
    lines = [f"Messages : {len(messages)}",
             f"Chars    : {total_chars}",
             f"Tokens   : {total_tokens}t"]
    await update.message.reply_text('\n'.join(lines))


async def on_unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in ALLOWED_IDS:
        return
    cmd = update.message.text.split()[0] if update.message.text else '?'
    await update.message.reply_text(f"Unknown command: {cmd}")


def shutdown(sig, frame):
    print("\n[App] Shutting down...")
    if mlx_process:
        mlx_process.terminate()
    sys.exit(0)


def main():
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    #start_mlx_server()
    load_state()

    print("[Bot] Starting Telegram bot...")

    async def post_init(application):
        asyncio.create_task(reminder_check_loop(application))
        asyncio.create_task(task_check_loop(application))

    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("reset", on_reset))
    app.add_handler(CommandHandler("ram", on_ram))
    app.add_handler(CommandHandler("reminders", on_reminders))
    app.add_handler(CommandHandler("clearreminders", on_clearreminders))
    app.add_handler(CommandHandler("tasks", on_tasks))
    app.add_handler(CommandHandler("cleartasks", on_cleartasks))
    app.add_handler(CommandHandler("env", on_env))
    app.add_handler(CommandHandler("compress", on_compress))
    app.add_handler(CommandHandler("messages", on_messages))
    app.add_handler(CommandHandler("thrown", on_thrown))
    app.add_handler(CommandHandler("throw", on_throw))
    app.add_handler(CommandHandler("quit", on_quit))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.add_handler(MessageHandler(filters.COMMAND, on_unknown_command))

    print("[Bot] Polling for messages. Press Ctrl+C to stop.\n")
    app.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()
