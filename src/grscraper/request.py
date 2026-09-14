"""Validated request contract shared by HTTP and Lambda entrypoints."""

from dataclasses import dataclass
from urllib.parse import urlsplit

from . import config
from .sinks import parse_sinks
from .targets import parse_targets
from .url import classify_input


@dataclass(frozen=True)
class ScrapeRequest:
    targets: str | None = None
    sinks: list[str] | None = None
    limit: int | None = None
    inline_result: bool = False
    include_internal: bool = False
    refresh: bool = True

    @classmethod
    def parse(cls, body, *, restrict_sinks: bool = False):
        if not isinstance(body, dict):
            raise ValueError("body must be a JSON object")
        allowed = {"targets", "sinks", "limit", "inline_result", "include_internal", "refresh"}
        if set(body) - allowed:
            raise ValueError("unknown request fields")
        for field in ("inline_result", "include_internal", "refresh"):
            if field in body and type(body[field]) is not bool:
                raise ValueError(f"{field} must be a boolean")
        limit = body.get("limit")
        if limit is not None and (type(limit) is not int or not 1 <= limit <= 1000):
            raise ValueError("limit must be an integer between 1 and 1000")
        targets = body.get("targets")
        if isinstance(targets, list):
            if any(not isinstance(t, str) or not t.strip() for t in targets):
                raise ValueError("targets must contain non-empty strings")
            targets = "\n".join(targets)
        if targets is not None and not isinstance(targets, str):
            raise ValueError("targets must be a string or an array of strings")
        parsed = parse_targets(targets) if targets is not None else []
        if len(parsed) > 1000 or any(len(value) > 8192 for value, _ in parsed):
            raise ValueError("at most 1000 targets, each at most 8192 characters")
        # Only trusted Maps URLs may be navigated from external requests.
        # This validates the initial URL; browser egress still needs platform controls.
        for value, declared in parsed:
            if (declared or classify_input(value)) == "maps_url":
                url = urlsplit(value)
                if (
                    url.scheme != "https"
                    or url.username
                    or url.password
                    or url.hostname not in {"google.com", "www.google.com", "maps.google.com"}
                    or url.port not in (None, 443)
                    or not (url.path == "/maps" or url.path.startswith("/maps/"))
                ):
                    raise ValueError("maps_url must be an HTTPS google.com/maps URL")
        sinks = body.get("sinks")
        if isinstance(sinks, str):
            sinks = parse_sinks(sinks)
        if sinks is not None:
            if not isinstance(sinks, list) or any(
                not isinstance(s, str) or not s.strip() for s in sinks
            ):
                raise ValueError("sinks must be a string or an array of non-empty strings")
            if restrict_sinks and any(s not in parse_sinks(config.SINKS) for s in sinks):
                raise ValueError("HTTP sinks must be preconfigured in GRS_SINKS")
        return cls(
            targets,
            sinks,
            limit,
            body.get("inline_result", False),
            body.get("include_internal", False),
            body.get("refresh", True),
        )

    def execute(self):
        from .sync import sync

        result = sync(
            raw_targets=self.targets,
            sink_uris=self.sinks,
            limit=self.limit,
            include_internal=self.include_internal,
            refresh=self.refresh,
        )
        payload = result.pop("payload")
        if self.inline_result:
            result["result"] = payload
        return result
