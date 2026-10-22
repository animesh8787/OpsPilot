"""Slack Bolt app (Socket Mode): slash commands and Ack/Resolve buttons."""

from slack_bolt.async_app import AsyncApp

from app.incidents import Commands, IncidentService
from app.slack_blocks import incident_blocks, incident_text


def build_app(bot_token: str, service: IncidentService, commands: Commands) -> AsyncApp:
    app = AsyncApp(token=bot_token)

    @app.command("/opsstatus")
    async def status(ack, respond):
        await ack()
        text, blocks = await commands.status()
        await respond(text=text, blocks=blocks, response_type="in_channel")

    @app.command("/incident")
    async def incident(ack, respond, command):
        await ack()
        text, blocks = await commands.incident(command.get("text", ""))
        await respond(text=text, blocks=blocks, response_type="in_channel")

    @app.command("/ask")
    async def ask(ack, respond, command):
        await ack()  # LLM calls take longer than Slack's 3s ack window
        text, blocks = await commands.ask(command.get("text", ""))
        await respond(text=text, blocks=blocks, response_type="in_channel")

    async def _button(ack, body, action, fn):
        await ack()
        inc = await fn(int(action["value"]), body["user"].get("username") or body["user"]["id"])
        if inc is None:  # already handled (double click) -> still re-render current state
            inc = service.store.get(int(action["value"]))
        if inc and not inc.slack_ts:  # message not tracked in DB; update from the click payload
            await service.notifier.update(
                body["channel"]["id"],
                body["message"]["ts"],
                incident_text(inc),
                incident_blocks(inc),
            )

    @app.action("ack_incident")
    async def on_ack(ack, body, action):
        await _button(ack, body, action, service.ack)

    @app.action("resolve_incident")
    async def on_resolve(ack, body, action):
        await _button(ack, body, action, service.resolve)

    return app
