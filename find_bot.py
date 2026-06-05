#!/usr/bin/env python3
"""브랜업 관련 봇/채팅 찾기"""
import os, asyncio, base64

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(SCRIPT_DIR, ".telethon.env")

env = {}
if os.path.exists(ENV_FILE):
    with open(ENV_FILE, encoding='utf-8-sig') as f:
        for line in f:
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")

api_id = int(env.get("TELEGRAM_API_ID", "0"))
api_hash = env.get("TELEGRAM_API_HASH", "")
phone_b64 = env.get("TELEGRAM_PHONE_B64", "")
phone = base64.b64decode(phone_b64).decode("utf-8") if phone_b64 else env.get("TELEGRAM_PHONE", "")

from telethon import TelegramClient

async def main():
    client = TelegramClient(os.path.join(SCRIPT_DIR, "telethon_session"), api_id, api_hash)
    await client.start(phone=phone)
    print("=== 봇/업무 관련 다이얼로그 ===")
    async for d in client.iter_dialogs():
        name = d.name or ""
        if "업무" in name or "봇" in name or "bot" in name.lower() or "branup" in name.lower() or "hermes" in name.lower():
            print(f"ID={d.id} | name={name} | is_user={d.is_user}")
    print("\n=== 전체 검색 완료 ===")
    await client.disconnect()

asyncio.run(main())
