import discord

from messages import build_embed, get_message
from storage import get_allowed_guild_ids


def build_server_help_embeds(guild_id: int) -> list[discord.Embed]:
    command_values = {
        "slash_help": get_message("commands.slash_help"),
        "slash_ping": get_message("commands.slash_ping"),
        "slash_gameplaza": get_message("commands.slash_gameplaza"),
        "slash_sega_facebook": get_message("commands.slash_sega_facebook"),
        "slash_random_song": get_message("commands.slash_random_song"),
        "slash_random_song_preset": get_message("commands.slash_random_song_preset"),
    }
    embeds = [build_embed("server_help", **command_values)]

    if str(guild_id) in get_allowed_guild_ids():
        treat_values = {
            "user_treat_list": get_message("commands.user_treat_list"),
            "user_treat_add": get_message("commands.user_treat_add"),
            "user_treat_help": get_message("commands.user_treat_help"),
        }
        embeds.append(build_embed("server_help_treat", **treat_values))

    return embeds
