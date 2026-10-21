"""Averigua tu TELEGRAM_CHAT_ID y manda un mensaje de prueba.

Uso:
  1. Escribe cualquier cosa a tu bot en Telegram (por ejemplo "hola").
  2. Ejecuta:  python scripts/telegram_chat_id.py TU_TOKEN_DEL_BOT
"""
import sys

import requests


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    token = sys.argv[1].strip()
    r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=30).json()
    if not r.get("ok"):
        print("El token no es válido:", r.get("description"))
        return 1
    chats = {}
    for u in r.get("result", []):
        msg = u.get("message") or u.get("channel_post") or {}
        chat = msg.get("chat") or {}
        if chat:
            chats[chat["id"]] = chat.get("first_name") or chat.get("title") or ""
    if not chats:
        print("No hay mensajes. Escribe algo a tu bot en Telegram y vuelve a ejecutar esto.")
        return 1
    for chat_id, nombre in chats.items():
        print(f"TELEGRAM_CHAT_ID = {chat_id}   ({nombre})")
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat_id, "text": "🌸 ¡Radar de oposiciones conectado!"},
                      timeout=30)
    print("Te he mandado un mensaje de prueba. Guarda ese número como secreto en GitHub.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
