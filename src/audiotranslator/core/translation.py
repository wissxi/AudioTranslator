"""Translating recognized segments.

Segments are translated in batches (one segment per line) so the translation
stays aligned with the timing and can be written as subtitles. If a service
fails, the next one in the chain takes over.

Services:
* ``google``   — Google Translate web endpoint (free, no key).
* ``mymemory`` — MyMemory API (free, daily limit per IP).
* ``deepl``    — DeepL API (free or Pro key required).
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable, Sequence
from typing import ClassVar

import requests

from .. import APP_NAME, __version__
from ..errors import Cancelled, TranslationError

log = logging.getLogger(__name__)

USER_AGENT = f"{APP_NAME}/{__version__}"
TIMEOUT = 30


class RetryableError(TranslationError):
    """Temporary failure (rate limit, network) worth retrying."""


class Provider:
    id = ""
    max_chars = 4500
    max_items = 10_000
    min_interval = 0.0  # seconds between requests

    def measure(self, text: str) -> int:
        return len(text)

    def translate_batch(self, lines: list[str], source: str, target: str) -> list[str]:
        raise NotImplementedError


# --------------------------------------------------------------------- Google
class GoogleProvider(Provider):
    id = "google"
    max_chars = 4500
    min_interval = 0.3
    _codes: ClassVar[dict[str, str]] = {"he": "iw", "zh": "zh-CN"}

    def _code(self, code: str) -> str:
        return self._codes.get(code, code)

    def translate_batch(self, lines, source, target):
        from deep_translator import GoogleTranslator
        from deep_translator.exceptions import (
            NotValidPayload,
            RequestError,
            TooManyRequests,
            TranslationNotFound,
        )

        translator = GoogleTranslator(source=self._code(source), target=self._code(target))

        def one(text: str) -> str:
            try:
                return translator.translate(text) or ""
            except TooManyRequests as exc:
                raise RetryableError("rate_limited", "Google Translate rate limit reached") from exc
            except (RequestError, requests.RequestException) as exc:
                raise RetryableError("network", f"Google Translate request failed: {exc}") from exc
            except (TranslationNotFound, NotValidPayload) as exc:
                raise TranslationError("bad_response", f"Google Translate returned no text: {exc}") from exc

        if len(lines) == 1:
            return [one(lines[0])]
        parts = one("\n".join(lines)).split("\n")
        if len(parts) == len(lines):
            return [p.strip() for p in parts]
        # The service merged or split lines: fall back to one request per line.
        result = []
        for line in lines:
            result.append(one(line))
            time.sleep(self.min_interval)
        return result


# ------------------------------------------------------------------- MyMemory
class MyMemoryProvider(Provider):
    id = "mymemory"
    max_chars = 480  # the API limit is 500 bytes per request
    min_interval = 0.2
    url = "https://api.mymemory.translated.net/get"
    _codes: ClassVar[dict[str, str]] = {"zh": "zh-CN"}

    def measure(self, text: str) -> int:
        return len(text.encode("utf-8"))

    def _code(self, code: str) -> str:
        return self._codes.get(code, code)

    def _request(self, text: str, source: str, target: str) -> str:
        try:
            resp = requests.get(
                self.url,
                params={"q": text, "langpair": f"{self._code(source)}|{self._code(target)}"},
                headers={"User-Agent": USER_AGENT},
                timeout=TIMEOUT,
            )
        except requests.RequestException as exc:
            raise RetryableError("network", f"MyMemory request failed: {exc}") from exc
        if resp.status_code == 429:
            raise TranslationError("quota_exceeded", "MyMemory daily limit reached")
        if resp.status_code >= 500:
            raise RetryableError("network", f"MyMemory HTTP {resp.status_code}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise RetryableError("bad_response", "MyMemory returned invalid JSON") from exc
        status = str(data.get("responseStatus", resp.status_code))
        translated = (data.get("responseData") or {}).get("translatedText") or ""
        if data.get("quotaFinished") or status == "429" or translated.startswith("MYMEMORY WARNING"):
            raise TranslationError("quota_exceeded", "MyMemory daily limit reached")
        if status != "200":
            raise TranslationError("bad_response", f"MyMemory error {status}: {data.get('responseDetails')}")
        return translated

    def translate_batch(self, lines, source, target):
        if len(lines) == 1:
            return [self._request(lines[0], source, target)]
        parts = self._request("\n".join(lines), source, target).split("\n")
        if len(parts) == len(lines):
            return [p.strip() for p in parts]
        result = []
        for line in lines:
            result.append(self._request(line, source, target))
            time.sleep(self.min_interval)
        return result


# ---------------------------------------------------------------------- DeepL
# Languages DeepL accepts (as source; targets add regional variants, see below).
DEEPL_SOURCE = frozenset(
    (
        "ar bg cs da de el en es et fi fr he hu id it ja ko lt lv nb nl pl pt ro ru sk sl sv th tr uk vi zh"
    ).split()
)
DEEPL_TARGET_OVERRIDES = {"en": "EN-US", "pt": "PT-BR", "zh": "ZH-HANS", "no": "NB"}


class DeepLProvider(Provider):
    id = "deepl"
    max_chars = 20_000
    max_items = 50

    def __init__(self, api_key: str) -> None:
        self.api_key = (api_key or "").strip()
        host = "api-free.deepl.com" if self.api_key.endswith(":fx") else "api.deepl.com"
        self.url = f"https://{host}/v2/translate"

    @staticmethod
    def target_code(code: str) -> str | None:
        base = "nb" if code == "no" else code
        if base not in DEEPL_SOURCE:
            return None
        return DEEPL_TARGET_OVERRIDES.get(code, code.upper())

    @staticmethod
    def source_code(code: str) -> str | None:
        base = "nb" if code == "no" else code
        return base.upper() if base in DEEPL_SOURCE else None

    def translate_batch(self, lines, source, target):
        if not self.api_key:
            raise TranslationError("deepl_key_missing", "DeepL API key is not set")
        target_code = self.target_code(target)
        if target_code is None:
            raise TranslationError(
                "language_unsupported", f"DeepL does not support '{target}'", language=target
            )
        payload: dict = {"text": lines, "target_lang": target_code}
        source_code = self.source_code(source)
        if source_code:
            payload["source_lang"] = source_code
        try:
            resp = requests.post(
                self.url,
                json=payload,
                headers={"Authorization": f"DeepL-Auth-Key {self.api_key}", "User-Agent": USER_AGENT},
                timeout=TIMEOUT,
            )
        except requests.RequestException as exc:
            raise RetryableError("network", f"DeepL request failed: {exc}") from exc
        if resp.status_code in (401, 403):
            raise TranslationError("deepl_key_invalid", "DeepL rejected the API key")
        if resp.status_code == 456:
            raise TranslationError("quota_exceeded", "DeepL character limit reached")
        if resp.status_code in (429, 500, 502, 503, 504, 529):
            raise RetryableError("rate_limited", f"DeepL HTTP {resp.status_code}")
        if resp.status_code != 200:
            raise TranslationError("bad_response", f"DeepL HTTP {resp.status_code}: {resp.text[:200]}")
        items = resp.json().get("translations") or []
        if len(items) != len(lines):
            raise TranslationError("bad_response", "DeepL returned a different number of lines")
        return [item.get("text", "") for item in items]


PROVIDERS = ("google", "mymemory", "deepl")


def make_chain(primary: str, deepl_key: str = "", fallback: bool = True) -> list[Provider]:
    """Build the ordered list of services to try."""

    def build(pid: str) -> Provider:
        if pid == "deepl":
            return DeepLProvider(deepl_key)
        if pid == "mymemory":
            return MyMemoryProvider()
        return GoogleProvider()

    primary = primary if primary in PROVIDERS else "google"
    chain = [build(primary)]
    if fallback:
        for pid in ("google", "mymemory"):
            if pid != primary:
                chain.append(build(pid))
    return chain


# -------------------------------------------------------------- batching core
_SENTENCE_END = re.compile(r"(?<=[.!?…。！？])\s+")


def split_long(text: str, limit: int, measure: Callable[[str], int]) -> list[str]:
    """Split ``text`` into pieces that each fit ``limit`` (by sentence, then by word)."""
    if measure(text) <= limit:
        return [text]
    pieces: list[str] = []
    current = ""
    for unit in _SENTENCE_END.split(text):
        words = [unit] if measure(unit) <= limit else unit.split(" ")
        for word in words:
            candidate = f"{current} {word}".strip()
            if measure(candidate) <= limit:
                current = candidate
                continue
            if current:
                pieces.append(current)
            while measure(word) > limit:  # a single giant token: hard cut
                cut = limit
                while measure(word[:cut]) > limit:
                    cut -= 1
                pieces.append(word[:cut])
                word = word[cut:]
            current = word
    if current:
        pieces.append(current)
    return pieces


def plan_batches(lines: Sequence[str], provider: Provider) -> list[list[int]]:
    """Group line indexes into requests that respect the provider limits."""
    batches: list[list[int]] = []
    current: list[int] = []
    size = 0
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        length = provider.measure(line) + 1
        if current and (size + length > provider.max_chars or len(current) >= provider.max_items):
            batches.append(current)
            current, size = [], 0
        current.append(index)
        size += length
    if current:
        batches.append(current)
    return batches


class Translator:
    """Translates lists of lines through a chain of providers."""

    def __init__(
        self,
        chain: list[Provider],
        stop_event: threading.Event | None = None,
        attempts: int = 3,
        backoff: float = 1.5,
    ) -> None:
        if not chain:
            raise ValueError("At least one provider is required")
        self.chain = chain
        self.stop_event = stop_event or threading.Event()
        self.attempts = attempts
        self.backoff = backoff
        self.used_provider: str | None = None
        self.warnings: list[str] = []

    def _wait(self, seconds: float) -> None:
        if self.stop_event.wait(seconds):
            raise Cancelled()

    def translate(
        self,
        lines: Sequence[str],
        source: str,
        target: str,
        on_progress: Callable[[float], None] | None = None,
    ) -> list[str]:
        last_error: TranslationError | None = None
        for provider in self.chain:
            try:
                result = self._translate_with(provider, list(lines), source, target, on_progress)
                self.used_provider = provider.id
                return result
            except TranslationError as exc:
                last_error = exc
                self.warnings.append(f"{provider.id}: {exc.message}")
                log.warning("Translation via %s failed: %s", provider.id, exc.message)
        assert last_error is not None
        raise last_error

    def _call(self, provider: Provider, lines: list[str], source: str, target: str) -> list[str]:
        delay = self.backoff
        for attempt in range(1, self.attempts + 1):
            if self.stop_event.is_set():
                raise Cancelled()
            try:
                return provider.translate_batch(lines, source, target)
            except RetryableError:
                if attempt == self.attempts:
                    raise
                self._wait(delay)
                delay *= 2
        raise AssertionError("unreachable")

    def _translate_with(self, provider, lines, source, target, on_progress) -> list[str]:
        result = [""] * len(lines)
        # Lines longer than one request are translated piece by piece.
        long_ones = {i for i, line in enumerate(lines) if provider.measure(line) + 1 > provider.max_chars}
        normal = [line if i not in long_ones else "" for i, line in enumerate(lines)]
        batches = plan_batches(normal, provider)
        total = len(batches) + len(long_ones) or 1
        done = 0
        for batch in batches:
            translated = self._call(provider, [lines[i] for i in batch], source, target)
            for index, text in zip(batch, translated, strict=False):
                result[index] = text
            done += 1
            if on_progress:
                on_progress(done / total)
            self._wait(provider.min_interval)
        for index in sorted(long_ones):
            pieces = split_long(lines[index], provider.max_chars - 1, provider.measure)
            result[index] = " ".join(self._call(provider, [p], source, target)[0] for p in pieces)
            done += 1
            if on_progress:
                on_progress(done / total)
            self._wait(provider.min_interval)
        return result
