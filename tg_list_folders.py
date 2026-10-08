#!/usr/bin/env python3
"""
tg_list_folders.py - List your Telegram folders and channels to fill TG_FOLDERS / TG_CHANNELS in .env

Usage:
  python3 tg_list_folders.py              # show folders with their chats + a ready TG_FOLDERS line
  python3 tg_list_folders.py --names      # print only the TG_FOLDERS line (for copying)
  python3 tg_list_folders.py --channels   # all channels/groups with ID and username -> channels.txt
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

from colorama import Fore, Style
from colorama import init as colorama_init
from telethon import TelegramClient
from telethon.tl.functions.messages import GetDialogFiltersRequest
from telethon.tl.types import DialogFilter

from tg_txt_sync import dialog_in_filter, filter_peer_sets, title_text

BASE = Path(__file__).resolve().parent

colorama_init()

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


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


async def main(args):
    load_env()
    api_id = int(cfg("TG_API_ID", required=True))
    api_hash = cfg("TG_API_HASH", required=True)
    session = str(BASE / cfg("TG_SESSION", "tg_session"))

    async with TelegramClient(session, api_id, api_hash) as client:
        if not await client.is_user_authorized():
            sys.exit("Not signed in. Run first: python3 tg_txt_sync.py --login")

        if args.channels:
            out_file = BASE / "channels.txt"
            count = 0
            with out_file.open("w", encoding="utf-8") as fh:
                fh.write("id\tusername\ttype\tname\n")
                async for d in client.iter_dialogs(archived=None):
                    if not d.is_channel:  # channels and groups only, no private chats
                        continue
                    uname = getattr(d.entity, "username", None)
                    kind = "group" if d.is_group else "channel"
                    fh.write(f"{d.id}\t{'@' + uname if uname else '-'}\t{kind}\t{d.name}\n")
                    color = Fore.CYAN if d.is_group else Fore.GREEN
                    print(f"{Fore.YELLOW}{d.id}{Style.RESET_ALL}\t"
                          f"{Fore.MAGENTA}{'@' + uname if uname else '-'}{Style.RESET_ALL}\t"
                          f"{color}{kind}{Style.RESET_ALL}\t{d.name}")
                    count += 1
            print(f"\n{Fore.GREEN}Saved {count} channels/groups to {out_file}{Style.RESET_ALL}")
            print("Put the ones you want in .env by id or username, e.g.:")
            print(f"{Fore.YELLOW}TG_CHANNELS=-1001234567890,@somechannel{Style.RESET_ALL}")
            return

        res = await client(GetDialogFiltersRequest())
        filters = [f for f in getattr(res, "filters", res) if isinstance(f, DialogFilter)]
        names = [title_text(f.title) for f in filters]

        if args.names:
            print("TG_FOLDERS=" + ",".join(names))
            return

        # one pass over the dialogs, distributed across all folders
        peer_sets = {i: filter_peer_sets(f) for i, f in enumerate(filters)}
        members = {i: [] for i in range(len(filters))}
        async for d in client.iter_dialogs(archived=None):
            for i, f in enumerate(filters):
                explicit, excluded = peer_sets[i]
                if dialog_in_filter(f, d, explicit, excluded):
                    members[i].append(d.name)

        print("Available folders:\n")
        for i, name in enumerate(names):
            chats = members[i]
            print(f"{Fore.CYAN}📁 {name}{Style.RESET_ALL}  ({Fore.GREEN}{len(chats)} chats{Style.RESET_ALL})")
            for chat_name in chats:
                print(f"   - {chat_name}")
            print()
        print("Copy this line into .env (keep only the folders you want):")
        print(f"{Fore.YELLOW}TG_FOLDERS={','.join(names)}{Style.RESET_ALL}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--names", action="store_true", help="print only the TG_FOLDERS line")
    p.add_argument("--channels", action="store_true", help="all channels/groups with IDs -> channels.txt")
    asyncio.run(main(p.parse_args()))
