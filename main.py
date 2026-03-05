import discord
from discord.ext import commands
import os
import asyncio
from dotenv import load_dotenv

# Flask para mantener el puerto abierto en Render
from flask import Flask
from threading import Thread

load_dotenv()

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ---------------------------
# SERVIDOR WEB (para Render)
# ---------------------------

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running"

def run():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()

# ---------------------------
# CARGAR COGS
# ---------------------------

async def load_extensions():
    for filename in os.listdir("./cogs"):
        if filename.endswith(".py"):
            await bot.load_extension(f"cogs.{filename[:-3]}")

# ---------------------------
# BOT READY
# ---------------------------

@bot.event
async def on_ready():
    print(f"✅ Bot conectado como {bot.user}")

# ---------------------------
# MAIN
# ---------------------------

async def main():
    async with bot:
        await load_extensions()
        await bot.start(TOKEN)

# iniciar servidor web
keep_alive()

# iniciar bot
asyncio.run(main())