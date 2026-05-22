import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import aiohttp
import discord

from storage import (
    get_twitter_update_seen_tweet_id,
    normalize_handle_text,
    set_twitter_update_seen_tweet_id,
)


X_API_BASE_URL = "https://api.x.com/2"
DEFAULT_HANDLES = ["maimai_official", "chunithm", "performai_int"]
SPECIAL_GUILD_ID = 1422484150920810610
SPECIAL_DEFAULT_CHANNEL_ID = 1422484152560914494
SPECIAL_EXTRA_HANDLES = ["arcaea_kr"]
TWEET_FETCH_LIMIT = 5


@dataclass(frozen=True)
class XUser:
    user_id: str
    username: str
    name: str
    profile_image_url: str | None


@dataclass(frozen=True)
class XPost:
    tweet_id: str
    user: XUser
    text: str
    created_at: datetime | None
    url: str
    image_url: str | None


class XUpdateError(Exception):
    pass


def default_handles_for_guild(guild_id: int) -> list[str]:
    handles = list(DEFAULT_HANDLES)

    if guild_id == SPECIAL_GUILD_ID:
        handles.extend(SPECIAL_EXTRA_HANDLES)

    return handles


def post_url(username: str, tweet_id: str) -> str:
    return f"https://x.com/{username}/status/{tweet_id}"


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


async def _get_json(
    session: aiohttp.ClientSession,
    url: str,
    token: str,
    params: dict[str, str],
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"}

    async with session.get(url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as response:
        payload = await response.json(content_type=None)

    if response.status >= 400:
        detail = payload.get("detail") if isinstance(payload, dict) else None
        title = payload.get("title") if isinstance(payload, dict) else None
        raise XUpdateError(str(detail or title or f"X API returned HTTP {response.status}"))

    if not isinstance(payload, dict):
        raise XUpdateError("X API response was not a JSON object")

    return payload


async def fetch_users_by_handles(
    session: aiohttp.ClientSession,
    token: str,
    handles: list[str],
) -> dict[str, XUser]:
    fixed_handles = [handle for handle in dict.fromkeys(normalize_handle_text(h) for h in handles) if handle]

    if not fixed_handles:
        return {}

    payload = await _get_json(
        session,
        f"{X_API_BASE_URL}/users/by",
        token,
        {
            "usernames": ",".join(fixed_handles),
            "user.fields": "profile_image_url",
        },
    )
    users = payload.get("data", [])
    result: dict[str, XUser] = {}

    if not isinstance(users, list):
        return result

    for item in users:
        if not isinstance(item, dict):
            continue

        user_id = item.get("id")
        username = normalize_handle_text(item.get("username", ""))
        name = item.get("name")
        profile_image_url = item.get("profile_image_url")

        if not isinstance(user_id, str) or not username or not isinstance(name, str):
            continue

        result[username] = XUser(
            user_id=user_id,
            username=username,
            name=name,
            profile_image_url=profile_image_url if isinstance(profile_image_url, str) else None,
        )

    return result


def _media_by_key(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    includes = payload.get("includes")

    if not isinstance(includes, dict):
        return {}

    media = includes.get("media")

    if not isinstance(media, list):
        return {}

    result: dict[str, dict[str, Any]] = {}

    for item in media:
        if not isinstance(item, dict):
            continue

        media_key = item.get("media_key")

        if isinstance(media_key, str):
            result[media_key] = item

    return result


def _find_image_url(tweet: dict[str, Any], media_items: dict[str, dict[str, Any]]) -> str | None:
    attachments = tweet.get("attachments")

    if not isinstance(attachments, dict):
        return None

    media_keys = attachments.get("media_keys")

    if not isinstance(media_keys, list):
        return None

    for media_key in media_keys:
        if not isinstance(media_key, str):
            continue

        media = media_items.get(media_key)

        if not media:
            continue

        image_url = media.get("url") or media.get("preview_image_url")

        if isinstance(image_url, str) and image_url:
            return image_url

    return None


async def fetch_recent_posts(
    session: aiohttp.ClientSession,
    token: str,
    user: XUser,
) -> list[XPost]:
    payload = await _get_json(
        session,
        f"{X_API_BASE_URL}/users/{user.user_id}/tweets",
        token,
        {
            "exclude": "retweets,replies",
            "max_results": str(TWEET_FETCH_LIMIT),
            "tweet.fields": "created_at,attachments",
            "expansions": "attachments.media_keys",
            "media.fields": "url,preview_image_url,type",
        },
    )
    tweets = payload.get("data", [])

    if tweets is None:
        return []

    if not isinstance(tweets, list):
        raise XUpdateError("X API response did not include a post list")

    media_items = _media_by_key(payload)
    posts: list[XPost] = []

    for tweet in tweets:
        if not isinstance(tweet, dict):
            continue

        tweet_id = tweet.get("id")
        text = tweet.get("text")

        if not isinstance(tweet_id, str) or not isinstance(text, str):
            continue

        posts.append(
            XPost(
                tweet_id=tweet_id,
                user=user,
                text=text,
                created_at=_parse_datetime(tweet.get("created_at")),
                url=post_url(user.username, tweet_id),
                image_url=_find_image_url(tweet, media_items),
            )
        )

    return posts


def select_new_posts(handle: str, posts: list[XPost]) -> list[XPost]:
    if not posts:
        return []

    handle = normalize_handle_text(handle)
    seen_tweet_id = get_twitter_update_seen_tweet_id(handle)
    newest_tweet_id = posts[0].tweet_id

    if seen_tweet_id is None:
        set_twitter_update_seen_tweet_id(handle, newest_tweet_id)
        return []

    new_posts: list[XPost] = []

    for post in posts:
        if post.tweet_id == seen_tweet_id:
            break
        new_posts.append(post)

    set_twitter_update_seen_tweet_id(handle, newest_tweet_id)
    return list(reversed(new_posts))


def build_post_embed(post: XPost) -> discord.Embed:
    description = post.text.strip() or "새 X 게시물이 올라왔습니다."

    if len(description) > 3500:
        description = f"{description[:3497]}..."

    embed = discord.Embed(
        title=f"{post.user.name} 새 게시물",
        url=post.url,
        description=description,
        color=0x1DA1F2,
    )
    embed.add_field(name="X", value=f"[원 게시글 열기]({post.url})", inline=False)
    embed.set_author(
        name=f"{post.user.name} (@{post.user.username})",
        url=f"https://x.com/{post.user.username}",
        icon_url=post.user.profile_image_url,
    )

    if post.created_at is not None:
        embed.timestamp = post.created_at

    if post.image_url:
        embed.set_image(url=post.image_url)

    return embed


async def send_post_to_channel(channel: discord.TextChannel, post: XPost) -> None:
    await channel.send(embed=build_post_embed(post), allowed_mentions=discord.AllowedMentions.none())


async def fetch_new_posts_for_handles(
    token: str,
    handles: list[str],
) -> dict[str, list[XPost]]:
    fixed_handles = [handle for handle in dict.fromkeys(normalize_handle_text(h) for h in handles) if handle]

    if not fixed_handles:
        return {}

    async with aiohttp.ClientSession() as session:
        users = await fetch_users_by_handles(session, token, fixed_handles)
        result: dict[str, list[XPost]] = {}

        for handle in fixed_handles:
            user = users.get(handle)

            if user is None:
                continue

            posts = await fetch_recent_posts(session, token, user)
            result[handle] = select_new_posts(handle, posts)

    return result


async def poll_forever(
    client: discord.Client,
    token: str | None,
    interval_seconds: int,
    get_targets,
) -> None:
    if not token:
        print("Twitter update polling is disabled: X_TOKEN is not set")
        return

    await client.wait_until_ready()

    while not client.is_closed():
        try:
            targets = get_targets()
            all_handles = sorted({handle for target in targets for handle in target["handles"]})
            posts_by_handle = await fetch_new_posts_for_handles(token, all_handles)

            for target in targets:
                channel = client.get_channel(int(target["channel_id"]))

                if channel is None:
                    try:
                        channel = await client.fetch_channel(int(target["channel_id"]))
                    except discord.DiscordException:
                        continue

                if not isinstance(channel, discord.TextChannel):
                    continue

                for handle in target["handles"]:
                    for post in posts_by_handle.get(handle, []):
                        try:
                            await send_post_to_channel(channel, post)
                        except discord.DiscordException:
                            continue
        except Exception as exc:
            print(f"Twitter update polling failed: {exc}")

        await asyncio.sleep(interval_seconds)
