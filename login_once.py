#!/usr/bin/env python3
"""Telethon 로그인 - 코드를 명령줄로 받음"""
import os, sys, asyncio, base64

if len(sys.argv) < 2:
    print("사용법: python3 login_once.py <인증코드>")
    sys.exit(1)

code = sys.argv[1]

api_id = int(os.environ["TELEGRAM_API_ID"])
api_hash = os.environ["TELEGRAM_API_HASH"]
phone = base64.b64decode(os.environ["TELEGRAM_PHONE_B64"]).decode()

from telethon import TelegramClient

async def main():
    client = TelegramClient("telethon_session", api_id, api_hash)
    await client.connect()
    sent = await client.send_code_request(phone)
    await client.sign_in(phone=phone, code=code, phone_code_hash=sent.phone_code_hash)
    me = await client.get_me()
    print(f"OK: {me.first_name} (@{me.username})")
    await client.disconnect()

asyncio.run(main())
