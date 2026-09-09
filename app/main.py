import asyncio
from fastapi import FastAPI
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
import uvicorn
from .config import settings
from .db import init_db
from .bot import router, run_job

api = FastAPI(title="Web2APK Bot")

@api.get("/health")
async def health():
    return {"status": "ok", "service": "web2apk-bot"}

async def run():
    await init_db()
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    run_job.bot = bot

    server = uvicorn.Server(
        uvicorn.Config(api, host="0.0.0.0", port=settings.port, log_level="info")
    )
    await asyncio.gather(
        dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types()),
        server.serve(),
    )

if __name__ == "__main__":
    asyncio.run(run())
