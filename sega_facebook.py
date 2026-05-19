import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import aiohttp
import discord

from storage import (
    get_sega_facebook_channels,
    get_sega_facebook_seen_post_id,
    set_sega_facebook_seen_post_id,
)


GRAPH_API_BASE_URL = "https://graph.facebook.com/v20.0"
POST_FETCH_LIMIT = 5


@dataclass(frozen=True)
class FacebookPage:
    page_id: str
    display_name: str
    url: str
    color: int


@dataclass(frozen=True)
class FacebookPost:
    page: FacebookPage
    post_id: str
    message: str
    created_at: datetime | None
    permalink_url: str
    image_url: str | None


PAGES = [
    FacebookPage(
        page_id="maimaiDX",
        display_name="maimai DX International",
        url="https://www.facebook.com/maimaiDX",
        color=0xF59BC7,
    ),
    FacebookPage(
        page_id="CHUNITHM.International.ver",
        display_name="CHUNITHM International",
        url="https://www.facebook.com/CHUNITHM.International.ver",
        color=0x55C7F7,
    ),
]


class FacebookFeedError(Exception):
    pass


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _find_image_url(item: dict[str, Any]) -> str | None:
    full_picture = item.get("full_picture")

    if isinstance(full_picture, str) and full_picture:
        return full_picture

    attachments = item.get("attachments")
    if not isinstance(attachments, dict):
        return None

    data = attachments.get("data")
    if not isinstance(data, list):
        return None

    for attachment in data:
        if not isinstance(attachment, dict):
            continue

        media = attachment.get("media")
        if not isinstance(media, dict):
            continue

        image = media.get("image")
        if not isinstance(image, dict):
            continue

        src = image.get("src")
        if isinstance(src, str) and src:
            return src

    return None


async def fetch_page_posts(
    session: aiohttp.ClientSession,
    page: FacebookPage,
    access_token: str,
) -> list[FacebookPost]:
    params = {
        "access_token": access_token,
        "fields": "id,message,created_time,permalink_url,full_picture,attachments{media}",
        "limit": str(POST_FETCH_LIMIT),
    }
    url = f"{GRAPH_API_BASE_URL}/{page.page_id}/posts"

    async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=20)) as response:
        payload = await response.json(content_type=None)

    if response.status >= 400:
        error = payload.get("error") if isinstance(payload, dict) else None
        message = error.get("message") if isinstance(error, dict) else None
        raise FacebookFeedError(message or f"Facebook Graph API returned HTTP {response.status}")

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise FacebookFeedError("Facebook Graph API response did not include a post list")

    posts: list[FacebookPost] = []

    for item in data:
        if not isinstance(item, dict):
            continue

        post_id = item.get("id")
        permalink_url = item.get("permalink_url")

        if not isinstance(post_id, str) or not isinstance(permalink_url, str):
            continue

        message = item.get("message")
        posts.append(
            FacebookPost(
                page=page,
                post_id=post_id,
                message=message if isinstance(message, str) else "",
                created_at=_parse_datetime(item.get("created_time")),
                permalink_url=permalink_url,
                image_url=_find_image_url(item),
            )
        )

    return posts


def select_new_posts(page: FacebookPage, posts: list[FacebookPost]) -> list[FacebookPost]:
    if not posts:
        return []

    seen_post_id = get_sega_facebook_seen_post_id(page.page_id)
    newest_post_id = posts[0].post_id

    if seen_post_id is None:
        set_sega_facebook_seen_post_id(page.page_id, newest_post_id)
        return []

    new_posts: list[FacebookPost] = []

    for post in posts:
        if post.post_id == seen_post_id:
            break
        new_posts.append(post)

    set_sega_facebook_seen_post_id(page.page_id, newest_post_id)
    return list(reversed(new_posts))


def build_post_embed(post: FacebookPost) -> discord.Embed:
    description = post.message.strip() or "새 Facebook 게시물이 올라왔습니다."

    if len(description) > 3500:
        description = f"{description[:3497]}..."

    embed = discord.Embed(
        title=f"{post.page.display_name} 새 게시물",
        url=post.permalink_url,
        description=description,
        color=post.page.color,
    )
    embed.add_field(name="Facebook", value=f"[게시물 열기]({post.permalink_url})", inline=False)
    embed.set_author(name=post.page.display_name, url=post.page.url)

    if post.created_at is not None:
        embed.timestamp = post.created_at

    if post.image_url:
        embed.set_image(url=post.image_url)

    return embed


async def send_post_to_enabled_channels(client: discord.Client, post: FacebookPost) -> None:
    embed = build_post_embed(post)

    for channel_id in get_sega_facebook_channels():
        channel = client.get_channel(int(channel_id))

        if channel is None:
            try:
                channel = await client.fetch_channel(int(channel_id))
            except discord.DiscordException:
                continue

        if not isinstance(channel, discord.abc.Messageable):
            continue

        try:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.DiscordException:
            continue


async def poll_once(client: discord.Client, access_token: str) -> list[FacebookPost]:
    published_posts: list[FacebookPost] = []

    async with aiohttp.ClientSession() as session:
        for page in PAGES:
            posts = await fetch_page_posts(session, page, access_token)

            for post in select_new_posts(page, posts):
                await send_post_to_enabled_channels(client, post)
                published_posts.append(post)

    return published_posts


async def poll_forever(
    client: discord.Client,
    access_token: str | None,
    interval_seconds: int,
) -> None:
    if not access_token:
        print("SEGA Facebook polling is disabled: FACEBOOK_ACCESS_TOKEN is not set")
        return

    await client.wait_until_ready()

    while not client.is_closed():
        try:
            await poll_once(client, access_token)
        except Exception as exc:
            print(f"SEGA Facebook polling failed: {exc}")

        await asyncio.sleep(interval_seconds)
