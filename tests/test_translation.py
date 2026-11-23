import threading

import pytest

from audiotranslator.core import translation as tr
from audiotranslator.errors import Cancelled, TranslationError


class Echo(tr.Provider):
    """Uppercases text; records every batch it receives."""

    id = "echo"
    max_chars = 30

    def __init__(self):
        self.batches = []

    def translate_batch(self, lines, source, target):
        self.batches.append(list(lines))
        return [line.upper() for line in lines]


class Flaky(tr.Provider):
    id = "flaky"

    def __init__(self, failures, error=tr.RetryableError):
        self.failures = failures
        self.error = error
        self.calls = 0

    def translate_batch(self, lines, source, target):
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error("rate_limited", "slow down")
        return [f"ok:{line}" for line in lines]


def test_plan_batches_respects_limits_and_skips_blank():
    provider = Echo()
    provider.max_chars = 25  # "aaaa\n" + "bbbbbbbbbb\n" = 16; adding the next line would make 27
    lines = ["aaaa", "", "bbbbbbbbbb", "cccccccccc", "dd"]
    assert tr.plan_batches(lines, provider) == [[0, 2], [3, 4]]


def test_plan_batches_respects_item_limit():
    provider = Echo()
    provider.max_items = 2
    assert tr.plan_batches(["a", "b", "c"], provider) == [[0, 1], [2]]


def test_split_long_by_sentence_then_word():
    text = "First sentence here. Second one is a little longer than that. Third."
    pieces = tr.split_long(text, 25, len)
    assert all(len(p) <= 25 for p in pieces)
    assert " ".join(pieces).split() == text.split()


def test_split_long_hard_cuts_giant_tokens():
    pieces = tr.split_long("x" * 50, 20, len)
    assert pieces == ["x" * 20, "x" * 20, "x" * 10]


def test_translator_keeps_alignment_and_blanks():
    provider = Echo()
    result = tr.Translator([provider]).translate(["hello", "", "world"], "en", "ru")
    assert result == ["HELLO", "", "WORLD"]
    assert provider.batches == [["hello", "world"]]


def test_translator_splits_long_lines():
    provider = Echo()
    line = "one two three four five six seven eight nine ten eleven"
    result = tr.Translator([provider]).translate([line], "en", "ru")
    assert result == [line.upper()]
    assert len(provider.batches) > 1


def test_retry_then_success():
    provider = Flaky(failures=2)
    translator = tr.Translator([provider], backoff=0.001)
    assert translator.translate(["a"], "en", "ru") == ["ok:a"]
    assert provider.calls == 3
    assert translator.used_provider == "flaky"


def test_fallback_to_next_provider():
    broken = Flaky(failures=99, error=TranslationError)
    good = Echo()
    translator = tr.Translator([broken, good], backoff=0.001)
    assert translator.translate(["a"], "en", "ru") == ["A"]
    assert broken.calls == 1  # non-retryable errors are not retried
    assert translator.used_provider == "echo"
    assert translator.warnings and translator.warnings[0].startswith("flaky:")


def test_all_providers_fail_raises_last_error():
    translator = tr.Translator([Flaky(99, TranslationError)], backoff=0.001)
    with pytest.raises(TranslationError):
        translator.translate(["a"], "en", "ru")


def test_cancel_during_backoff():
    stop = threading.Event()
    stop.set()
    with pytest.raises(Cancelled):
        tr.Translator([Flaky(1)], stop_event=stop).translate(["a"], "en", "ru")


def test_make_chain():
    assert [p.id for p in tr.make_chain("google")] == ["google", "mymemory"]
    assert [p.id for p in tr.make_chain("deepl", "k")] == ["deepl", "google", "mymemory"]
    assert [p.id for p in tr.make_chain("mymemory", fallback=False)] == ["mymemory"]
    assert next(p.id for p in tr.make_chain("nonsense")) == "google"


# ------------------------------------------------------------------ Google
class FakeGoogle:
    responses: list = []
    created: list = []

    def __init__(self, source, target):
        FakeGoogle.created.append((source, target))

    def translate(self, text):
        return FakeGoogle.responses.pop(0)(text)


@pytest.fixture
def fake_google(monkeypatch):
    import deep_translator

    FakeGoogle.responses = []
    FakeGoogle.created = []
    monkeypatch.setattr(deep_translator, "GoogleTranslator", FakeGoogle)
    monkeypatch.setattr(tr.GoogleProvider, "min_interval", 0)
    return FakeGoogle


def test_google_batch_joined_with_newlines(fake_google):
    fake_google.responses = [lambda text: text.replace("a", "б")]
    out = tr.GoogleProvider().translate_batch(["a1", "a2"], "he", "zh")
    assert out == ["б1", "б2"]
    assert fake_google.created == [("iw", "zh-CN")]


def test_google_falls_back_to_single_lines_on_mismatch(fake_google):
    fake_google.responses = [lambda text: "merged", lambda text: "x", lambda text: "y"]
    assert tr.GoogleProvider().translate_batch(["a", "b"], "en", "ru") == ["x", "y"]


def test_google_rate_limit_is_retryable(fake_google):
    from deep_translator.exceptions import TooManyRequests

    def boom(text):
        raise TooManyRequests()

    fake_google.responses = [boom]
    with pytest.raises(tr.RetryableError):
        tr.GoogleProvider().translate_batch(["a"], "en", "ru")


# ---------------------------------------------------------------- MyMemory
class FakeResponse:
    def __init__(self, status, data=None, text=""):
        self.status_code = status
        self._data = data
        self.text = text

    def json(self):
        if self._data is None:
            raise ValueError("no json")
        return self._data


def test_mymemory_ok(monkeypatch):
    seen = {}

    def fake_get(url, params, headers, timeout):
        seen.update(params)
        return FakeResponse(200, {"responseStatus": 200, "responseData": {"translatedText": "Привет"}})

    monkeypatch.setattr(tr.requests, "get", fake_get)
    assert tr.MyMemoryProvider().translate_batch(["Hello"], "en", "zh") == ["Привет"]
    assert seen["langpair"] == "en|zh-CN"


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(429, {"responseStatus": 429}),
        FakeResponse(200, {"responseStatus": 200, "quotaFinished": True, "responseData": {}}),
        FakeResponse(
            200, {"responseStatus": "429", "responseData": {"translatedText": "MYMEMORY WARNING: ..."}}
        ),
    ],
)
def test_mymemory_quota(monkeypatch, response):
    monkeypatch.setattr(tr.requests, "get", lambda *a, **k: response)
    with pytest.raises(TranslationError) as info:
        tr.MyMemoryProvider().translate_batch(["Hello"], "en", "ru")
    assert info.value.code == "quota_exceeded"
    assert not isinstance(info.value, tr.RetryableError)


def test_mymemory_measures_bytes():
    assert tr.MyMemoryProvider().measure("привет") == 12


# ------------------------------------------------------------------- DeepL
def test_deepl_codes():
    assert tr.DeepLProvider.target_code("en") == "EN-US"
    assert tr.DeepLProvider.target_code("pt") == "PT-BR"
    assert tr.DeepLProvider.target_code("zh") == "ZH-HANS"
    assert tr.DeepLProvider.target_code("no") == "NB"
    assert tr.DeepLProvider.target_code("ru") == "RU"
    assert tr.DeepLProvider.target_code("ka") is None
    assert tr.DeepLProvider.source_code("ka") is None
    assert tr.DeepLProvider.source_code("en") == "EN"


def test_deepl_endpoint_by_key():
    assert "api-free" in tr.DeepLProvider("abc:fx").url
    assert "api-free" not in tr.DeepLProvider("abc").url


def test_deepl_request(monkeypatch):
    seen = {}

    def fake_post(url, json, headers, timeout):
        seen.update(url=url, json=json, headers=headers)
        return FakeResponse(200, {"translations": [{"text": "Привет"}, {"text": "Мир"}]})

    monkeypatch.setattr(tr.requests, "post", fake_post)
    out = tr.DeepLProvider("secret:fx").translate_batch(["Hello", "World"], "en", "ru")
    assert out == ["Привет", "Мир"]
    assert seen["json"] == {"text": ["Hello", "World"], "target_lang": "RU", "source_lang": "EN"}
    assert seen["headers"]["Authorization"] == "DeepL-Auth-Key secret:fx"


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [(403, "deepl_key_invalid", False), (456, "quota_exceeded", False), (429, "rate_limited", True)],
)
def test_deepl_errors(monkeypatch, status, code, retryable):
    monkeypatch.setattr(tr.requests, "post", lambda *a, **k: FakeResponse(status, {}))
    with pytest.raises(TranslationError) as info:
        tr.DeepLProvider("k").translate_batch(["Hello"], "en", "ru")
    assert info.value.code == code
    assert isinstance(info.value, tr.RetryableError) is retryable


def test_deepl_requires_key_and_language():
    with pytest.raises(TranslationError) as info:
        tr.DeepLProvider("").translate_batch(["x"], "en", "ru")
    assert info.value.code == "deepl_key_missing"
    with pytest.raises(TranslationError) as info:
        tr.DeepLProvider("k").translate_batch(["x"], "en", "ka")
    assert info.value.code == "language_unsupported"
