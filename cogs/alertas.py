import discord
from discord.ext import commands
import os
import asyncio
from telethon import TelegramClient, events
from dotenv import load_dotenv

load_dotenv()

# ===== TELEGRAM CONFIG =====
api_id = int(os.getenv("TELEGRAM_API_ID"))
api_hash = os.getenv("TELEGRAM_API_HASH")
telegram_channel = int(os.getenv("TELEGRAM_CHANNEL_ID"))

# ===== DISCORD CONFIG =====
DISCORD_ALERTS_CHANNEL = int(os.getenv("ALERTS_CHANNEL_ID"))

class Alertas(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.telegram_client = TelegramClient("telegram_session", api_id, api_hash)
        self.bot.loop.create_task(self.start_telegram())

    async def start_telegram(self):

        await self.telegram_client.start()

        @self.telegram_client.on(events.NewMessage(chats=telegram_channel))
        async def handler(event):

            channel = self.bot.get_channel(DISCORD_ALERTS_CHANNEL)

            if not channel:
                return

            texto = event.message.text
            archivo = None

            if event.message.media:
                archivo = await event.message.download_media()

            if archivo:
                await channel.send(content=texto if texto else "", file=discord.File(archivo))
                os.remove(archivo)
            else:
                if texto:
                    await channel.send(texto)

        print("📡 Escuchando canal de Telegram...")

        await self.telegram_client.run_until_disconnected()


async def setup(bot):
    await bot.add_cog(Alertas(bot))