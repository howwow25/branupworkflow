#!/usr/bin/env python3
"""Telethon 로그인 - client.start() 사용"""
import os, sys, asyncio, base64, argparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(SCRIPT_DIR, ".telethon.env")
SESSION_PATH = os.path.join(SCRIPT_DIR, "telethon_session")
HERMES_CHAT = 51271702

def load_env():
    env = {}
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, encoding='utf-8-sig') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    return env

def get_auth():
    env = load_env()
    api_id = int(env.get("TELEGRAM_API_ID", "0"))
    api_hash = env.get("TELEGRAM_API_HASH", "")
    phone = env.get("TELEGRAM_PHONE", "")
    phone_b64 = env.get("TELEGRAM_PHONE_B64", "")
    if phone_b64 and not phone:
        phone = base64.b64decode(phone_b64).decode("utf-8")
    return api_id, api_hash, phone

from telethon import TelegramClient, events

async def do_login():
    api_id, api_hash, phone = get_auth()
    client = TelegramClient(SESSION_PATH, api_id, api_hash)
    try:
        await client.start(phone=phone, code_callback=lambda: input("인증코드: "))
        me = await client.get_me()
        username = f"@{me.username}" if me.username else "(없음)"
        print(f"✅ 로그인 성공: {me.first_name} {username}")
    except Exception as e:
        print(f"❌ 실패: {e}")
    finally:
        await client.disconnect()

async def send_and_wait(message: str, timeout: int = 45):
    api_id, api_hash, phone = get_auth()
    client = TelegramClient(SESSION_PATH, api_id, api_hash)
    
    response_received = asyncio.Event()
    response_text = None

    @client.on(events.NewMessage(chats=HERMES_CHAT, incoming=True))
    async def handler(event):
        nonlocal response_text
        if event.is_private:
            response_text = event.message.text
            response_received.set()

    await client.start(phone=phone)
    await client.send_message(HERMES_CHAT, message)
    
    try:
        await asyncio.wait_for(response_received.wait(), timeout=timeout)
        print(response_text or "(응답 없음)")
    except asyncio.TimeoutError:
        print(f"⏰ {timeout}초 내 응답 없음")
    finally:
        await client.disconnect()

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--login", action="store_true")
    p.add_argument("--msg", type=str)
    p.add_argument("--timeout", type=int, default=45)
    args = p.parse_args()
    
    if args.login:
        asyncio.run(do_login())
    elif args.msg:
        asyncio.run(send_and_wait(args.msg, args.timeout))
    else:
        print("사용법: --login 또는 --msg '메시지'")
