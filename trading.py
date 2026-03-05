import discord
from discord.ext import commands
import yfinance as yf
import pandas as pd
import numpy as np
import aiohttp
import asyncio
import os
import time
from scipy.signal import argrelextrema
from dotenv import load_dotenv

# ============================
# CONFIGURACIÓN
# ============================
load_dotenv()

# ============================
# INDICADORES TÉCNICOS
# ============================
def calcular_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))


def calcular_macd(series):
    exp1 = series.ewm(span=12, adjust=False).mean()
    exp2 = series.ewm(span=26, adjust=False).mean()
    macd = exp1 - exp2
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd, signal


def calcular_atr(df, period=14):
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    return true_range.rolling(14).mean().iloc[-1]


# ============================
# SOPORTES Y RESISTENCIAS
# ============================
def obtener_niveles_clave(df):
    data = df['Close'].tail(50).values
    max_idx = argrelextrema(data, np.greater, order=10)[0]
    min_idx = argrelextrema(data, np.less, order=10)[0]

    resistencia = data[max_idx[-1]] if len(max_idx) > 0 else max(data)
    soporte = data[min_idx[-1]] if len(min_idx) > 0 else min(data)

    return float(soporte), float(resistencia)


# ============================
# DIVERGENCIAS
# ============================
def detectar_divergencias(df):
    close = df['Close'].values
    rsi = df['RSI'].values
    picos = argrelextrema(close, np.greater, order=5)[0]
    valles = argrelextrema(close, np.less, order=5)[0]

    if len(picos) >= 2:
        p1, p2 = picos[-2], picos[-1]
        if close[p2] > close[p1] and rsi[p2] < rsi[p1]:
            return "🔴 BAJISTA"

    if len(valles) >= 2:
        v1, v2 = valles[-2], valles[-1]
        if close[v2] < close[v1] and rsi[v2] > rsi[v1]:
            return "🟢 ALCISTA"

    return "Neutral"


# ============================
# COG PRINCIPAL
# ============================
class Trading(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.cache = {}
        self.session = None

    async def cog_load(self):
        self.session = aiohttp.ClientSession()

    async def cog_unload(self):
        if self.session:
            await self.session.close()

    # ============================
    # OBTENER DATOS
    # ============================
    def obtener_datos(self, symbol):

        if symbol in self.cache and (time.time() - self.cache[symbol]["time"] < 60):
            return self.cache[symbol]["data"]

        df = yf.download(symbol, period="60d", interval="1h", progress=False)

        if df.empty or len(df) < 50:
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df['RSI'] = calcular_rsi(df['Close'])
        df['EMA200'] = df['Close'].ewm(span=200, adjust=False).mean()
        df['MACD'], df['MACD_SIGNAL'] = calcular_macd(df['Close'])

        last_row = df.iloc[-1]
        prev_row = df.iloc[-2]

        atr = calcular_atr(df)
        soporte, resistencia = obtener_niveles_clave(df)

        estructura = "RANGO ↔️"

        if last_row['High'] > prev_row['High'] and last_row['Low'] > prev_row['Low']:
            estructura = "UPTREND 📈"
        elif last_row['High'] < prev_row['High'] and last_row['Low'] < prev_row['Low']:
            estructura = "DOWNTREND 📉"

        datos = {
            "precio": float(last_row['Close']),
            "rsi": float(last_row['RSI']),
            "macd": float(last_row['MACD']),
            "macd_sig": float(last_row['MACD_SIGNAL']),
            "tendencia": "ALCISTA" if last_row['Close'] > last_row['EMA200'] else "BAJISTA",
            "divergencia": detectar_divergencias(df.dropna()),
            "estructura": estructura,
            "volumen": "ALTO" if last_row['Volume'] > df['Volume'].rolling(20).mean().iloc[-1] else "NORMAL",
            "atr": atr,
            "soporte": soporte,
            "resistencia": resistencia
        }

        self.cache[symbol] = {"time": time.time(), "data": datos}

        return datos

    # ============================
    # IA EXPLICACIÓN
    # ============================
    async def ia_explicacion(self, datos, decision):

        prompt = (
            f"Actúa como un trader senior. Analiza estos datos:\n"
            f"- Precio: {datos['precio']}\n"
            f"- RSI: {datos['rsi']:.2f}\n"
            f"- Tendencia: {datos['tendencia']}\n"
            f"- Estructura: {datos['estructura']}\n"
            f"- Soporte: {datos['soporte']} | Resistencia: {datos['resistencia']}\n"
            f"Decisión: {decision}.\n\n"
            f"Tarea: Explica brevemente por qué {decision} en español profesional (max 25 palabras)."
        )

        try:
            async with self.session.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": "llama3",
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.2}
                },
                timeout=10
            ) as r:

                res = await r.json()

                return res.get("response", "Explicación no disponible.")

        except:
            return "IA fuera de línea. Análisis técnico basado en score cuantitativo."

    # ============================
    # COMANDO DISCORD
    # ============================
    @discord.app_commands.command(name="analisis", description="Análisis técnico avanzado con IA")
    async def analisis(self, interaction: discord.Interaction, activo: str):

        await interaction.response.defer(thinking=True)

        symbol = activo.upper()

        if "-" not in symbol and len(symbol) <= 5:
            symbol += "-USD"

        try:

            datos = self.obtener_datos(symbol)

            if not datos:
                return await interaction.followup.send(
                    "⚠️ Error: Activo no encontrado o datos insuficientes."
                )

            score = 0
            score += 1 if datos["tendencia"] == "ALCISTA" else -1
            score += 1 if datos["rsi"] < 35 else (-1 if datos["rsi"] > 65 else 0)
            score += 1 if datos["macd"] > datos["macd_sig"] else -1
            score += 2 if "ALCISTA" in datos["divergencia"] else (-2 if "BAJISTA" in datos["divergencia"] else 0)

            decision = "🟢 COMPRAR" if score >= 3 else "🔴 VENDER" if score <= -3 else "🟡 ESPERAR"

            color = 0x2ecc71 if "COMPRAR" in decision else 0xe74c3c if "VENDER" in decision else 0xf1c40f

            sl = datos['precio'] - (datos['atr'] * 2) if "COMPRAR" in decision else datos['precio'] + (datos['atr'] * 2)
            tp = datos['precio'] + (datos['atr'] * 3) if "COMPRAR" in decision else datos['precio'] - (datos['atr'] * 3)

            explicacion = await self.ia_explicacion(datos, decision)

            embed = discord.Embed(
                title=f"🏛️ Terminal de Trading: {symbol}",
                color=color,
                timestamp=discord.utils.utcnow()
            )

            embed.add_field(name="🎯 SEÑAL", value=f"**{decision}**", inline=True)
            embed.add_field(name="📊 SCORE", value=f"`{score}/5`", inline=True)
            embed.add_field(name="💰 PRECIO", value=f"`${datos['precio']:,.2f}`", inline=True)

            embed.add_field(name="📉 SOPORTE", value=f"`${datos['soporte']:,.2f}`", inline=True)
            embed.add_field(name="📈 RESISTENCIA", value=f"`${datos['resistencia']:,.2f}`", inline=True)
            embed.add_field(name="🌊 ESTRUCTURA", value=f"{datos['estructura']}", inline=True)

            if decision != "🟡 ESPERAR":
                embed.add_field(name="🛡️ STOP LOSS", value=f"`${sl:,.2f}`", inline=True)
                embed.add_field(name="🚀 TAKE PROFIT", value=f"`${tp:,.2f}`", inline=True)
                embed.add_field(name="📏 VOLATILIDAD (ATR)", value=f"`{datos['atr']:.4f}`", inline=True)

            embed.add_field(
                name="🤖 ANÁLISIS IA",
                value=f"*{explicacion.strip()}*",
                inline=False
            )

            await interaction.followup.send(embed=embed)

        except Exception as e:
            await interaction.followup.send(
                f"❌ Error en el motor de análisis: {str(e)}"
            )


# ============================
# SETUP PARA MAIN.PY
# ============================
async def setup(bot):
    await bot.add_cog(Trading(bot))