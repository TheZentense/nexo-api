import hashlib

import pytest

from app.modules.media.video import InvalidVideo, convert_video, inspect_video, run


def sample(path, codec="libx264", size="160x90"):
    run(
        [
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size={size}:rate=10",
            "-t",
            "0.5",
            "-c:v",
            codec,
            "-threads",
            "1",
            str(path),
        ]
    )
    return path


@pytest.mark.parametrize(
    "extension,codec",
    [
        ("mp4", "libx264"),
        ("mov", "libx264"),
        ("webm", "libvpx-vp9"),
    ],
)
def test_convert_real_formats_preserves_original(tmp_path, extension, codec):
    source = sample(tmp_path / f"original.{extension}", codec)
    original_hash = hashlib.sha256(source.read_bytes()).digest()
    output = convert_video(source, tmp_path / "converted")
    assert output.name == "web720.mp4"
    assert inspect_video(output)["width"] == 160
    assert hashlib.sha256(source.read_bytes()).digest() == original_hash
    data = output.read_bytes()
    assert data.index(b"moov") < data.index(b"mdat")


def test_fake_video_is_rejected(tmp_path):
    source = tmp_path / "fake.mp4"
    source.write_bytes(b"This is not a video")
    with pytest.raises(InvalidVideo):
        convert_video(source, tmp_path / "converted")
    assert not (tmp_path / "converted").exists()


def test_corrupt_container_is_rejected(tmp_path):
    source = tmp_path / "broken.mp4"
    source.write_bytes(b"\x00\x00\x00\x18ftypisom" + bytes(100))
    with pytest.raises(InvalidVideo):
        inspect_video(source)


def test_limits_and_existing_destination(tmp_path):
    source = sample(tmp_path / "video.mp4")
    with pytest.raises(InvalidVideo):
        inspect_video(source, max_bytes=10)
    with pytest.raises(InvalidVideo):
        inspect_video(source, max_seconds=0.1)
    with pytest.raises(FileExistsError):
        convert_video(source, tmp_path)


def test_audio_only_is_rejected(tmp_path):
    source = tmp_path / "audio.mp4"
    run(["-f", "lavfi", "-i", "sine=frequency=440", "-t", "0.5", str(source)])
    with pytest.raises(InvalidVideo):
        inspect_video(source)


def test_portrait_video_keeps_proportions(tmp_path):
    source = sample(tmp_path / "portrait.mp4", size="900x1600")
    output = convert_video(source, tmp_path / "converted")
    dimensions = inspect_video(output)
    assert dimensions["height"] == 720
    assert abs(dimensions["width"] / dimensions["height"] - 900 / 1600) < 0.01


def test_failed_conversion_removes_partial_output(tmp_path, monkeypatch):
    source = sample(tmp_path / "video.mp4")
    destination = tmp_path / "converted"
    from app.modules.media import video

    original_run = video.run

    def fail_conversion(arguments, timeout=30):
        if timeout == 150:
            (destination / "web720.mp4").write_bytes(b"partial")
            raise InvalidVideo("Video could not be processed")
        return original_run(arguments, timeout)

    monkeypatch.setattr(video, "run", fail_conversion)
    with pytest.raises(InvalidVideo):
        convert_video(source, destination)
    assert source.exists()
    assert not destination.exists()
