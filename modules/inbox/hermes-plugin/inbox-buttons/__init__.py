"""inbox-buttons: tappable answers for agent-inbox cards on Telegram.

The inbox owns what a card says and which buttons it has. This plugin only sends a card with an
inline keyboard (``hermes inbox-card``), reusing the bot token Hermes already holds, and turns a
tap whose callback data is ``ib:<entry>:<value>`` into ``agt inbox answer``. The store decides
whether the answer is accepted; the tap shows its reply.

The send path reuses private helpers from Hermes's standalone Telegram sender
(``_telegram_bot``, ``_telegram_format``). A Hermes update can move them; the inbox falls back
to a plain ``hermes send`` when this command fails.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys

PREFIX = "ib:"


def _agt() -> str:
    return os.environ.get("AGENT_INBOX_AGT") or shutil.which("agt") or os.path.expanduser("~/.local/bin/agt")


def setup_cli(parser) -> None:
    parser.add_argument("--to", default="telegram", help="telegram (home channel) or telegram:<chat_id>")
    parser.add_argument("--buttons", required=True, help='JSON list of [label, callback_data] pairs, one per row')
    parser.add_argument("message", nargs="?", help="Card text (Markdown). Read from stdin when omitted.")


async def _send(to: str, text: str, buttons: list[list[str]]) -> dict:
    from hermes_cli.send_cmd import _load_hermes_env
    _load_hermes_env()
    from gateway.config import Platform, load_gateway_config
    from plugins.platforms.telegram.standalone import _telegram_bot, _telegram_format
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    platform, _, chat = to.partition(":")
    if platform != "telegram":
        return {"ok": False, "error": f"only telegram targets are supported, got {to!r}"}
    config = load_gateway_config()
    pconfig = config.platforms.get(Platform.TELEGRAM)
    if pconfig is None or not pconfig.token:
        return {"ok": False, "error": "telegram is not configured in Hermes"}
    if not chat:
        home = config.get_home_channel(Platform.TELEGRAM)
        if home is None:
            return {"ok": False, "error": "telegram has no home channel"}
        chat = str(home.chat_id)
    for _, data in buttons:
        if not data.startswith(PREFIX) or len(data.encode()) > 64:
            return {"ok": False, "error": f"bad callback data {data!r}"}
    markup = InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=data)] for label, data in buttons])
    formatted, parse_mode, _ = _telegram_format(text)
    bot = _telegram_bot(pconfig.token, pconfig.extra)
    msg = await bot.send_message(
        chat_id=int(chat) if chat.lstrip("-").isdigit() else chat, text=formatted, parse_mode=parse_mode,
        reply_markup=markup, disable_web_page_preview=True)
    return {"ok": True, "chat_id": chat, "message_id": msg.message_id}


def handle_cli(args) -> None:
    text = args.message if args.message is not None else sys.stdin.read()
    try:
        buttons = json.loads(args.buttons)
        result = asyncio.run(_send(args.to, text, buttons))
    except Exception as exc:
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(result))
    sys.exit(0 if result.get("ok") else 1)


def _label(query) -> str:
    markup = query.message.reply_markup if query.message else None
    for row in (markup.inline_keyboard if markup else ()):
        for button in row:
            if button.callback_data == query.data:
                return button.text
    return query.data.split(":", 2)[-1]


def _wire(app, adapter) -> None:
    from telegram.ext import ApplicationHandlerStop, CallbackQueryHandler

    async def on_tap(update, context) -> None:
        query = update.callback_query
        parts = (query.data or "").split(":", 2)
        if len(parts) != 3 or not parts[1] or not parts[2]:
            await query.answer("Malformed button", show_alert=True)
            raise ApplicationHandlerStop
        _, entry_id, value = parts
        user = query.from_user
        chat = query.message.chat if query.message else None
        check = getattr(adapter, "_is_callback_user_authorized", None)
        allowed = bool(check) and check(
            str(user.id), chat_id=str(chat.id) if chat else None, chat_type=getattr(chat, "type", None),
            user_name=user.username)
        if not allowed:
            await query.answer("Not allowed", show_alert=True)
            raise ApplicationHandlerStop
        proc = await asyncio.create_subprocess_exec(
            _agt(), "inbox", "answer", entry_id, "--value", value, "--via", "telegram",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        _, err = await proc.communicate()
        if proc.returncode == 0:
            await query.answer("Answered")
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(f"✅ Answered: {_label(query)}")
        else:
            reason = (err.decode(errors="replace").strip().splitlines() or [f"exit {proc.returncode}"])[-1]
            await query.answer(reason[:190], show_alert=True)
            # Not found, or closed / already answered: the buttons are dead. A held session keeps
            # them, since the question becomes answerable at the reset.
            if proc.returncode == 2 or (proc.returncode == 4 and " is held" not in reason):
                await query.edit_message_reply_markup(reply_markup=None)
        raise ApplicationHandlerStop

    # Group -1 runs before core's catch-all CallbackQueryHandler; ApplicationHandlerStop keeps an
    # inbox tap from reaching it.
    app.add_handler(CallbackQueryHandler(on_tap, pattern=r"^ib:"), group=-1)


def register(ctx) -> None:
    ctx.register_cli_command(
        name="inbox-card", help="Send an agent-inbox card with answer buttons",
        description="Send a Telegram card with inline buttons whose taps answer agent-inbox entries.",
        setup_fn=setup_cli, handler_fn=handle_cli)
    ctx.register_telegram_handler(_wire)


__all__ = ["register"]
