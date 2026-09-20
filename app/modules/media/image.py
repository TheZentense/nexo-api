"""Genera copias para la web y deja el original intacto."""

import warnings
from pathlib import Path

from PIL import Image, ImageOps


def has_image_header(source: Path) -> bool:
    with source.open("rb") as stream:
        header = stream.read(16)
    return header.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")) or (
        header[:4] == b"RIFF" and header[8:12] == b"WEBP"
    )


def convert_image(source: Path, destination: Path, *, max_bytes: int, max_pixels: int):
    if not 0 < source.stat().st_size <= max_bytes:
        raise ValueError("Image exceeds the file size limit or is empty")
    # Se ejecuta en el subproceso del worker, con tiempo de ejecución limitado.
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(source, formats=["JPEG", "PNG", "WEBP"]) as original:
            if (
                original.width * original.height > max_pixels
                or getattr(original, "n_frames", 1) != 1
            ):
                raise ValueError("Image exceeds the pixel limit or is animated")
            original.load()
            picture = ImageOps.exif_transpose(original)
            picture = picture.convert(
                "RGBA" if "A" in picture.getbands() or "transparency" in picture.info else "RGB"
            )
            picture.info.clear()
    destination.mkdir(parents=True, exist_ok=False)
    outputs = []
    try:
        variants, sizes = {}, set()
        for width in (480, 960, 1600):
            resized = picture.copy()
            resized.thumbnail((width, 1600), Image.Resampling.LANCZOS)
            if resized.size in sizes:
                continue
            sizes.add(resized.size)
            label = f"w{width}"
            output = destination / f"{label}.webp"
            outputs.append(output)
            resized.save(output, "WEBP", quality=80, method=4, exif=b"", icc_profile=b"", xmp=b"")
            variants[label] = {
                "width": resized.width,
                "height": resized.height,
                "size_bytes": output.stat().st_size,
            }
        return variants
    except Exception:
        for output in outputs:
            output.unlink(missing_ok=True)
        destination.rmdir()
        raise
