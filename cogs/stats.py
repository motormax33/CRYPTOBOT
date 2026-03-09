import discord
from discord.ext import commands, tasks
import requests
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
import pytz

load_dotenv()

CANAL_STATS_ID = int(os.getenv("CANAL_STATS_ID"))
UPDATE_SECONDS = 60

class Stats(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.message = None
        self.next_update = None
        self.last_prices = None

        self.coins = [
            "bitcoin", "ethereum", "litecoin", "solana",
            "binancecoin", "ripple", "tether"
        ]

        # nombres de emojis en tu servidor
        self.emoji_names = {
            "bitcoin": "70506bitcoin",
            "solana": "65771solana",
            "ethereum": "18119ethereum",
            "ripple": "9643xrp",
            "binancecoin": "6798bnb",
            "tether": "6121tether",
            "litecoin": "4887ltc"
        }

    def get_emoji(self, coin):
        name = self.emoji_names.get(coin)
        emoji = discord.utils.get(self.bot.emojis, name=name)
        return str(emoji) if emoji else "🪙"

    def fetch_prices(self):
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {
            "ids": ",".join(self.coins),
            "vs_currencies": "usd",
            "include_24hr_change": "true"
        }

        try:
            r = requests.get(url, params=params, timeout=10)
            return r.json()
        except:
            return None

    def create_embed(self):

        embed = discord.Embed(
            title="🚀 CRYPTO MARKET LIVE",
            color=0x2f3136
        )

        if not self.last_prices:
            embed.description = "⌛ Actualizando..."
            return embed

        name_map = {
            "bitcoin": "BTC",
            "ethereum": "ETH",
            "litecoin": "LTC",
            "solana": "SOL",
            "binancecoin": "BNB",
            "ripple": "XRP",
            "tether": "USDT"
        }

        for coin in self.coins:

            data = self.last_prices.get(coin)
            if not data:
                continue

            price = data["usd"]
            change = data.get("usd_24h_change", 0)

            icon = self.get_emoji(coin)

            trend = "📈" if change >= 0 else "📉"

            embed.add_field(
                name=f"{icon} {name_map[coin]}",
                value=f"**${price:,.2f}**\n`{change:+.2f}%` {trend}",
                inline=True
            )

        tz = pytz.timezone("Europe/Madrid")
        now_es = datetime.now(tz).strftime("%H:%M:%S")

        remaining = 0
        if self.next_update:
            diff = (self.next_update - datetime.utcnow()).total_seconds()
            remaining = int(max(0, diff))

        embed.add_field(name=" ", value="────────────────", inline=False)

        embed.add_field(
            name="🕒 Hora Local (ES)",
            value=f"`{now_es}`",
            inline=True
        )

        embed.add_field(
            name="⏱ Actualizacion en",
            value=f"`{remaining}s`",
            inline=True
        )

        return embed

    @discord.app_commands.command(name="stats", description="Panel de criptos")
    async def stats(self, interaction: discord.Interaction):

        await interaction.response.defer(ephemeral=True)

        canal = self.bot.get_channel(CANAL_STATS_ID)

        if not canal:
            return await interaction.followup.send("❌ Canal no encontrado")

        self.last_prices = self.fetch_prices()
        self.next_update = datetime.utcnow() + timedelta(seconds=UPDATE_SECONDS)

        self.message = await canal.send(embed=self.create_embed())

        if not self.update_prices.is_running():
            self.update_prices.start()

        await interaction.followup.send("✅ Panel creado")

    @tasks.loop(seconds=2)
    async def update_prices(self):

        if not self.message:
            return

        now = datetime.utcnow()

        if not self.next_update or now >= self.next_update:
            self.last_prices = self.fetch_prices()
            self.next_update = now + timedelta(seconds=UPDATE_SECONDS)

        try:
            await self.message.edit(embed=self.create_embed())
        except:
            pass

    @update_prices.before_loop
    async def before_update(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Stats(bot))
