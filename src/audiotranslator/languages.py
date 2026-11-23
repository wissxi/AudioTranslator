"""Languages offered in the interface.

Every language here is supported by Whisper for recognition and by the
translation services for output. Codes are ISO 639-1 as used by Whisper.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Language:
    code: str
    en: str
    ru: str
    native: str


LANGUAGES: tuple[Language, ...] = (
    Language("en", "English", "Английский", "English"),
    Language("ru", "Russian", "Русский", "Русский"),
    Language("uk", "Ukrainian", "Украинский", "Українська"),
    Language("be", "Belarusian", "Белорусский", "Беларуская"),
    Language("kk", "Kazakh", "Казахский", "Қазақша"),
    Language("uz", "Uzbek", "Узбекский", "Oʻzbekcha"),
    Language("de", "German", "Немецкий", "Deutsch"),
    Language("fr", "French", "Французский", "Français"),
    Language("es", "Spanish", "Испанский", "Español"),
    Language("it", "Italian", "Итальянский", "Italiano"),
    Language("pt", "Portuguese", "Португальский", "Português"),
    Language("nl", "Dutch", "Нидерландский", "Nederlands"),
    Language("pl", "Polish", "Польский", "Polski"),
    Language("cs", "Czech", "Чешский", "Čeština"),
    Language("sk", "Slovak", "Словацкий", "Slovenčina"),
    Language("sl", "Slovenian", "Словенский", "Slovenščina"),
    Language("hr", "Croatian", "Хорватский", "Hrvatski"),
    Language("sr", "Serbian", "Сербский", "Српски"),
    Language("bg", "Bulgarian", "Болгарский", "Български"),
    Language("ro", "Romanian", "Румынский", "Română"),
    Language("hu", "Hungarian", "Венгерский", "Magyar"),
    Language("el", "Greek", "Греческий", "Ελληνικά"),
    Language("sv", "Swedish", "Шведский", "Svenska"),
    Language("no", "Norwegian", "Норвежский", "Norsk"),
    Language("da", "Danish", "Датский", "Dansk"),
    Language("fi", "Finnish", "Финский", "Suomi"),
    Language("et", "Estonian", "Эстонский", "Eesti"),
    Language("lv", "Latvian", "Латышский", "Latviešu"),
    Language("lt", "Lithuanian", "Литовский", "Lietuvių"),
    Language("tr", "Turkish", "Турецкий", "Türkçe"),
    Language("az", "Azerbaijani", "Азербайджанский", "Azərbaycanca"),
    Language("ka", "Georgian", "Грузинский", "ქართული"),
    Language("hy", "Armenian", "Армянский", "Հայերեն"),
    Language("ar", "Arabic", "Арабский", "العربية"),
    Language("he", "Hebrew", "Иврит", "עברית"),
    Language("fa", "Persian", "Персидский", "فارسی"),
    Language("hi", "Hindi", "Хинди", "हिन्दी"),
    Language("ur", "Urdu", "Урду", "اردو"),
    Language("bn", "Bengali", "Бенгальский", "বাংলা"),
    Language("th", "Thai", "Тайский", "ไทย"),
    Language("vi", "Vietnamese", "Вьетнамский", "Tiếng Việt"),
    Language("id", "Indonesian", "Индонезийский", "Bahasa Indonesia"),
    Language("ms", "Malay", "Малайский", "Bahasa Melayu"),
    Language("zh", "Chinese", "Китайский", "中文"),
    Language("ja", "Japanese", "Японский", "日本語"),
    Language("ko", "Korean", "Корейский", "한국어"),
)

BY_CODE = {lang.code: lang for lang in LANGUAGES}


def is_supported(code: str | None) -> bool:
    return code in BY_CODE


def display_name(code: str | None, ui: str = "en") -> str:
    lang = BY_CODE.get(code or "")
    if lang is None:
        return (code or "").upper()
    return lang.ru if ui == "ru" else lang.en


def as_dicts() -> list[dict[str, str]]:
    return [asdict(lang) for lang in LANGUAGES]
