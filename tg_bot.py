#!/usr/bin/env python3
"""
tg_bot.py - Telegram-controlled sync daemon (personal account via Telethon)

Runs 24/7, owns the Telegram session, and lets you control everything
from Saved Messages on your phone:

  /add <id|@username>   - add a channel, replies with its name, downloads its archive
  /remove <id|@username> - remove a channel from the sync list
  /list                 - show configured channels/folders
  /status               - live progress: files, disk usage, what is running
  /sync                 - force a full sync right now
  /help                 - show these commands

Also runs the daily sync automatically at DAILY_TIME (default 03:00) and sends
the report to Saved Messages. Only ONE Telegram process may run at a time
(session lock) - do not run tg_txt_sync.py while this daemon is up.
"""
import asyncio
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from telethon import TelegramClient, events, utils

from tg_txt_sync import (
    BASE, STATS, ColorFormatter, FolderNotFound, Notifier, cfg,
    folder_chats, load_env, safe, set_title, sync_chat,
)

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

stream = logging.StreamHandler()
stream.setFormatter(ColorFormatter("%(asctime)s %(levelname)s %(message)s"))
file_handler = logging.FileHandler(BASE / "sync.log", encoding="utf-8")
file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[stream, file_handler])
log = logging.getLogger("tg_bot")

HELP = """🤖 TG Sync commands:
/add <id|@username> — add a channel & download its archive
/remove <id|@username> — remove a channel from the list
/list — show configured channels
/status — files, disk usage, current activity
/sync — force a full sync now
/help — this message"""


def update_env(key, value):
    env = BASE / ".env"
    lines = env.read_text(encoding="utf-8").splitlines() if env.exists() else []
    out, done = [], False
    for line in lines:
        if line.strip().startswith(key + "="):
            line = f"{key}={value}"
            done = True
        out.append(line)
    if not done:
        out.append(f"{key}={value}")
    env.write_text("\n".join(out) + "\n", encoding="utf-8")


class Daemon:
    def __init__(self):
        load_env()
        self.client = TelegramClient(
            str(BASE / cfg("TG_SESSION", "tg_session")),
            int(cfg("TG_API_ID", required=True)),
            cfg("TG_API_HASH", required=True),
        )
        self.out_dir = Path(cfg("OUT_DIR", str(BASE / "downloads")))
        self.state_file = Path(cfg("STATE_FILE", str(BASE / "state.json")))
        self.channels = [x.strip() for x in cfg("TG_CHANNELS", "").split(",") if x.strip()]
        self.folders = [x.strip() for x in cfg("TG_FOLDERS", "").split(",") if x.strip()]
        self.max_mb = int(cfg("MAX_FILE_MB", "0"))
        self.first_run_days = int(cfg("FIRST_RUN_DAYS", "0"))
        self.daily_time = cfg("DAILY_TIME", "03:00")
        self.exts = tuple(
            "." + x.strip().lower().lstrip(".")
            for x in cfg("TG_EXTENSIONS", "txt").split(",")
            if x.strip()
        ) or (".txt",)
        self.args = SimpleNamespace(dry_run=False)
        self.state = self.load_state()
        self.names = {}          # peer id -> display name (cache)
        self.full_sync_running = False
        self.activity = "starting"
        self.me = None

    def load_state(self):
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                log.warning("State file is corrupt - starting fresh")
        return {}

    def cutoff(self):
        return (
            datetime.now().astimezone() - timedelta(days=self.first_run_days)
            if self.first_run_days > 0
            else None
        )

    async def resolve(self, ch):
        """Resolve a channel id/username to (entity, name) or (None, None)."""
        try:
            entity = await self.client.get_entity(int(ch) if ch.lstrip("-").isdigit() else ch)
        except Exception:
            entity = None
            if ch.lstrip("-").isdigit():
                async for d in self.client.iter_dialogs(archived=None):
                    if d.id == int(ch):
                        entity = d.entity
                        break
        if entity is None:
            return None, None
        name = getattr(entity, "title", None) or getattr(entity, "username", None) or ch
        self.names[utils.get_peer_id(entity)] = name
        return entity, name

    async def sync_entity(self, entity, name, dest, notifier=None, label=None):
        async def on_progress(chat, done, found):
            if notifier:
                remaining = found - done
                await notifier.set(
                    name,
                    f"📂 {label or name}: ✅ {done} downloaded"
                    + (f" • ⏳ {remaining} in queue" if remaining else ""),
                )

        self.activity = name
        STATS.update(name)
        got = await sync_chat(
            self.client, entity, name, dest, self.state, self.state_file,
            self.args, log, self.cutoff(), self.max_mb, self.exts,
            on_progress=on_progress if notifier else None,
        )
        if notifier:
            await notifier.set(name, f"📂 {label or name}: ✅ {got} files - done", force=True)
        return got

    async def run_full_sync(self, reason="manual"):
        if self.full_sync_running:
            return None
        self.full_sync_running = True
        notifier = Notifier(self.client, True, "me")
        started = asyncio.get_event_loop().time()
        await notifier.start(
            f"🚀 Sync started ({reason}) — {datetime.now():%Y-%m-%d %H:%M}"
        )
        total = 0
        seen = set()
        try:
            for folder in self.folders:
                try:
                    chats = await folder_chats(self.client, folder)
                except FolderNotFound as e:
                    log.error("%s", e)
                    continue
                for d in chats:
                    pid = utils.get_peer_id(d.entity)
                    if pid in seen:
                        continue
                    seen.add(pid)
                    self.names[pid] = d.name
                    total += await self.sync_entity(
                        d.entity, d.name, self.out_dir / safe(folder) / safe(d.name),
                        notifier, label=f"{folder}/{d.name}",
                    )
            channel_sem = asyncio.Semaphore(6)  # all channels at once = different DCs

            async def run_channel(ch):
                async with channel_sem:
                    entity, name = await self.resolve(ch)
                    if entity is None:
                        log.error("Cannot reach channel '%s'", ch)
                        await notifier.add(f"⚠️ cannot reach {ch}")
                        return 0
                    pid = utils.get_peer_id(entity)
                    if pid in seen:
                        return 0
                    seen.add(pid)
                    return await self.sync_entity(entity, name, self.out_dir / safe(name), notifier)

            results = await asyncio.gather(*(run_channel(ch) for ch in list(self.channels)))
            total += sum(results)
        except Exception as e:
            log.error("Sync failed: %s", e)
            await notifier.add(f"❌ error: {e}", force=True)
        elapsed = int(asyncio.get_event_loop().time() - started)
        self.activity = "idle"
        STATS.update("done")
        log.info("Sync done (%s). New files: %d", reason, total)
        await notifier.add(
            f"✅ Done — {total} new files in {elapsed // 60}m {elapsed % 60}s", force=True
        )
        self.full_sync_running = False
        return total

    def disk_stats(self):
        files = 0
        size = 0
        if self.out_dir.exists():
            for p in self.out_dir.rglob("*"):
                if p.is_file():
                    files += 1
                    size += p.stat().st_size
        return files, size / (1024 ** 3)

    def next_run_text(self):
        try:
            hh, mm = (int(x) for x in self.daily_time.split(":"))
        except ValueError:
            return self.daily_time
        now = datetime.now()
        nxt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
        return f"{nxt:%Y-%m-%d %H:%M}"

    async def cmd_add(self, event, arg):
        if not arg:
            await event.reply("Usage: /add <id|@username>")
            return
        msg = await event.reply(f"🔎 resolving {arg} ...")
        entity, name = await self.resolve(arg)
        if entity is None:
            await msg.edit(f"❌ cannot reach '{arg}' - make sure you are a member")
            return
        pid = utils.get_peer_id(entity)
        key = str(pid)
        already = arg in self.channels or key in self.channels
        if not already:
            self.channels.append(key)  # canonical marked id
            update_env("TG_CHANNELS", ",".join(self.channels))
        await msg.edit(
            f"✅ {'already in list' if already else 'added'}: {name} ({key})\n"
            f"⬇️ downloading archive..."
        )
        got = await self.sync_entity(entity, name, self.out_dir / safe(name))
        await msg.edit(
            f"✅ {name} ({key})\n⬇️ done — {got} new files"
            + ("" if already else " — saved to TG_CHANNELS")
        )

    async def cmd_remove(self, event, arg):
        if not arg:
            await event.reply("Usage: /remove <id|@username>")
            return
        removed = [c for c in self.channels if c == arg or c.lstrip("-") == arg.lstrip("-")]
        self.channels = [c for c in self.channels if c not in removed]
        update_env("TG_CHANNELS", ",".join(self.channels))
        name = self.names.get(int(removed[0]), removed[0]) if removed else None
        await event.reply(
            f"🗑 removed {name or arg}" if removed else f"ℹ️ {arg} was not in the list"
        )

    async def cmd_list(self, event):
        lines = ["📋 Configured channels:"]
        for ch in self.channels:
            name = self.names.get(int(ch)) if ch.lstrip("-").isdigit() else None
            lines.append(f"• {ch}" + (f" — {name}" if name else ""))
        if self.folders:
            lines.append("📁 Folders: " + ", ".join(self.folders))
        await event.reply("\n".join(lines))

    async def cmd_status(self, event):
        files, gb = self.disk_stats()
        await event.reply(
            f"📊 Status\n"
            f"• activity: {self.activity}\n"
            f"• full sync running: {'yes' if self.full_sync_running else 'no'}\n"
            f"• files on disk: {files} ({gb:.1f} GB)\n"
            f"• channels tracked: {len(self.state)}\n"
            f"• channels configured: {len(self.channels)}\n"
            f"• next daily run: {self.next_run_text()}"
        )

    async def handle_command(self, event):
        text = (event.raw_text or "").strip()
        cmd, _, arg = text.partition(" ")
        cmd, arg = cmd.lower(), arg.strip()
        log.info("Command received: %s %s", cmd, arg)
        if cmd == "/add":
            asyncio.create_task(self.cmd_add(event, arg))
        elif cmd == "/remove":
            await self.cmd_remove(event, arg)
        elif cmd == "/list":
            await self.cmd_list(event, arg)
        elif cmd == "/status":
            await self.cmd_status(event)
        elif cmd == "/sync":
            if self.full_sync_running:
                await event.reply("⏳ a sync is already running")
            else:
                await event.reply("🚀 starting full sync now...")
                asyncio.create_task(self.run_full_sync("manual"))
        elif cmd in ("/help", "/start"):
            await event.reply(HELP)

    async def scheduler(self):
        while True:
            try:
                hh, mm = (int(x) for x in self.daily_time.split(":"))
            except ValueError:
                hh, mm = 3, 0
            now = datetime.now()
            nxt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if nxt <= now:
                nxt += timedelta(days=1)
            wait = (nxt - now).total_seconds()
            log.info("Next daily sync at %s (in %.1f h)", nxt, wait / 3600)
            await asyncio.sleep(wait)
            await self.run_full_sync("daily")

    async def run(self):
        await self.client.start()
        self.me = await self.client.get_me()
        account = f"@{self.me.username}" if self.me.username else (self.me.first_name or "account")
        STATS.base = f"TG Bot | {account}"
        STATS.update("listening")
        set_title(f"TG Bot | {account} | listening")
        log.info("Daemon up as %s — commands via Saved Messages", account)

        @self.client.on(events.NewMessage)
        async def on_message(event):
            if event.out and event.chat_id == self.me.id:
                text = (event.raw_text or "").strip()
                if text.startswith("/"):
                    try:
                        await self.handle_command(event)
                    except Exception as e:
                        log.error("Command error: %s", e)
                        await event.reply(f"❌ error: {e}")

        await self.client.send_message(
            "me", f"🤖 TG Sync daemon online — {account}\n{HELP}"
        )
        # resume/continue the full archive sync right away, then daily
        asyncio.create_task(self.run_full_sync("startup"))
        asyncio.create_task(self.scheduler())
        await self.client.run_until_disconnected()


def main():
    daemon = Daemon()
    asyncio.run(daemon.run())


if __name__ == "__main__":
    main()
