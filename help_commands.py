import discord

from messages import build_embed, get_message
from storage import get_allowed_guild_ids


def build_server_help_embeds(guild_id: int) -> list[discord.Embed]:
    command_values = {
        "slash_help": get_message("commands.slash_help"),
        "slash_ping": get_message("commands.slash_ping"),
        "slash_gameplaza": get_message("commands.slash_gameplaza"),
        "slash_twitter_update": get_message("commands.slash_twitter_update"),
        "slash_maimai_song": get_message("commands.slash_maimai_song"),
        "slash_chunithm_song": get_message("commands.slash_chunithm_song"),
        "slash_maimai_song_preset": get_message("commands.slash_maimai_song_preset"),
        "slash_chunithm_song_preset": get_message("commands.slash_chunithm_song_preset"),
    }
    embeds = [build_embed("server_help", **command_values)]

    if str(guild_id) in get_allowed_guild_ids():
        treat_values = {
            "slash_treat_add": get_message("commands.slash_treat_add"),
            "slash_treat_delete": get_message("commands.slash_treat_delete"),
            "slash_treat_list": get_message("commands.slash_treat_list"),
        }
        embeds.append(build_embed("server_help_treat", **treat_values))

    return embeds
