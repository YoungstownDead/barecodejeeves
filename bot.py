import asyncio
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict

import discord
from discord.ext import commands
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("discord-memory-bot")


@dataclass
class BotConfig:
    discord_token: str
    openai_api_key: str
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str | None = None
    bot_name: str = "Jeeves"
    memory_messages: int = 30
    allowed_channel_ids: set[int] | None = None

    @classmethod
    def from_env(cls) -> "BotConfig":
        discord_token = os.getenv("DISCORD_TOKEN", "")
        openai_api_key = os.getenv("OPENAI_API_KEY", "")

        if not discord_token:
            raise ValueError("Missing DISCORD_TOKEN")
        if not openai_api_key:
            raise ValueError("Missing OPENAI_API_KEY")

        channels_raw = os.getenv("ALLOWED_CHANNEL_IDS", "").strip()
        allowed = {
            int(channel_id.strip())
            for channel_id in channels_raw.split(",")
            if channel_id.strip()
        }

        return cls(
            discord_token=discord_token,
            openai_api_key=openai_api_key,
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            openai_base_url=os.getenv("OPENAI_BASE_URL") or None,
            bot_name=os.getenv("BOT_NAME", "Jeeves"),
            memory_messages=int(os.getenv("MEMORY_MESSAGES", "30")),
            allowed_channel_ids=allowed,
        )


class MemoryStore:
    def __init__(self, db_path: str = "memory.db") -> None:
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_message_id TEXT,
                guild_id TEXT,
                channel_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_messages_channel_user_time
            ON messages (channel_id, user_id, created_at)
            """
        )
        self.conn.commit()

    def add_message(
        self,
        *,
        discord_message_id: str,
        guild_id: str | None,
        channel_id: str,
        user_id: str,
        role: str,
        content: str,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO messages (
                discord_message_id,
                guild_id,
                channel_id,
                user_id,
                role,
                content,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                discord_message_id,
                guild_id,
                channel_id,
                user_id,
                role,
                content,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.conn.commit()

    def load_recent_context(
        self,
        *,
        channel_id: str,
        user_id: str,
        limit: int,
    ) -> List[Dict[str, str]]:
        rows = self.conn.execute(
            """
            SELECT role, content, created_at
            FROM messages
            WHERE channel_id = ?
               OR user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (channel_id, user_id, limit),
        ).fetchall()

        rows = list(reversed(rows))
        return [{"role": row["role"], "content": row["content"]} for row in rows]


class JeevesBot(commands.Bot):
    def __init__(self, config: BotConfig):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.messages = True

        super().__init__(command_prefix="!", intents=intents)

        self.config = config
        self.memory = MemoryStore()
        self.openai_client = AsyncOpenAI(
            api_key=config.openai_api_key,
            base_url=config.openai_base_url,
        )
        self.system_prompt = (
            f"You are {config.bot_name}, a Discord-native AI companion similar to"
            " a social chat bot. Be friendly, concise, and conversational."
            " You have long-term memory pulled from prior chats."
            " Reference memories naturally without revealing internal implementation."
            " Keep responses readable for Discord (short paragraphs, occasional bullets)."
        )

    async def on_ready(self):
        logger.info("Logged in as %s (%s)", self.user, self.user.id if self.user else "n/a")

    async def should_respond(self, message: discord.Message) -> bool:
        if message.author.bot:
            return False

        if isinstance(message.channel, discord.DMChannel):
            return True

        if self.user and self.user in message.mentions:
            return True

        if message.reference and self.user and message.reference.resolved:
            ref = message.reference.resolved
            if isinstance(ref, discord.Message) and ref.author.id == self.user.id:
                return True

        if self.config.allowed_channel_ids and message.channel.id in self.config.allowed_channel_ids:
            return True

        return False

    async def build_messages(self, message: discord.Message) -> List[Dict[str, str]]:
        context = self.memory.load_recent_context(
            channel_id=str(message.channel.id),
            user_id=str(message.author.id),
            limit=self.config.memory_messages,
        )

        live_prompt = {
            "role": "user",
            "content": f"[{message.author.display_name}] {message.content}",
        }

        return [{"role": "system", "content": self.system_prompt}, *context, live_prompt]

    async def generate_reply(self, messages: List[Dict[str, str]]) -> str:
        completion = await self.openai_client.chat.completions.create(
            model=self.config.openai_model,
            messages=messages,
            temperature=0.8,
            max_tokens=400,
        )
        return completion.choices[0].message.content or "I had a thought, but words failed me."

    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        self.memory.add_message(
            discord_message_id=str(message.id),
            guild_id=str(message.guild.id) if message.guild else None,
            channel_id=str(message.channel.id),
            user_id=str(message.author.id),
            role="user",
            content=f"[{message.author.display_name}] {message.content}",
        )

        if not await self.should_respond(message):
            return

        async with message.channel.typing():
            try:
                prompt_messages = await self.build_messages(message)
                reply = await self.generate_reply(prompt_messages)
            except Exception:
                logger.exception("Failed generating response")
                await message.reply(
                    "I hit an error while thinking. Check server logs and config, then try again."
                )
                return

        sent = await message.reply(reply, mention_author=False)

        self.memory.add_message(
            discord_message_id=str(sent.id),
            guild_id=str(sent.guild.id) if sent.guild else None,
            channel_id=str(sent.channel.id),
            user_id=str(self.user.id) if self.user else "bot",
            role="assistant",
            content=reply,
        )


def main() -> None:
    config = BotConfig.from_env()
    bot = JeevesBot(config)
    bot.run(config.discord_token)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
