"""Slack posting with a dry-run fallback (no tokens -> log the Block Kit JSON)."""

import itertools
import json
import logging

log = logging.getLogger("opspilot.slack")
_fake_ts = itertools.count(1)


class SlackNotifier:
    def __init__(self, client, channel: str) -> None:  # client: slack_sdk AsyncWebClient | None
        self.client, self.channel = client, channel

    @property
    def dry_run(self) -> bool:
        return self.client is None

    async def post(self, text: str, blocks: list[dict]) -> tuple[str, str]:
        """Returns (channel, ts)."""
        if self.dry_run:
            log.info("DRY-RUN slack post", extra={"extra_fields": {"text": text, "blocks": blocks}})
            return self.channel, f"dryrun-{next(_fake_ts)}"
        r = await self.client.chat_postMessage(channel=self.channel, text=text, blocks=blocks)
        return r["channel"], r["ts"]

    async def update(self, channel: str, ts: str, text: str, blocks: list[dict]) -> None:
        if self.dry_run:
            log.info(
                "DRY-RUN slack update",
                extra={"extra_fields": {"ts": ts, "blocks": json.dumps(blocks)[:2000]}},
            )
            return
        await self.client.chat_update(channel=channel, ts=ts, text=text, blocks=blocks)
