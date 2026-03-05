import discord
from discord.ext import commands

class Limpieza(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(name="clear", description="Borra mensajes del canal")
    @discord.app_commands.describe(cantidad="Número de mensajes a borrar")
    async def clear(self, interaction: discord.Interaction, cantidad: int):

        # comprobar permisos
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message(
                "❌ No tienes permisos para borrar mensajes.",
                ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        deleted = await interaction.channel.purge(limit=cantidad)

        await interaction.followup.send(
            f"🧹 {len(deleted)} mensajes eliminados.",
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(Limpieza(bot))