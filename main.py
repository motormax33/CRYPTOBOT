import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import asyncio

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")


class MainBot(commands.Bot):

    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):

        # cargar cogs
        await self.load_extension("cogs.stats")
        await self.load_extension("cogs.trading")
        await self.load_extension("cogs.limpieza")
        await self.load_extension("cogs.alertas")

        await self.tree.sync()

        print("✅ Cogs cargados")

    async def on_ready(self):
        print(f"🤖 Bot conectado como {self.user}")


async def main():
    bot = MainBot()
    async with bot:
        await bot.start(TOKEN)


asyncio.run(main())
