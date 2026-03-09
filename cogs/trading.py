import discord
from discord.ext import commands, tasks
import yfinance as yf
import pandas as pd
import numpy as np
import os
import time
import discord.ui
from scipy.signal import argrelextrema
from dotenv import load_dotenv
import matplotlib.pyplot as plt
import asyncio

load_dotenv()

SIGNALS_CHANNEL_ID = int(os.getenv("SIGNS_CHANNEL_ID"))

SCAN_SYMBOLS = [
    "BTC-USD",
    "ETH-USD",
    "SOL-USD",
    "BNB-USD",
    "XRP-USD",
    "ADA-USD",
    "DOGE-USD",
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


def calcular_bollinger_bands(series, window=20, num_std_dev=2):
    sma = series.rolling(window).mean()
    std = series.rolling(window).std()
    upper_band = sma + (std * num_std_dev)
    lower_band = sma - (std * num_std_dev)
    return upper_band, sma, lower_band


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

    async def obtener_datos(self, symbol):

        if symbol in self.cache and (time.time() - self.cache[symbol]["time"]
                                     < 60):
            return self.cache[symbol]["data"]

        # Ejecutar yfinance.download en un hilo separado para evitar bloqueo
        df = await asyncio.to_thread(yf.download,
                                     symbol,
                                     period="90d",
                                     interval="1h",
                                     progress=False)

        if df.empty or len(df) < 50:
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df['RSI'] = calcular_rsi(df['Close'])
        df['EMA50'] = df['Close'].ewm(span=50).mean()
        df['EMA200'] = df['Close'].ewm(span=200).mean()
        df['MACD'], df['MACD_SIGNAL'] = calcular_macd(df['Close'])
        df['BB_UPPER'], df['BB_MIDDLE'], df[
            'BB_LOWER'] = calcular_bollinger_bands(df['Close'])

        last = df.iloc[-1]
        prev = df.iloc[-2]

        atr = calcular_atr(df)
        soporte, resistencia = obtener_niveles(df)

        # Calcular Volumen Relativo (RVOL)
        df['Volume_MA'] = df['Volume'].rolling(window=20).mean()
        rvol = last['Volume'] / (last['Volume_MA'] + 1e-9)

        datos = {
            "precio": float(last['Close']),
            "rsi": float(last['RSI']),
            "macd": float(last['MACD']),
            "macd_sig": float(last['MACD_SIGNAL']),
            "tendencia":
            "ALCISTA" if last['Close'] > last['EMA200'] else "BAJISTA",
            "volumen": float(last['Volume']),
            "vol_avg": float(df['Volume'].rolling(20).mean().iloc[-1]),
            "atr": atr,
            "soporte": soporte,
            "resistencia": resistencia,
            "ema50": float(last['EMA50']),
            "ema200": float(last['EMA200']),
            "bb_upper": float(last['BB_UPPER']),
            "bb_middle": float(last['BB_MIDDLE']),
            "bb_lower": float(last['BB_LOWER']),
            "rvol": rvol,
            "df_historico":
            df.tail(100)  # Guardar un subconjunto para el gráfico
        }

        self.cache[symbol] = {"time": time.time(), "data": datos}

        return datos

    # =====================
    # SCORE AVANZADO
    # =====================

    def calcular_score(self, datos):

        score = 0

        # Filtro de tendencia: solo operar en tendencia alcista para compras
        if datos["tendencia"] == "ALCISTA":
            score += 2
        else:
            score -= 2

        # RSI
        if datos["rsi"] < 35:
            score += 1  # Posible sobreventa
        elif datos["rsi"] > 65:
            score -= 1  # Posible sobrecompra

        # MACD
        if datos["macd"] > datos["macd_sig"]:
            score += 1  # Cruce alcista
        else:
            score -= 1  # Cruce bajista

        # Ruptura resistencia / soporte
        if datos["precio"] > datos["resistencia"]:
            score += 3  # Ruptura alcista
        elif datos["precio"] < datos["soporte"]:
            score -= 3  # Ruptura bajista

        # Volumen fuerte (RVOL)
        if datos["rvol"] > 2:
            score += 1

        # Bandas de Bollinger
        if datos["precio"] > datos["bb_upper"]:
            score -= 1  # Sobrecompra
        elif datos["precio"] < datos["bb_lower"]:
            score += 1  # Sobreventa

        # Cruce EMA (Golden Cross / Death Cross - simplificado para el último punto)
        if datos["ema50"] > datos["ema200"] and datos["tendencia"] == "ALCISTA":
            score += 2  # Golden Cross
        elif datos["ema50"] < datos["ema200"] and datos[
                "tendencia"] == "BAJISTA":
            score -= 2  # Death Cross

        return score

    # =====================
    # GENERAR EMBED Y GRÁFICO
    # =====================

    def crear_embed_y_grafico(self, symbol, datos, score):

        decision = "🟢 COMPRAR" if score >= 3 else "🔴 VENDER" if score <= -3 else "🟡 ESPERAR"

        precio = datos["precio"]

        # Lógica de Stop Loss / Take Profit ajustada
        if decision == "🟢 COMPRAR":
            sl = precio - datos["atr"] * 2
            tp = precio + datos["atr"] * 3
        elif decision == "🔴 VENDER":
            sl = precio + datos["atr"] * 2
            tp = precio - datos["atr"] * 3
        else:
            sl = 0
            tp = 0

        rr = abs((tp - precio) / (precio - sl)) if (precio - sl) != 0 else 0

        color = 0x2ecc71 if "COMPRAR" in decision else 0xe74c3c if "VENDER" in decision else 0xf1c40f

        embed = discord.Embed(title=f"📊 Señal de Trading: {symbol}",
                              color=color)

        embed.add_field(name="🎯 Acción", value=decision, inline=True)
        embed.add_field(name="📊 Score", value=f"{score}", inline=True)
        embed.add_field(name="💰 Precio", value=f"${precio:,.2f}", inline=True)

        embed.add_field(name="📉 Soporte",
                        value=f"${datos['soporte']:,.2f}",
                        inline=True)
        embed.add_field(name="📈 Resistencia",
                        value=f"${datos['resistencia']:,.2f}",
                        inline=True)
        embed.add_field(name="📏 ATR", value=f"{datos['atr']:.4f}", inline=True)

        embed.add_field(name="📈 EMA50",
                        value=f"{datos['ema50']:.2f}",
                        inline=True)
        embed.add_field(name="📈 EMA200",
                        value=f"{datos['ema200']:.2f}",
                        inline=True)
        embed.add_field(name="📊 RSI", value=f"{datos['rsi']:.2f}", inline=True)
        embed.add_field(name="📊 MACD",
                        value=f"{datos['macd']:.2f}",
                        inline=True)
        embed.add_field(name="📊 MACD Signal",
                        value=f"{datos['macd_sig']:.2f}",
                        inline=True)
        embed.add_field(name="📈 BB Upper",
                        value=f"{datos['bb_upper']:.2f}",
                        inline=True)
        embed.add_field(name="📉 BB Lower",
                        value=f"{datos['bb_lower']:.2f}",
                        inline=True)
        embed.add_field(name="📊 RVOL",
                        value=f"{datos['rvol']:.2f}",
                        inline=True)

        if decision != "🟡 ESPERAR":
            embed.add_field(name="🛡️ Stop Loss",
                            value=f"${sl:,.2f}",
                            inline=True)
            embed.add_field(name="🚀 Take Profit",
                            value=f"${tp:,.2f}",
                            inline=True)
            embed.add_field(name="⚖️ Risk/Reward",
                            value=f"{rr:.2f}",
                            inline=True)

        # Generar gráfico
        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(10, 6))

        df_plot = datos['df_historico']

        ax.plot(df_plot.index,
                df_plot['Close'],
                label='Precio de Cierre',
                color='cyan')
        ax.plot(df_plot.index,
                df_plot['EMA50'],
                label='EMA 50',
                color='orange')
        ax.plot(df_plot.index,
                df_plot['EMA200'],
                label='EMA 200',
                color='magenta')
        ax.plot(df_plot.index,
                df_plot['BB_UPPER'],
                label='BB Superior',
                color='red',
                linestyle='--')
        ax.plot(df_plot.index,
                df_plot['BB_LOWER'],
                label='BB Inferior',
                color='green',
                linestyle='--')

        ax.fill_between(df_plot.index,
                        df_plot['BB_LOWER'],
                        df_plot['BB_UPPER'],
                        color='gray',
                        alpha=0.1)

        ax.set_title(f'{symbol} - Gráfico de Precio con Indicadores',
                     color='white')
        ax.set_xlabel('Fecha', color='white')
        ax.set_ylabel('Precio', color='white')
        ax.tick_params(axis='x', colors='white')
        ax.tick_params(axis='y', colors='white')
        ax.legend(loc='upper left',
                  frameon=True,
                  facecolor='black',
                  edgecolor='white',
                  labelcolor='white')
        ax.grid(True, linestyle=':', alpha=0.6)

        # Resaltar soporte y resistencia
        ax.axhline(y=datos['soporte'],
                   color='blue',
                   linestyle='-',
                   linewidth=1,
                   label='Soporte')
        ax.axhline(y=datos['resistencia'],
                   color='purple',
                   linestyle='-',
                   linewidth=1,
                   label='Resistencia')

        # Guardar gráfico
        chart_path = f"./charts/{symbol}_chart.png"
        os.makedirs('./charts', exist_ok=True)
        plt.savefig(chart_path, bbox_inches='tight', dpi=100)
        plt.close(fig)

        return embed, chart_path

    # =====================
    # SCANNER AUTOMÁTICO
    # =====================

    @tasks.loop(minutes=15)
    async def market_scanner(self):

        canal = self.bot.get_channel(SIGNALS_CHANNEL_ID)

        if not canal:
            print(f"Error: Canal con ID {SIGNALS_CHANNEL_ID} no encontrado.")
            return

        oportunidades = []

        for symbol in SCAN_SYMBOLS:
            try:
                datos = await self.obtener_datos(symbol)

                if not datos:
                    print(f"No se pudieron obtener datos para {symbol}")
                    continue

                score = self.calcular_score(datos)

                oportunidades.append((symbol, score, datos))

                if score >= 5:
                    embed, chart_path = self.crear_embed_y_grafico(
                        symbol, datos, score)
                    view = self.SignalView(self, symbol, datos, score)
                    await canal.send(embed=embed,
                                     file=discord.File(chart_path),
                                     view=view)

            except Exception as e:
                print(f"Error al procesar {symbol} en scanner automático: {e}")
                continue

        # ranking

        oportunidades.sort(key=lambda x: x[1], reverse=True)

        ranking = "🔥 **TOP OPORTUNIDADES**\n\n"

        for i, (symbol, score, _) in enumerate(oportunidades[:5], start=1):
            ranking += f"{i}️⃣ {symbol} — score {score}\n"

        await canal.send(ranking)

    # =====================
    # BOTONES INTERACTIVOS
    # =====================

    class SignalView(discord.ui.View):

        def __init__(self, bot_cog, symbol, datos, score):
            super().__init__(timeout=300)  # Timeout de 5 minutos
            self.bot_cog = bot_cog
            self.symbol = symbol
            self.datos = datos
            self.score = score

        @discord.ui.button(label="Actualizar Precio",
                           style=discord.ButtonStyle.primary,
                           emoji="🔄")
        async def refresh_button(self, interaction: discord.Interaction,
                                 button: discord.ui.Button):
            await interaction.response.defer(ephemeral=True)
            try:
                new_datos = await self.bot_cog.obtener_datos(self.symbol)
                if new_datos:
                    new_score = self.bot_cog.calcular_score(new_datos)
                    new_embed, new_chart_path = self.bot_cog.crear_embed_y_grafico(
                        self.symbol, new_datos, new_score)
                    await interaction.followup.edit_message(
                        message_id=interaction.message.id,
                        embed=new_embed,
                        attachments=[discord.File(new_chart_path)],
                        view=self)
                    await interaction.followup.send("Precio actualizado.",
                                                    ephemeral=True)
                else:
                    await interaction.followup.send(
                        "No se pudieron obtener nuevos datos.", ephemeral=True)
            except Exception as e:
                await interaction.followup.send(f"Error al actualizar: {e}",
                                                ephemeral=True)

        @discord.ui.button(label="Ver Detalles",
                           style=discord.ButtonStyle.secondary,
                           emoji="🔍")
        async def details_button(self, interaction: discord.Interaction,
                                 button: discord.ui.Button):
            await interaction.response.defer(ephemeral=True)
            details_text = f"**Detalles para {self.symbol}:**\n"
            for key, value in self.datos.items():
                if key != "df_historico":  # Evitar mostrar el DataFrame completo
                    details_text += f"- {key.replace('_', ' ').title()}: {value}\n"
            await interaction.followup.send(details_text, ephemeral=True)

    # =====================
    # SCAN MANUAL
    # =====================

    # =====================
    # SCAN MANUAL
    # =====================

    @discord.app_commands.command(name="scan",
                                  description="Escanea el mercado")
    async def scan(self, interaction: discord.Interaction):

        await interaction.response.defer()

        resultados = []

        for symbol in SCAN_SYMBOLS:
            try:
                datos = await self.obtener_datos(symbol)

                if not datos:
                    await interaction.followup.send(
                        f"No se pudieron obtener datos para {symbol}",
                        ephemeral=True)
                    continue

                score = self.calcular_score(datos)

                resultados.append((symbol, score, datos))

            except Exception as e:
                await interaction.followup.send(
                    f"Error al procesar {symbol}: {e}", ephemeral=True)
                continue

        resultados.sort(key=lambda x: x[1], reverse=True)

        texto = "📊 **Market Scan**\n\n"

        for symbol, score, _ in resultados[:5]:
            texto += f"• {symbol} → score {score}\n"

        await interaction.followup.send(texto)

        # Para el comando /scan, también podemos enviar un embed con botones para el TOP 1
        if resultados:
            top_symbol, top_score, top_datos = resultados[0]
            top_embed, top_chart_path = self.crear_embed_y_grafico(
                top_symbol, top_datos, top_score)
            top_view = self.SignalView(self, top_symbol, top_datos, top_score)
            await interaction.followup.send(content="**Top 1 Oportunidad:**",
                                            embed=top_embed,
                                            file=discord.File(top_chart_path),
                                            view=top_view)


async def setup(bot):
    await bot.add_cog(Trading(bot))
