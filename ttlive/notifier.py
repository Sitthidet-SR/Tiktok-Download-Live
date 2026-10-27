"""Send alerts to the log and, if configured, Discord and LINE."""

import json
import logging
import urllib.request

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, cfg):
        self.discord = cfg.discord_webhook_url
        self.line_token = cfg.line_channel_token
        self.line_to = cfg.line_to

    def send(self, text):
        log.warning("NOTIFY: %s", text)
        if self.discord:
            self._post(self.discord, {"content": text[:1900]})
        if self.line_token and self.line_to:
            self._post("https://api.line.me/v2/bot/message/push",
                       {"to": self.line_to, "messages": [{"type": "text", "text": text[:4900]}]},
                       {"Authorization": f"Bearer {self.line_token}"})

    def _post(self, url, payload, headers=None):
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(), method="POST",
            headers={"Content-Type": "application/json", **(headers or {})})
        try:
            urllib.request.urlopen(req, timeout=15).close()
        except Exception as e:  # an alert failing must never stop recording
            log.error("notification to %s failed: %s", url.split("/")[2], e)
