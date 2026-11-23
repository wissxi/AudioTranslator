import numpy as np
import pytest

from audiotranslator.core import media
from audiotranslator.errors import MediaError


def test_is_media_and_kind():
    assert media.is_media("a.MP3")
    assert media.is_media("b.mkv")
    assert not media.is_media("c.txt")
    assert media.media_kind("x.mp4") == "video"
    assert media.media_kind("x.flac") == "audio"


def test_natural_sort_key():
    names = ["part 10.mp3", "part 2.mp3", "Part 1.mp3"]
    assert sorted(names, key=media.natural_key) == ["Part 1.mp3", "part 2.mp3", "part 10.mp3"]


def test_collect_media(tmp_path):
    folder = tmp_path / "lectures"
    (folder / "extra").mkdir(parents=True)
    for name in ["lesson 10.mp3", "lesson 2.mp4", "notes.txt"]:
        (folder / name).write_bytes(b"x")
    (folder / "extra" / "bonus.wav").write_bytes(b"x")
    single = tmp_path / "single.m4a"
    single.write_bytes(b"x")

    found = media.collect_media([single, folder, single, tmp_path / "missing.mp3", ""])
    assert [p.name for p in found] == ["single.m4a", "bonus.wav", "lesson 2.mp4", "lesson 10.mp3"]

    shallow = media.collect_media([folder], recursive=False)
    assert [p.name for p in shallow] == ["lesson 2.mp4", "lesson 10.mp3"]


def test_decode_audio_resamples_to_mono_16k(wav_file):
    audio = media.decode_audio(wav_file)
    assert audio.dtype == np.float32
    assert audio.ndim == 1
    assert abs(audio.size - 24_000) <= 16  # 1.5 s at 16 kHz
    assert 0.3 < float(np.abs(audio).max()) < 0.5


def test_probe_duration(wav_file):
    assert media.probe_duration(wav_file) == pytest.approx(1.5, abs=0.05)
    assert media.probe_duration(wav_file.with_name("nope.wav")) is None


def test_decode_missing_file(tmp_path):
    with pytest.raises(MediaError) as info:
        media.decode_audio(tmp_path / "missing.mp3")
    assert info.value.code == "file_not_found"


def test_decode_garbage(tmp_path):
    bad = tmp_path / "bad.mp3"
    bad.write_text("this is not audio")
    with pytest.raises(MediaError) as info:
        media.decode_audio(bad)
    assert info.value.code in ("decode_failed", "no_audio")


def test_waveform_peaks():
    audio = np.concatenate([np.zeros(1000), np.full(1000, 0.5)]).astype(np.float32)
    peaks = media.waveform_peaks(audio, bins=4)
    assert peaks == [0.0, 0.0, 1.0, 1.0]
    assert media.waveform_peaks(np.zeros(0, dtype=np.float32)) == []
    assert len(media.waveform_peaks(np.ones(10, dtype=np.float32), bins=50)) == 10
