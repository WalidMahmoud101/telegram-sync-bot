#!/usr/bin/env python3
"""
tg_txt_sync.py - Daily downloader for .txt/.rar files from Telegram folders/channels
(personal account via Telethon)

Usage:
  python3 tg_txt_sync.py --login            # one time: sign in (phone + code)
  python3 tg_txt_sync.py --list-folders     # show available folder names
  python3 tg_txt_sync.py                    # run the sync (for scheduling)
  python3 tg_txt_sync.py --dry-run          # show what would be downloaded

Settings come from a .env file (next to the script) or environment variables - see env.example
TG_FOLDERS=comma-separated folder names, TG_CHANNELS=comma-separated channel IDs/usernames
"""
import argparse
import asyncio
import ctypes
import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from colorama import Fore, Style
from colorama import init as colorama_init
from telethon import TelegramClient, utils
from telethon.errors import FloodWaitError
from telethon.tl.functions.messages import GetDialogFiltersRequest
from telethon.tl.types import DialogFilter, InputMessagesFilterDocument

BASE = Path(__file__).resolve().parent

colorama_init()

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


class FolderNotFound(Exception):
    pass


class ColorFormatter(logging.Formatter):
    """Colored output for the console; the log file stays plain."""
    COLORS = {
        logging.DEBUG: Fore.WHITE,
        logging.INFO: Fore.GREEN,
        logging.WARNING: Fore.YELLOW,
        logging.ERROR: Fore.RED,
    }

    def format(self, record):
        msg = super().format(record)
        color = self.COLORS.get(record.levelno)
        return f"{color}{msg}{Style.RESET_ALL}" if color else msg


def set_title(text):
    """Update the console window title (Windows only, silent elsewhere)."""
    if os.name == "nt":
        try:
            ctypes.windll.kernel32.SetConsoleTitleW(text)
        except Exception:
            pass


class Stats:
    """Shared counters + console title for the whole run."""

    def __init__(self):
        self.total = 0
        self.mb = 0.0
        self.base = "TG Sync"
        self.context = ""

    def add_mb(self, n):
        self.mb += n

    def update(self, context=None):
        if context is not None:
            self.context = context
        set_title(
            f"{self.base} | {self.context} | {self.total} files | {self.mb / 1024:.1f} GB done"
        )


STATS = Stats()

STATE_LOCK = asyncio.Lock()  # serializes state.json writes from concurrent chats


class Notifier:
    """Sends one Saved Messages report and keeps editing it live (phone-friendly)."""

    def __init__(self, client, enabled, target):
        self.client = client
        self.enabled = enabled
        self.target = target
        self.msg = None
        self.lines = []
        self.kv = {}  # stable per-key lines (e.g. one progress line per channel)
        self.last_edit = 0.0

    def _text(self):
        return "\n".join(self.lines + list(self.kv.values()))

    async def _edit(self, force=False):
        if self.msg is None:
            return
        now = asyncio.get_event_loop().time()
        if not force and now - self.last_edit < 10:  # Telegram edit-rate throttle
            return
        self.last_edit = now
        try:
            await self.msg.edit(self._text())
        except Exception:
            pass

    async def start(self, text):
        if not self.enabled:
            return
        self.lines.append(text)
        try:
            self.msg = await self.client.send_message(self.target, text)
        except Exception:
            self.msg = None  # never let notifications break the sync

    async def add(self, line, force=False):
        if not self.enabled or self.msg is None:
            return
        self.lines.append(line)
        await self._edit(force)

    async def set(self, key, line, force=False):
        """Add or update one stable line (keyed) - used for live counters."""
        if not self.enabled or self.msg is None:
            return
        self.kv[key] = line
        await self._edit(force)


def load_env():
    env_file = BASE / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def cfg(name, default=None, required=False):
    v = os.environ.get(name, default)
    if required and not v:
        sys.exit(f"Missing setting {name} (add it to .env)")
    return v


def safe(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", name or "").strip(" .")
    return name[:80] or "unnamed"


def title_text(t):
    # In newer Telethon the title can be TextWithEntities
    return getattr(t, "text", t) or ""


PASS_RE = re.compile(
    r"(?:\bpass(?:word)?\b|باسورد|الباسورد)\s*[:=\-]\s*[\"']?([^\s\"',;]+)",
    re.IGNORECASE,
)


def extract_passwords(text):
    """Grab archive passwords from the message caption (pass / password / باسورد)."""
    return PASS_RE.findall(text or "")


def wanted_file(msg, exts) -> bool:
    f = msg.file
    if not f:
        return False
    name = (f.name or "").lower()
    if any(name.endswith(e) for e in exts):
        return True
    return ".txt" in exts and f.mime_type == "text/plain"


def filter_peer_sets(target):
    """Peer id sets manually included in / excluded from the folder."""
    explicit = {utils.get_peer_id(p) for p in list(target.include_peers) + list(target.pinned_peers)}
    excluded = {utils.get_peer_id(p) for p in target.exclude_peers}
    return explicit, excluded


def dialog_in_filter(target, d, explicit, excluded):
    """Is the dialog inside the folder? (manually or by type rules)"""
    pid = d.id  # marked id form (same as get_peer_id)
    if pid in excluded:
        return False
    if pid in explicit:
        return True
    e = d.entity
    is_user = d.is_user
    is_bot = is_user and getattr(e, "bot", False)
    return (
        (target.groups and d.is_group)
        or (target.broadcasts and d.is_channel and not d.is_group)
        or (target.bots and is_bot)
        or (target.contacts and is_user and not is_bot and getattr(e, "contact", False))
        or (target.non_contacts and is_user and not is_bot and not getattr(e, "contact", False))
    )


async def folder_chats(client, folder_title):
    """Return the list of dialogs inside a folder by name."""
    res = await client(GetDialogFiltersRequest())
    filters = getattr(res, "filters", res)
    wanted = " ".join(folder_title.split()).lower()
    target = None
    for f in filters:
        if isinstance(f, DialogFilter) and " ".join(title_text(f.title).split()).lower() == wanted:
            target = f
            break
    if not target:
        names = [title_text(f.title) for f in filters if isinstance(f, DialogFilter)]
        raise FolderNotFound(f"Folder '{folder_title}' not found. Available: {names}")

    explicit, excluded = filter_peer_sets(target)
    chats = {}
    async for d in client.iter_dialogs(archived=None):
        if dialog_in_filter(target, d, explicit, excluded):
            chats[d.id] = d
    return list(chats.values())


async def sync_chat(client, entity, chat_name, chat_dir, state, state_file, args, log, cutoff, max_mb, exts, on_progress=None):
    """Download new files from one chat and update state. Returns file count.

    Downloads run in parallel (semaphore-limited) - one Telegram stream is slow,
    but several concurrent streams multiply the total throughput.
    on_progress(chat_name, done, found) is called as counters change.
    """
    key = str(utils.get_peer_id(entity))
    last_id = state.get(key, 0)
    new_last = last_id
    total = 0
    found = 0
    scanned = 0
    scan_from = last_id
    sem = asyncio.Semaphore(3)  # 3 concurrent downloads
    pending = []
    failed = []  # retried once more at the end with a fresh file reference

    async def download_one(msg, fname, target, passwords):
        nonlocal total
        size_mb = (msg.file.size or 0) / 1048576
        async with sem:
            log.info("Downloading %s (%.1f MB)...", fname, size_mb)
            last_pct = [-10]  # progress log every 10% for large files
            last_done = [0]

            def progress(done, total_bytes):
                STATS.add_mb((done - last_done[0]) / 1048576)
                last_done[0] = done
                if total_bytes:
                    pct = int(done * 100 / total_bytes)
                    STATS.update(f"{chat_name} | {pct}% {fname}")
                    if pct >= last_pct[0] + 10:
                        last_pct[0] = pct
                        log.info("  %d%% of %s", pct, fname)

            for retry in range(3):
                try:
                    await msg.download_media(
                        file=str(target),
                        progress_callback=progress if size_mb >= 20 else None,
                    )
                    break
                except FloodWaitError as e:
                    log.warning("FloodWait %ss - waiting", e.seconds)
                    STATS.update(f"FloodWait {e.seconds}s")
                    await asyncio.sleep(e.seconds + 1)
                except Exception as e:
                    # file reference probably expired (long queues) - get a fresh one
                    log.warning("Download attempt failed %s: %s - refreshing reference", fname, e)
                    try:
                        fresh = await client.get_messages(entity, ids=msg.id)
                        if fresh and fresh.file:
                            msg = fresh
                            continue
                    except Exception:
                        pass
                    failed.append((msg.id, fname, target, passwords))
                    return
            else:
                failed.append((msg.id, fname, target, passwords))
                return
            log.info("Downloaded %s", target)
            if size_mb < 20:  # small files have no progress callback
                STATS.add_mb(size_mb)
            if passwords:
                with (chat_dir / "_passwords.txt").open("a", encoding="utf-8") as fh:
                    fh.write(f"{fname}\t{' | '.join(passwords)}\n")
                log.info("Saved password for %s to _passwords.txt", fname)
            total += 1
            STATS.total += 1
            STATS.update()
            if on_progress:
                try:
                    await on_progress(chat_name, total, found)
                except Exception:
                    pass

    for attempt in range(2):  # one retry after FloodWait
        try:
            async for msg in client.iter_messages(
                entity, filter=InputMessagesFilterDocument, min_id=scan_from, reverse=True
            ):
                new_last = max(new_last, msg.id)
                scanned += 1
                if scanned % 1000 == 0:
                    log.info("Scanning %s ... %d messages so far", chat_name, scanned)
                    STATS.update(f"{chat_name} | scanning {scanned} msgs")
                if last_id == 0 and cutoff and msg.date < cutoff:
                    continue  # first run: only the last N days (when FIRST_RUN_DAYS > 0)
                if not wanted_file(msg, exts):
                    continue
                if max_mb > 0 and msg.file.size and msg.file.size > max_mb * 1024 * 1024:
                    log.warning("Skipping large file: %s (%.1f MB)", msg.file.name, msg.file.size / 1048576)
                    continue
                fname = f"{msg.date:%Y-%m-%d}_{msg.id}_{safe(msg.file.name or 'file.txt')}"
                target = chat_dir / fname
                if target.exists():
                    expected = msg.file.size or 0
                    if not expected or target.stat().st_size >= expected:
                        continue
                    log.warning(
                        "Incomplete file, re-downloading: %s (%.1f of %.1f MB)",
                        fname, target.stat().st_size / 1048576, expected / 1048576,
                    )
                passwords = extract_passwords(msg.message)
                if args.dry_run:
                    log.info("[dry-run] %s", target)
                    if passwords:
                        log.info("[dry-run] password for %s: %s", fname, " | ".join(passwords))
                    total += 1
                    continue
                chat_dir.mkdir(parents=True, exist_ok=True)
                found += 1
                pending.append(asyncio.ensure_future(download_one(msg, fname, target, passwords)))
                if on_progress:
                    try:
                        await on_progress(chat_name, total, found)
                    except Exception:
                        pass
            break
        except FloodWaitError as e:
            log.warning("FloodWait %ss - waiting", e.seconds)
            STATS.update(f"FloodWait {e.seconds}s")
            scan_from = new_last  # resume from the last processed message
            await asyncio.sleep(e.seconds + 1)
        except Exception as e:  # one failing chat must not stop the rest
            log.error("Error in '%s': %s", chat_name, e)
            break
    if pending:
        await asyncio.gather(*pending)
    # last pass: retry failed downloads with fresh file references
    for msg_id, fname, target, passwords in list(failed):
        try:
            fresh = await client.get_messages(entity, ids=msg_id)
            if fresh and fresh.file:
                log.info("Retrying failed download: %s", fname)
                await download_one(fresh, fname, target, passwords)
        except Exception as e:
            log.error("Final retry failed %s: %s", fname, e)
    if not args.dry_run:
        async with STATE_LOCK:
            state[key] = new_last
            state_file.write_text(json.dumps(state), encoding="utf-8")
    return total


async def sync(args):
    load_env()
    api_id = int(cfg("TG_API_ID", required=True))
    api_hash = cfg("TG_API_HASH", required=True)
    session = str(BASE / cfg("TG_SESSION", "tg_session"))
    out_dir = Path(cfg("OUT_DIR", str(BASE / "downloads")))
    state_file = Path(cfg("STATE_FILE", str(BASE / "state.json")))
    folders = [x.strip() for x in cfg("TG_FOLDERS", "").split(",") if x.strip()]
    channels = [x.strip() for x in cfg("TG_CHANNELS", "").split(",") if x.strip()]
    first_run_days = int(cfg("FIRST_RUN_DAYS", "1"))
    max_mb = int(cfg("MAX_FILE_MB", "0"))  # 0 = unlimited (5 GB files and more are fine)
    exts = tuple(
        "." + x.strip().lower().lstrip(".")
        for x in cfg("TG_EXTENSIONS", "txt").split(",")
        if x.strip()
    ) or (".txt",)

    stream = logging.StreamHandler()
    stream.setFormatter(ColorFormatter("%(asctime)s %(levelname)s %(message)s"))
    file_handler = logging.FileHandler(BASE / "sync.log", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[stream, file_handler])
    log = logging.getLogger("tg_sync")

    async with TelegramClient(session, api_id, api_hash) as client:
        if args.login:
            me = await client.get_me()
            log.info("Signed in as %s. Session file saved.", me.first_name)
            os.chmod(session + ".session", 0o600)
            return
        if not await client.is_user_authorized():
            sys.exit("Not signed in. Run: python3 tg_txt_sync.py --login")

        me = await client.get_me()
        account = f"@{me.username}" if me.username else (me.first_name or "account")
        STATS.base = f"TG Sync | {account}"
        STATS.update("starting")
        log.info("Account: %s", account)

        notify_on = cfg("TG_NOTIFY", "1").lower() not in ("0", "no", "false") and not args.dry_run
        notifier = Notifier(client, notify_on, cfg("TG_NOTIFY_TO", "me"))
        started = asyncio.get_event_loop().time()
        await notifier.start(f"🚀 TG Sync started — {account} — {datetime.now():%Y-%m-%d %H:%M}")

        if args.list_folders:
            res = await client(GetDialogFiltersRequest())
            for f in getattr(res, "filters", res):
                if isinstance(f, DialogFilter):
                    print("-", title_text(f.title))
            return

        if not folders and not channels:
            sys.exit("Set TG_FOLDERS and/or TG_CHANNELS in .env")

        state = {}
        if state_file.exists():
            try:
                state = json.loads(state_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                log.warning("State file %s is corrupt - starting fresh", state_file)
                state = {}
        # FIRST_RUN_DAYS=0 means the first run downloads the whole archive
        cutoff = datetime.now(timezone.utc) - timedelta(days=first_run_days) if first_run_days > 0 else None
        total = 0
        seen = set()  # no duplicates if a chat is in both a folder and TG_CHANNELS

        for folder in folders:
            try:
                chats = await folder_chats(client, folder)
            except FolderNotFound as e:
                log.error("%s", e)
                continue  # a missing folder must not stop the others
            log.info("Folder '%s': %d chats", folder, len(chats))
            STATS.update(f"folder {folder}")
            for d in chats:
                pid = utils.get_peer_id(d.entity)
                if pid in seen:
                    continue
                seen.add(pid)
                got = await sync_chat(
                    client, d.entity, d.name, out_dir / safe(folder) / safe(d.name),
                    state, state_file, args, log, cutoff, max_mb, exts,
                )
                total += got
                if got:
                    await notifier.add(f"📂 {folder}/{d.name}: {got} files")

        for ch in channels:
            STATS.update(f"resolving {ch}")
            try:
                entity = await client.get_entity(int(ch) if ch.lstrip("-").isdigit() else ch)
            except Exception:
                entity = None
                if ch.lstrip("-").isdigit():  # look it up in the dialogs by id
                    async for d in client.iter_dialogs(archived=None):
                        if d.id == int(ch):
                            entity = d.entity
                            break
            if entity is None:
                log.error("Cannot reach channel '%s' - make sure you are a member", ch)
                continue
            pid = utils.get_peer_id(entity)
            if pid in seen:
                continue
            seen.add(pid)
            name = getattr(entity, "title", None) or getattr(entity, "username", None) or ch
            log.info("Channel '%s' (%s)", name, ch)
            STATS.update(name)
            got = await sync_chat(
                client, entity, name, out_dir / safe(name),
                state, state_file, args, log, cutoff, max_mb, exts,
            )
            total += got
            if got:
                await notifier.add(f"📂 {name}: {got} files")

        elapsed = int(asyncio.get_event_loop().time() - started)
        STATS.update("done")
        log.info("Done. New files: %d", total)
        await notifier.add(
            f"✅ Done — {total} new files in {elapsed // 60}m {elapsed % 60}s", force=True
        )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--login", action="store_true")
    p.add_argument("--list-folders", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    asyncio.run(sync(p.parse_args()))


if __name__ == "__main__":
    main()
