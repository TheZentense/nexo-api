import hashlib
import io

import pytest
from PIL import Image

from app.modules.media.image import convert_image


@pytest.mark.parametrize("format", ["JPEG", "PNG", "WEBP"])
def test_supported_formats_and_private_metadata(tmp_path, format):
    source = tmp_path / "original"
    exif = Image.Exif()
    exif[0x010E] = "Private description"
    Image.new("RGB", (1800, 900), "green").save(source, format, exif=exif)
    original = hashlib.sha256(source.read_bytes()).digest()
    variants = convert_image(source, tmp_path / "web", max_bytes=15_000_000, max_pixels=25_000_000)
    assert list(variants) == ["w480", "w960", "w1600"]
    for label, info in variants.items():
        with Image.open(tmp_path / "web" / f"{label}.webp") as image:
            assert image.format == "WEBP"
            assert image.size == (info["width"], info["height"])
            assert (
                not image.getexif()
                and not image.info.get("xmp")
                and not image.info.get("icc_profile")
            )
    assert hashlib.sha256(source.read_bytes()).digest() == original


def test_orientation_and_no_upscaling(tmp_path):
    source = tmp_path / "original"
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (80, 40), "red").save(source, "JPEG", exif=exif)
    variants = convert_image(source, tmp_path / "web", max_bytes=100000, max_pixels=10000)
    assert len(variants) == 1
    assert (variants["w480"]["width"], variants["w480"]["height"]) == (40, 80)


def test_transparency_is_preserved(tmp_path):
    source = tmp_path / "original"
    Image.new("RGBA", (100, 100), (0, 100, 0, 0)).save(source, "PNG")
    convert_image(source, tmp_path / "web", max_bytes=10000, max_pixels=10000)
    with Image.open(tmp_path / "web" / "w480.webp") as image:
        assert image.getpixel((20, 20))[3] == 0


@pytest.mark.parametrize("case", ["animated", "pixels", "bytes", "fake", "truncated"])
def test_invalid_images_do_not_create_variants(tmp_path, case):
    source = tmp_path / "original"
    image = Image.new("RGB", (100, 100), "green")
    image.save(source, "PNG")
    if case == "animated":
        image.save(
            source,
            "WEBP",
            save_all=True,
            append_images=[Image.new("RGB", image.size, "red")],
            duration=100,
        )
    if case == "fake":
        source.write_bytes(b"not an image")
    if case == "truncated":
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        source.write_bytes(buffer.getvalue()[:50])
    with pytest.raises((ValueError, OSError)):
        convert_image(
            source,
            tmp_path / "web",
            max_bytes=1 if case == "bytes" else 10000,
            max_pixels=100 if case == "pixels" else 10000,
        )
    assert not (tmp_path / "web").exists()
