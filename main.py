import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import asyncio
from flask import Flask
from threading import Thread

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

# servidor web para Render
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot activo"


def run_web():
    app.run(host="0.0.0.0", port=10000)


class MainBot(commands.Bot):

    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        cogs = ["cogs.stats", "cogs.limpieza", "cogs.alertas"]

        for cog in cogs:
            try:
                await self.load_extension(cog)
                print(f"✅ {cog} cargado")
            except Exception as e:
                print(f"❌ Error cargando {cog}: {e}")

        await self.tree.sync()
        print("🚀 Comandos sincronizados")

    async def on_ready(self):
        print(f"🤖 Bot conectado como {self.user}")


async def run_bot():
    while True:
        try:
            bot = MainBot()
            async with bot:
                await bot.start(TOKEN)
        except Exception as e:
            print(f"⚠️ Bot detenido: {e}. Reiniciando en 10s")
            await asyncio.sleep(10)


if __name__ == "__main__":

    # iniciar servidor web
    t = Thread(target=run_web)
    t.start()

    asyncio.run(run_bot())
