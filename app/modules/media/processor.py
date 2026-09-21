"""Este proceso recibe archivos temporales, sin credenciales de la aplicación."""

import json
import sys
from pathlib import Path

from app.modules.media.image import convert_image
from app.modules.media.video import convert_video, run


def main():
    source, destination = Path(sys.argv[1]), Path(sys.argv[2])
    if len(sys.argv) > 5 and sys.argv[5] == "image":
        variants = convert_image(
            source, destination, max_bytes=int(sys.argv[3]), max_pixels=int(sys.argv[4])
        )
        (destination / "manifest.json").write_text(json.dumps(variants), encoding="utf-8")
        return
    output = convert_video(
        source, destination, max_bytes=int(sys.argv[3]), max_seconds=int(sys.argv[4])
    )
    run(
        [
            "-protocol_whitelist",
            "file",
            "-i",
            str(output),
            "-frames:v",
            "1",
            "-vf",
            "scale=w='min(960,iw)':h=-2",
            "-threads",
            "1",
            "-filter_threads",
            "1",
            "-map_metadata",
            "-1",
            "-q:v",
            "3",
            str(destination / "poster.jpg"),
        ]
    )


if __name__ == "__main__":
    main()
