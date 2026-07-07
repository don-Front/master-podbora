# -*- coding: utf-8 -*-
import os
import sys
import traceback

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.chdir(r"c:\Users\userii1\Downloads\Andrey (подбор, потом удалю)\master-podbora\back\chatbot")
sys.path.insert(0, ".")

try:
    from api.services.rag_service import RAGService

    svc = RAGService()
    bot = svc._get_bot()
    print("bot ok", bot is not None, "config", bot.config is not None if bot else None)
    if bot and bot.config:
        ans = bot.ask("максимальный диаметр UFG-H")
        print("answer:", (ans or "")[:500])
except Exception:
    traceback.print_exc()
