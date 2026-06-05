#!/usr/bin/env python3
"""Telethon 로그인 - client.start() 사용"""
import os, sys, json, asyncio, base64, argparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(SCRIPT_DIR, ".telethon.env")
SESSION_PATH = os.path.join(SCRIPT_DIR, "telethon_session")
HERMES_CHAT = 8992344528  # 브랜업업무봇

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

async def send_and_wait(message: str, timeout: int = 120):
    api_id, api_hash, phone = get_auth()
    client = TelegramClient(SESSION_PATH, api_id, api_hash)
    
    responses = []
    last_msg_time = [0]
    done = asyncio.Event()
    
    @client.on(events.NewMessage(chats=HERMES_CHAT, incoming=True))
    async def handler(event):
        nonlocal responses
        if event.is_private:
            responses.append(event.message.text)
            last_msg_time[0] = asyncio.get_event_loop().time()
    
    await client.start(phone=phone)
    
    # 봇 엔티티 먼저 확보
    bot_entity = await client.get_entity(HERMES_CHAT)
    await client.send_message(bot_entity, message)
    
    # 마지막 메시지 후 5초간 새 메시지 없으면 종료
    try:
        end_time = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < end_time:
            await asyncio.sleep(1)
            if responses and (asyncio.get_event_loop().time() - last_msg_time[0] > 5):
                break
        
        if responses:
            # 마지막 응답 출력
            print(json.dumps({"ok": True, "response": responses[-1]}, ensure_ascii=False))
        else:
            print(json.dumps({"ok": True, "response": None, "note": f"{timeout}초 내 응답 없음"}, ensure_ascii=False))
    except asyncio.TimeoutError:
        pass
    finally:
        await client.disconnect()

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--login", action="store_true")
    p.add_argument("--msg", type=str)
    p.add_argument("--timeout", type=int, default=120)
    args = p.parse_args()
    
    if args.login:
        asyncio.run(do_login())
    elif args.msg:
        asyncio.run(send_and_wait(args.msg, args.timeout))
    else:
        print("사용법: --login 또는 --msg '메시지'")
