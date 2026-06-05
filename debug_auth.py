#!/usr/bin/env python3
"""디버그: send_code_request 응답 확인"""
import os, sys, asyncio, base64

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(SCRIPT_DIR, ".telethon.env")

env = {}
with open(ENV_FILE) as f:
    for line in f:
        line = line.strip()
        if line and '=' in line:
            k, v = line.split('=', 1)
            env[k.strip()] = v.strip().strip('"').strip("'")

api_id = int(env["TELEGRAM_API_ID"])
api_hash = env["TELEGRAM_API_HASH"]
phone = base64.b64decode(env["TELEGRAM_PHONE_B64"]).decode()

from telethon import TelegramClient

async def main():
    client = TelegramClient("debug_session", api_id, api_hash)
    await client.connect()
    result = await client.send_code_request(phone)
    print(f"type: {type(result).__name__}")
    print(f"phone_code_hash: {result.phone_code_hash}")
    print(f"timeout: {result.timeout if hasattr(result, 'timeout') else 'N/A'}")
    # __dict__ 출력
    for k, v in result.__dict__.items():
        if not k.startswith('_'):
            print(f"  {k}: {v}")
    await client.disconnect()

asyncio.run(main())
