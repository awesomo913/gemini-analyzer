"""Gemini Takeout data parser — handles HTML and JSON export formats."""

import html as html_lib
import json
import re
import zipfile
import tempfile
import shutil
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import logging

logger = logging.getLogger(__name__)


@dataclass
class Message:
    role: str  # "user" or "model"
    text: str
    timestamp: Optional[datetime] = None
    attachments: list[str] = field(default_factory=list)

    def has_code(self) -> bool:
        return bool(re.search(r'```[\s\S]*?```', self.text))

    def extract_code_blocks(self) -> list[dict]:
        blocks = []
        pattern = re.compile(r'```(\w*)\n?([\s\S]*?)```')
        for match in pattern.finditer(self.text):
            lang = match.group(1).strip().lower() or "text"
            code = match.group(2).strip()
            if code:
                blocks.append({"language": lang, "code": code})
        return blocks


@dataclass
class Conversation:
    id: str
    title: str
    messages: list[Message] = field(default_factory=list)
    create_time: Optional[datetime] = None
    update_time: Optional[datetime] = None
    source_file: str = ""
    category: str = "Uncategorized"
    subcategory: str = ""
    tags: list[str] = field(default_factory=list)
    coding_project_name: str = ""
    activity_type: str = ""  # "Prompted", "Created Gemini Canvas", "Live Prompt", etc.

    @property
    def message_count(self) -> int:
        return len(self.messages)

    @property
    def user_messages(self) -> list[Message]:
        return [m for m in self.messages if m.role == "user"]

    @property
    def model_messages(self) -> list[Message]:
        return [m for m in self.messages if m.role == "model"]

    @property
    def all_code_blocks(self) -> list[dict]:
        blocks = []
        for msg in self.messages:
            for block in msg.extract_code_blocks():
                block["conversation_id"] = self.id
                block["conversation_title"] = self.title
                blocks.append(block)
        return blocks

    @property
    def full_text(self) -> str:
        return "\n".join(m.text for m in self.messages)

    @property
    def has_code(self) -> bool:
        return any(m.has_code() for m in self.messages)


# ── Timestamp parsing ────────────────────────────────────────────────

_TIMESTAMP_FORMATS = (
    "%b %d, %Y, %I:%M:%S\u202f%p %Z",   # "Apr 1, 2026, 2:12:20 PM EDT"
    "%b %d, %Y, %I:%M:%S %p %Z",
    "%b %d, %Y, %I:%M:%S\u202f%p",
    "%b %d, %Y, %I:%M:%S %p",
    "%b %d, %Y, %I:%M\u202f%p %Z",
    "%b %d, %Y, %I:%M %p %Z",
    "%b %d, %Y, %I:%M\u202f%p",
    "%b %d, %Y, %I:%M %p",
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
)


def _parse_timestamp(raw) -> Optional[datetime]:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(raw)
        except (OSError, ValueError):
            try:
                return datetime.fromtimestamp(raw / 1000)
            except (OSError, ValueError):
                return None
    if isinstance(raw, str):
        raw_clean = raw.strip()
        # Strip timezone abbreviations that Python can't parse
        raw_no_tz = re.sub(r'\s+(?:EST|EDT|CST|CDT|MST|MDT|PST|PDT|UTC|GMT)\s*$', '', raw_clean)
        for candidate in (raw_clean, raw_no_tz):
            for fmt in _TIMESTAMP_FORMATS:
                try:
                    return datetime.strptime(candidate, fmt)
                except ValueError:
                    continue
    if isinstance(raw, dict):
        if "seconds" in raw:
            try:
                return datetime.fromtimestamp(int(raw["seconds"]))
            except (OSError, ValueError):
                return None
        if "$date" in raw:
            return _parse_timestamp(raw["$date"])
    return None


# ── HTML parsing (real Gemini Takeout format) ────────────────────────

def _strip_html(text: str) -> str:
    """Remove HTML tags, decode entities, normalize whitespace."""
    text = re.sub(r'<br\s*/?>', '\n', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = html_lib.unescape(text)
    return text


def _reassemble_code_blocks(text: str) -> str:
    """Reassemble code fences that got split by HTML stripping."""
    # Fix orphaned ``` that lost their language tag during HTML parsing
    # Normalize multiple newlines inside code blocks
    text = re.sub(r'```\s*\n\s*\n+', '```\n', text)
    return text


def parse_html_activity(html_content: str, source: str = "") -> list[Conversation]:
    """Parse Google Takeout MyActivity.html for Gemini Apps."""
    conversations = []

    # Split on outer-cell divs — much faster than regex lookahead on 46MB
    _SPLIT_TAG = '<div class="outer-cell mdl-cell mdl-cell--12-col mdl-shadow--2dp">'
    blocks = html_content.split(_SPLIT_TAG)[1:]  # skip content before first block
    logger.info("Found %d activity blocks in HTML from %s", len(blocks), source)

    for idx, block in enumerate(blocks):
        conv = _parse_html_block(block, idx, source)
        if conv:
            conversations.append(conv)

    logger.info("Parsed %d conversations from HTML %s", len(conversations), source)
    return conversations


def _parse_html_block(block: str, index: int, source: str) -> Optional[Conversation]:
    """Parse a single outer-cell block into a Conversation."""

    # Extract content cells
    cell_pattern = re.compile(
        r'<div class="content-cell[^"]*">(.*?)</div>',
        re.DOTALL,
    )
    cells = cell_pattern.findall(block)

    if len(cells) < 2:
        return None

    # Cell 0: main content (prompt + response interleaved)
    # The first content-cell with body-1 class contains the user prompt info
    # The second content-cell (if right-aligned) may be empty
    # Then there's a caption cell with metadata

    # Extract all body-1 cells (left and right columns)
    body_cells = re.findall(
        r'<div class="content-cell mdl-cell mdl-cell--6-col mdl-typography--body-1">(.*?)</div>',
        block,
        re.DOTALL,
    )
    body_cells_right = re.findall(
        r'<div class="content-cell mdl-cell mdl-cell--6-col mdl-typography--body-1 mdl-typography--text-right">(.*?)</div>',
        block,
        re.DOTALL,
    )
    full_body_cells = re.findall(
        r'<div class="content-cell mdl-cell mdl-cell--12-col mdl-typography--body-1">(.*?)</div>',
        block,
        re.DOTALL,
    )

    if not body_cells:
        return None

    # First body cell contains the prompt/action line and possibly the response
    raw_content = body_cells[0]

    # Detect activity type and extract user prompt
    content_text = _strip_html(raw_content)
    # Normalize non-breaking spaces and other Unicode whitespace
    content_text = content_text.replace("\xa0", " ").replace("\u202f", " ").strip()

    activity_type = ""
    user_prompt = ""
    attachments = []

    # Detect the activity type prefix (order matters — longest first)
    _PREFIXES = [
        ("Created Gemini Canvas titled ", "Created Gemini Canvas"),
        ("Live Prompt ", "Live Prompt"),
        ("Prompted ", "Prompted"),
        ("Used an Assistant", "Used Assistant"),
        ("Searched for ", "Searched"),
        ("Uploaded ", "Uploaded"),
    ]
    matched = False
    for prefix, atype in _PREFIXES:
        if content_text.startswith(prefix):
            activity_type = atype
            user_prompt = content_text[len(prefix):]
            matched = True
            break
    if not matched:
        activity_type = "Other"
        user_prompt = content_text

    # Extract timestamp — look for date pattern in the raw content
    timestamp = None
    ts_pattern = re.compile(
        r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4},\s+\d{1,2}:\d{2}(?::\d{2})?\s*(?:\u202f|\s)*[AP]M(?:\s+\w+)?'
    )
    ts_matches = ts_pattern.findall(raw_content)
    if not ts_matches:
        ts_matches = ts_pattern.findall(block)
    if ts_matches:
        timestamp = _parse_timestamp(ts_matches[0])

    # Remove the timestamp line from the user prompt
    for ts_str in ts_matches:
        clean_ts = _strip_html(ts_str).strip()
        user_prompt = user_prompt.replace(clean_ts, "").strip()

    # Detect attachments
    attach_match = re.search(r'Attached (\d+) files?\.', user_prompt)
    if attach_match:
        # Find filenames after "Attached N files."
        after_attach = user_prompt[attach_match.end():]
        filenames = re.findall(r'[\w\s\(\)]+\.(?:jpg|png|gif|pdf|txt|py|js|json|zip|csv|html)\b',
                               after_attach, re.IGNORECASE)
        attachments = [f.strip() for f in filenames]
        # Clean up: remove the "Attached N files. - filename - filename" part
        user_prompt = user_prompt[:attach_match.start()].strip()
        if not user_prompt:
            user_prompt = attach_match.group(0)

    # Clean up trailing noise from user prompt
    user_prompt = user_prompt.strip()
    # Remove trailing timestamps that leaked in
    user_prompt = ts_pattern.sub('', user_prompt).strip()
    # Remove trailing dashes/bullets
    user_prompt = re.sub(r'\s*-\s*$', '', user_prompt)

    if not user_prompt:
        return None

    # Build title from the user prompt
    title_text = user_prompt[:120].replace("\n", " ").strip()
    if len(user_prompt) > 120:
        title_text += "..."

    # Now extract the model response — everything after the timestamp in the block
    # The response spans the remaining content of the first body cell after the timestamp,
    # plus any full-width body cells
    model_response_parts = []

    # Split the first body cell at the timestamp to get the response portion
    raw_after_timestamp = raw_content
    for ts_str in ts_matches:
        split_idx = raw_after_timestamp.find(ts_str)
        if split_idx >= 0:
            raw_after_timestamp = raw_after_timestamp[split_idx + len(ts_str):]
            break

    response_from_first_cell = _strip_html(raw_after_timestamp).strip()
    # Remove metadata footer
    response_from_first_cell = re.sub(
        r'Products:\s*Gemini Apps.*$', '', response_from_first_cell, flags=re.DOTALL
    ).strip()
    if response_from_first_cell:
        model_response_parts.append(response_from_first_cell)

    # Add any full-width body cells (12-col) that contain response content
    for cell in full_body_cells:
        cell_text = _strip_html(cell).strip()
        # Skip metadata/footer cells
        if cell_text.startswith("Products:") or cell_text.startswith("Why is this here"):
            continue
        if cell_text:
            model_response_parts.append(cell_text)

    model_response = "\n".join(model_response_parts).strip()

    # Remove metadata that leaks into response
    model_response = re.sub(
        r'Products:\s*Gemini Apps.*$', '', model_response, flags=re.DOTALL
    ).strip()
    model_response = re.sub(
        r'Why is this here\?.*$', '', model_response, flags=re.DOTALL
    ).strip()
    model_response = re.sub(
        r'This activity was saved to your Google Account.*$', '', model_response, flags=re.DOTALL
    ).strip()

    # Reassemble code blocks
    model_response = _reassemble_code_blocks(model_response)

    # Generate stable ID
    conv_id = hashlib.md5(
        f"{source}:{index}:{title_text[:50]}".encode()
    ).hexdigest()[:12]

    messages = []

    # User message
    messages.append(Message(
        role="user",
        text=user_prompt,
        timestamp=timestamp,
        attachments=attachments,
    ))

    # Model response (if any)
    if model_response:
        messages.append(Message(
            role="model",
            text=model_response,
            timestamp=timestamp,
        ))

    return Conversation(
        id=conv_id,
        title=title_text,
        messages=messages,
        create_time=timestamp,
        source_file=source,
        activity_type=activity_type,
    )


def parse_html_file(filepath: Path) -> list[Conversation]:
    """Parse an HTML file (MyActivity.html from Gemini Takeout)."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError as e:
        logger.error("Failed to read %s: %s", filepath, e)
        return []

    # The CSS/JS block in Takeout files can be 140K+ before the body starts
    # Check the filename and a broader range of content for markers
    is_activity_file = "myactivity" in filepath.name.lower()
    has_marker = "outer-cell" in content or "Gemini Apps" in content[:300000]
    if not is_activity_file and not has_marker:
        logger.debug("Skipping non-activity HTML: %s", filepath.name)
        return []

    return parse_html_activity(content, str(filepath.name))


# ── JSON parsing (alternative format / future-proofing) ──────────────

def _extract_text_from_parts(parts) -> str:
    if isinstance(parts, str):
        return parts
    if isinstance(parts, list):
        texts = []
        for part in parts:
            if isinstance(part, str):
                texts.append(part)
            elif isinstance(part, dict):
                if "text" in part:
                    texts.append(str(part["text"]))
                elif "content" in part:
                    texts.append(str(part["content"]))
        return "\n".join(texts)
    if isinstance(parts, dict):
        if "text" in parts:
            return str(parts["text"])
        if "content" in parts:
            return str(parts["content"])
    return str(parts) if parts else ""


def _normalize_role(role: str) -> str:
    role = role.lower().strip()
    if role in ("user", "human", "0"):
        return "user"
    if role in ("model", "assistant", "bot", "gemini", "1"):
        return "model"
    return role


def _parse_single_conversation(data: dict, source: str = "") -> Optional[Conversation]:
    conv_id = str(
        data.get("id")
        or data.get("conversation_id")
        or data.get("uuid")
        or hash(json.dumps(data, default=str, sort_keys=True))
    )

    title = (
        data.get("title")
        or data.get("name")
        or data.get("topic")
        or data.get("summary")
        or ""
    )

    create_time = _parse_timestamp(
        data.get("create_time")
        or data.get("createTime")
        or data.get("created_at")
        or data.get("timestamp")
    )
    update_time = _parse_timestamp(
        data.get("update_time")
        or data.get("updateTime")
        or data.get("updated_at")
        or data.get("last_modified")
    )

    messages = []
    raw_messages = (
        data.get("messages")
        or data.get("turns")
        or data.get("entries")
        or data.get("content")
        or data.get("mapping")
        or []
    )

    if isinstance(raw_messages, dict):
        raw_messages = list(raw_messages.values())

    for raw_msg in raw_messages:
        if not isinstance(raw_msg, dict):
            continue

        role = _normalize_role(str(
            raw_msg.get("role")
            or raw_msg.get("author")
            or raw_msg.get("sender")
            or raw_msg.get("from")
            or "unknown"
        ))

        text_raw = (
            raw_msg.get("parts")
            or raw_msg.get("text")
            or raw_msg.get("content")
            or raw_msg.get("body")
            or raw_msg.get("message")
            or ""
        )
        text = _extract_text_from_parts(text_raw)

        if not text.strip():
            continue

        ts = _parse_timestamp(
            raw_msg.get("create_time")
            or raw_msg.get("createTime")
            or raw_msg.get("timestamp")
            or raw_msg.get("created_at")
        )

        messages.append(Message(role=role, text=text, timestamp=ts))

    if not messages:
        return None

    if not title:
        first_user = next((m for m in messages if m.role == "user"), None)
        if first_user:
            title = first_user.text[:80].replace("\n", " ").strip()
            if len(first_user.text) > 80:
                title += "..."

    return Conversation(
        id=conv_id,
        title=title,
        messages=messages,
        create_time=create_time,
        update_time=update_time,
        source_file=source,
    )


def parse_json_file(filepath: Path) -> list[Conversation]:
    conversations = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.warning("Failed to parse %s: %s", filepath, e)
        return []

    source = str(filepath.name)

    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                conv = _parse_single_conversation(item, source)
                if conv:
                    conversations.append(conv)
    elif isinstance(data, dict):
        for key in ("conversations", "chats", "data", "items", "results"):
            if key in data and isinstance(data[key], list):
                for item in data[key]:
                    if isinstance(item, dict):
                        conv = _parse_single_conversation(item, source)
                        if conv:
                            conversations.append(conv)
                break
        else:
            conv = _parse_single_conversation(data, source)
            if conv:
                conversations.append(conv)

    logger.info("Parsed %d conversations from %s", len(conversations), filepath.name)
    return conversations


# ── Directory + ZIP parsing ──────────────────────────────────────────

def parse_directory(dirpath: Path) -> list[Conversation]:
    conversations = []

    # Find HTML files first (primary format for Gemini Takeout)
    html_files = sorted(dirpath.rglob("*.html"))
    json_files = sorted(dirpath.rglob("*.json"))

    logger.info("Found %d HTML files, %d JSON files in %s",
                len(html_files), len(json_files), dirpath)

    for hf in html_files:
        if hf.name.startswith(".") or "__MACOSX" in str(hf):
            continue
        conversations.extend(parse_html_file(hf))

    for jf in json_files:
        if jf.name.startswith(".") or "__MACOSX" in str(jf):
            continue
        conversations.extend(parse_json_file(jf))

    logger.info("Total parsed: %d conversations from %s", len(conversations), dirpath)
    return conversations


def parse_zip(zip_path: Path) -> list[Conversation]:
    conversations = []
    tmp_dir = Path(tempfile.mkdtemp(prefix="gemini_analyzer_"))
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmp_dir)
        conversations = parse_directory(tmp_dir)
    except zipfile.BadZipFile as e:
        logger.error("Bad zip file %s: %s", zip_path, e)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return conversations


def parse_input(path: Path) -> list[Conversation]:
    if not path.exists():
        raise FileNotFoundError(f"Path not found: {path}")

    if path.is_file():
        suffix = path.suffix.lower()
        if suffix == ".zip":
            return parse_zip(path)
        elif suffix == ".json":
            return parse_json_file(path)
        elif suffix in (".html", ".htm"):
            return parse_html_file(path)
        else:
            raise ValueError(f"Unsupported file type: {suffix}")
    elif path.is_dir():
        return parse_directory(path)
    else:
        raise ValueError(f"Invalid path: {path}")
