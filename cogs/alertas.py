import os
import asyncio
import discord
from discord.ext import commands
from telethon import TelegramClient, events
from telethon.tl.types import MessageService
from dotenv import load_dotenv

load_dotenv()

# Configuración de Telegram
TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID", 0))
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
TELEGRAM_GROUP_ID = int(os.getenv("TELEGRAM_GROUP_ID", 0))
TELEGRAM_TOPIC_ID = int(os.getenv("TELEGRAM_TOPIC_ID", 0))

# Configuración de Discord
ALERTS_CHANNEL_ID = int(os.getenv("ALERTS_CHANNEL_ID", 0))


class Alertas(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        # Usamos un archivo de sesión para mantener la conexión de Telegram
        self.client = TelegramClient("telegram_session", TELEGRAM_API_ID,
                                     TELEGRAM_API_HASH)
        self.telegram_task = None

    @commands.Cog.listener()
    async def on_ready(self):
        print(f"🤖 Bot Discord online: {self.bot.user}")

        # Iniciar Telegram solo si no está ya conectado
        if not self.client.is_connected():
            self.telegram_task = asyncio.create_task(self.ejecutar_telegram())

    async def ejecutar_telegram(self):
        print("📡 Conectando a Telegram...")
        await self.client.connect()
        print(f"✅ Telethon conectado correctamente.")
        print(
            f"🎯 Escuchando grupo {TELEGRAM_GROUP_ID} | Topic {TELEGRAM_TOPIC_ID}"
        )

        # Handler para nuevos mensajes en el grupo de Telegram
        @self.client.on(events.NewMessage(chats=TELEGRAM_GROUP_ID))
        async def handler(event):
            msg = event.message

            # LOG DE DEPURACIÓN: Esto nos ayudará a ver qué IDs está enviando Telegram
            reply_to = getattr(msg, 'reply_to', None)
            top_id = getattr(reply_to, 'reply_to_top_id', 'N/A')
            msg_id = getattr(reply_to, 'reply_to_msg_id', 'N/A')
            print(
                f"🔍 Mensaje recibido - ID: {msg.id} | Top ID: {top_id} | Reply Msg ID: {msg_id}"
            )

            if self.es_del_topic(msg):
                print(f"📩 ¡Mensaje del Topic detectado! Reenviando...")
                await self.enviar_a_discord(msg)

        print("👂 Escuchando nuevos mensajes en tiempo real...")
        await self.client.run_until_disconnected()

    def es_del_topic(self, msg):
        """
        Verifica si el mensaje pertenece al Thread (Topic) configurado.
        """
        if isinstance(msg, MessageService):
            return False

        # 1. Si el ID del mensaje es el ID del Topic
        if msg.id == TELEGRAM_TOPIC_ID:
            return True

        # 2. Si el mensaje es una respuesta
        if not msg.reply_to:
            return False

        r = msg.reply_to
        # En grupos con temas (Topics), el 'reply_to_top_id' es el ID del hilo
        top_id = getattr(r, "reply_to_top_id", None)
        msg_id = getattr(r, "reply_to_msg_id", None)

        # Verificamos contra el ID configurado
        if top_id == TELEGRAM_TOPIC_ID or msg_id == TELEGRAM_TOPIC_ID:
            return True

        return False

    async def enviar_a_discord(self, msg):
        """
        Formatea y envía el mensaje de Telegram al canal de Discord.
        """
        canal = self.bot.get_channel(ALERTS_CHANNEL_ID)
        if not canal:
            print(
                f"❌ Error: No se encontró el canal de Discord con ID {ALERTS_CHANNEL_ID}"
            )
            return

        sender = await msg.get_sender()
        nombre = getattr(sender, "first_name", "Usuario")
        if getattr(sender, "last_name", None):
            nombre += f" {sender.last_name}"

        texto = msg.text if msg.text else ""

        # Formato del mensaje en Discord
        contenido = f"🚨 **Nuevo mensaje de {nombre} en Telegram**\n\n{texto}"

        try:
            # Manejo de archivos adjuntos (fotos, documentos, etc.)
            if msg.media:
                print(f"📎 Descargando medio de Telegram...")
                path = await msg.download_media()

                # Si el archivo es muy grande, Discord podría rechazarlo (límite 8MB/25MB según servidor)
                file_size = os.path.getsize(path)
                if file_size > 8 * 1024 * 1024:  # 8MB
                    await canal.send(
                        content=
                        f"{contenido}\n\n⚠️ *El archivo adjunto era demasiado grande para enviarlo directamente.*"
                    )
                else:
                    await canal.send(content=contenido,
                                     file=discord.File(path))

                # Limpiar archivo temporal
                if os.path.exists(path):
                    os.remove(path)
            elif texto:
                await canal.send(contenido)
        except Exception as e:
            print(f"❌ Error al enviar a Discord: {e}")


async def setup(bot):
    await bot.add_cog(Alertas(bot))

