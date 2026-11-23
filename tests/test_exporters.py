from pathlib import Path

from audiotranslator.core import exporters
from audiotranslator.core.models import Segment, Transcript


def make_transcript(tmp_path: Path, translated: bool = True) -> Transcript:
    segments = [
        Segment(0.0, 1.25, "Hello there.", "Привет." if translated else ""),
        Segment(1.5, 3.0, "How are you?", "Как дела?" if translated else ""),
        Segment(6.0, 7.5, "Goodbye.", "Пока." if translated else ""),
    ]
    return Transcript(
        source=tmp_path / "talk.mp3",
        language="en",
        language_probability=0.97,
        duration=7.5,
        segments=segments,
        target_language="ru",
    )


def test_format_timestamp():
    assert exporters.format_timestamp(0) == "00:00:00,000"
    assert exporters.format_timestamp(3725.5) == "01:02:05,500"
    assert exporters.format_timestamp(59.9996) == "00:01:00,000"
    assert exporters.format_timestamp(1.5, ".") == "00:00:01.500"
    assert exporters.format_timestamp(-3) == "00:00:00,000"


def test_format_duration():
    assert exporters.format_duration(11) == "0:11"
    assert exporters.format_duration(3725) == "1:02:05"


def test_paragraphs_break_on_pauses(tmp_path):
    transcript = make_transcript(tmp_path)
    assert exporters.paragraphs(transcript.segments) == ["Hello there. How are you?", "Goodbye."]
    assert exporters.paragraphs(transcript.segments, "translation") == ["Привет. Как дела?", "Пока."]


def test_render_srt(tmp_path):
    srt = exporters.render_srt(make_transcript(tmp_path).segments, "translation")
    assert srt.startswith("1\n00:00:00,000 --> 00:00:01,250\nПривет.\n")
    assert "3\n00:00:06,000 --> 00:00:07,500\nПока.\n" in srt


def test_render_vtt(tmp_path):
    vtt = exporters.render_vtt(make_transcript(tmp_path).segments)
    assert vtt.startswith("WEBVTT\n\n00:00:00.000 --> 00:00:01.250\nHello there.\n")


def test_srt_skips_empty_and_extends_zero_length(tmp_path):
    segments = [Segment(1.0, 1.0, "Blink."), Segment(2.0, 3.0, "  ")]
    srt = exporters.render_srt(segments)
    assert srt == "1\n00:00:01,000 --> 00:00:01,200\nBlink.\n"


def test_write_outputs_names(tmp_path):
    transcript = make_transcript(tmp_path)
    written = exporters.write_outputs(
        transcript, ["txt", "srt", "vtt", "json"], include_original=True, ui="ru"
    )
    names = sorted(p.name for p in written)
    assert names == [
        "talk.en.srt",
        "talk.en.vtt",
        "talk.json",
        "talk.ru.srt",
        "talk.ru.vtt",
        "talk.txt",
    ]
    txt = (tmp_path / "talk.txt").read_text(encoding="utf-8")
    assert "Оригинал (EN, Английский):" in txt
    assert "Перевод (RU, Русский):" in txt
    assert "Привет. Как дела?\n\nПока." in txt


def test_write_outputs_without_original(tmp_path):
    transcript = make_transcript(tmp_path)
    written = exporters.write_outputs(transcript, ["srt", "txt"], include_original=False)
    assert sorted(p.name for p in written) == ["talk.ru.srt", "talk.txt"]
    assert "Original" not in (tmp_path / "talk.txt").read_text(encoding="utf-8")


def test_untranslated_writes_original_track(tmp_path):
    transcript = make_transcript(tmp_path, translated=False)
    transcript.translation_error = "quota"
    written = exporters.write_outputs(transcript, ["srt", "txt"], include_original=False, ui="en")
    assert sorted(p.name for p in written) == ["talk.en.srt", "talk.txt"]
    txt = (tmp_path / "talk.txt").read_text(encoding="utf-8")
    assert "Hello there." in txt
    assert "(translation failed: quota)" in txt


def test_custom_output_dir_and_report(tmp_path):
    out = tmp_path / "out"
    transcript = make_transcript(tmp_path)
    exporters.write_outputs(transcript, ["txt"], output_dir=out)
    assert (out / "talk.txt").exists()
    report = exporters.write_report([transcript, transcript], out, ui="en")
    text = report.read_text(encoding="utf-8")
    assert report.name == "translations.txt"
    assert text.count("File: talk.mp3") == 2
    assert text.startswith("AudioTranslator — 2 files")


def test_common_folder(tmp_path):
    a = tmp_path / "x" / "a.mp3"
    b = tmp_path / "x" / "y" / "b.mp3"
    assert exporters.common_folder([a, b]) == tmp_path / "x"
