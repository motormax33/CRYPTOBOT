import discord
from discord.ext import commands, tasks
import yfinance as yf
import pandas as pd
import numpy as np
import os
import time
from scipy.signal import argrelextrema
from dotenv import load_dotenv

load_dotenv()

SIGNALS_CHANNEL_ID = int(os.getenv("SIGNS_CHANNEL_ID"))

SCAN_SYMBOLS = [
"BTC-USD",
"ETH-USD",
"SOL-USD",
"BNB-USD",
"XRP-USD",
"ADA-USD",
"LINK-USD",
"AVAX-USD",
"DOGE-USD",
"MATIC-USD"
]

# =====================
# INDICADORES
# =====================

def calcular_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))


def calcular_macd(series):
    exp1 = series.ewm(span=12).mean()
    exp2 = series.ewm(span=26).mean()
    macd = exp1 - exp2
    signal = macd.ewm(span=9).mean()
    return macd, signal


def calcular_atr(df, period=14):
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())

    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)

    return true_range.rolling(period).mean().iloc[-1]


# =====================
# SOPORTE / RESISTENCIA
# =====================

def obtener_niveles(df):

    data = df['Close'].tail(50).values

    max_idx = argrelextrema(data, np.greater, order=10)[0]
    min_idx = argrelextrema(data, np.less, order=10)[0]

    resistencia = data[max_idx[-1]] if len(max_idx) > 0 else max(data)
    soporte = data[min_idx[-1]] if len(min_idx) > 0 else min(data)

    return float(soporte), float(resistencia)


# =====================
# COG
# =====================

class Trading(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.cache = {}

        self.market_scanner.start()

    # =====================
    # OBTENER DATOS
    # =====================

    def obtener_datos(self, symbol):

        if symbol in self.cache and (time.time() - self.cache[symbol]["time"] < 60):
            return self.cache[symbol]["data"]

        df = yf.download(symbol, period="60d", interval="1h", progress=False)

        if df.empty or len(df) < 50:
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df['RSI'] = calcular_rsi(df['Close'])
        df['EMA200'] = df['Close'].ewm(span=200).mean()

        df['MACD'], df['MACD_SIGNAL'] = calcular_macd(df['Close'])

        last = df.iloc[-1]
        prev = df.iloc[-2]

        atr = calcular_atr(df)
        soporte, resistencia = obtener_niveles(df)

        datos = {
            "precio": float(last['Close']),
            "rsi": float(last['RSI']),
            "macd": float(last['MACD']),
            "macd_sig": float(last['MACD_SIGNAL']),
            "tendencia": "ALCISTA" if last['Close'] > last['EMA200'] else "BAJISTA",
            "volumen": float(last['Volume']),
            "vol_avg": float(df['Volume'].rolling(20).mean().iloc[-1]),
            "atr": atr,
            "soporte": soporte,
            "resistencia": resistencia
        }

        self.cache[symbol] = {"time": time.time(), "data": datos}

        return datos


    # =====================
    # SCORE AVANZADO
    # =====================

    def calcular_score(self, datos):

        score = 0

        # tendencia
        score += 2 if datos["tendencia"] == "ALCISTA" else -2

        # RSI
        if datos["rsi"] < 35:
            score += 1
        elif datos["rsi"] > 65:
            score -= 1

        # MACD
        score += 1 if datos["macd"] > datos["macd_sig"] else -1

        # ruptura resistencia
        if datos["precio"] > datos["resistencia"]:
            score += 3

        # volumen fuerte
        vol_ratio = datos["volumen"] / (datos["vol_avg"] + 1)

        if vol_ratio > 2:
            score += 1

        return score


    # =====================
    # GENERAR EMBED
    # =====================

    def crear_embed(self, symbol, datos, score):

        decision = "🟢 COMPRAR" if score >= 3 else "🔴 VENDER" if score <= -3 else "🟡 ESPERAR"

        precio = datos["precio"]

        sl = precio - datos["atr"] * 2 if decision == "🟢 COMPRAR" else precio + datos["atr"] * 2
        tp = precio + datos["atr"] * 3 if decision == "🟢 COMPRAR" else precio - datos["atr"] * 3

        rr = abs((tp - precio) / (precio - sl)) if (precio - sl) != 0 else 0

        color = 0x2ecc71 if "COMPRAR" in decision else 0xe74c3c if "VENDER" in decision else 0xf1c40f

        embed = discord.Embed(
            title=f"📊 Señal de Trading: {symbol}",
            color=color
        )

        embed.add_field(name="🎯 Acción", value=decision, inline=True)
        embed.add_field(name="📊 Score", value=f"{score}", inline=True)
        embed.add_field(name="💰 Precio", value=f"${precio:,.2f}", inline=True)

        embed.add_field(name="📉 Soporte", value=f"${datos['soporte']:,.2f}", inline=True)
        embed.add_field(name="📈 Resistencia", value=f"${datos['resistencia']:,.2f}", inline=True)
        embed.add_field(name="📏 ATR", value=f"{datos['atr']:.4f}", inline=True)

        if decision != "🟡 ESPERAR":
            embed.add_field(name="🛡️ Stop Loss", value=f"${sl:,.2f}", inline=True)
            embed.add_field(name="🚀 Take Profit", value=f"${tp:,.2f}", inline=True)
            embed.add_field(name="⚖️ Risk/Reward", value=f"{rr:.2f}", inline=True)

        return embed


    # =====================
    # SCANNER AUTOMÁTICO
    # =====================

    @tasks.loop(minutes=15)
    async def market_scanner(self):

        canal = self.bot.get_channel(SIGNALS_CHANNEL_ID)

        if not canal:
            return

        oportunidades = []

        for symbol in SCAN_SYMBOLS:

            datos = self.obtener_datos(symbol)

            if not datos:
                continue

            score = self.calcular_score(datos)

            oportunidades.append((symbol, score, datos))

            if score >= 5:
                embed = self.crear_embed(symbol, datos, score)
                await canal.send(embed=embed)

        # ranking

        oportunidades.sort(key=lambda x: x[1], reverse=True)

        ranking = "🔥 **TOP OPORTUNIDADES**\n\n"

        for i, (symbol, score, _) in enumerate(oportunidades[:5], start=1):
            ranking += f"{i}️⃣ {symbol} — score {score}\n"

        await canal.send(ranking)


    # =====================
    # SCAN MANUAL
    # =====================

    @discord.app_commands.command(name="scan", description="Escanea el mercado")
    async def scan(self, interaction: discord.Interaction):

        await interaction.response.defer()

        resultados = []

        for symbol in SCAN_SYMBOLS:

            datos = self.obtener_datos(symbol)

            if not datos:
                continue

            score = self.calcular_score(datos)

            resultados.append((symbol, score, datos))

        resultados.sort(key=lambda x: x[1], reverse=True)

        texto = "📊 **Market Scan**\n\n"

        for symbol, score, _ in resultados[:5]:
            texto += f"• {symbol} → score {score}\n"

        await interaction.followup.send(texto)


async def setup(bot):
    await bot.add_cog(Trading(bot))
