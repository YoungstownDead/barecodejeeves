# Discord AI Chatbot with Persistent Memory

A Discord bot inspired by Shapes/AICord style conversational bots:

- chats naturally in channels and DMs,
- remembers previous interactions across restarts,
- uses any OpenAI-compatible chat completion provider.

## Features

- **Persistent memory** using SQLite (`memory.db`)
- **Context stitching** from recent channel and user history
- **Discord-native behavior**:
  - replies in DMs,
  - replies when mentioned,
  - replies when users reply to the bot,
  - optional always-on channels.

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Copy env template and configure:

   ```bash
   cp .env.example .env
   ```

4. Fill in values:

   - `DISCORD_TOKEN`: your Discord bot token
   - `OPENAI_API_KEY`: API key for your LLM provider
   - `OPENAI_MODEL`: model name (default `gpt-4o-mini`)
   - `OPENAI_BASE_URL`: optional for OpenAI-compatible endpoints
   - `ALLOWED_CHANNEL_IDS`: optional comma-separated channel IDs for always-on chat

5. Run the bot:

   ```bash
   python bot.py
   ```

## Discord App configuration checklist

- Enable **Message Content Intent** in Discord Developer Portal.
- Invite bot with proper scopes/permissions:
  - `bot`
  - permissions to read/send messages in your server.

## Notes on memory behavior

The bot stores each message in `memory.db` and reloads recent entries when generating responses, which gives it persistent conversational context.

If you want stronger long-term memory later, you can extend this with:

- memory summarization,
- vector search,
- user profile extraction (likes, dislikes, facts).
