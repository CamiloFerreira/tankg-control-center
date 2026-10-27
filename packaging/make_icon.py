"""Renders packaging/icon.svg (the brand icon) into every file that needs a bitmap: icon.png and
icon.ico (desktop), the Android launcher mipmaps and the README logo. Run after editing the SVG;
the outputs are committed. The APK's web UI uses android/ui/img/icon.svg (a copy of the SVG)."""
import shutil
import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SVG = HERE / "icon.svg"


def draw(renderer: QSvgRenderer, size: int) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    renderer.render(p)
    p.end()
    return img


def png_bytes(img: QImage) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(data)


def write_ico(renderer: QSvgRenderer, path: Path, sizes=(16, 24, 32, 48, 64, 128, 256)) -> None:
    """Multi-size .ico with PNG entries (Windows Vista and later)."""
    blobs = [png_bytes(draw(renderer, s)) for s in sizes]
    out = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    for s, b in zip(sizes, blobs):
        out += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(b), offset)
        offset += len(b)
    path.write_bytes(out + b"".join(blobs))


if __name__ == "__main__":
    app = QGuiApplication(sys.argv[:1] + ["-platform", "offscreen"])
    r = QSvgRenderer(str(SVG))
    draw(r, 256).save(str(HERE / "icon.png"))
    write_ico(r, HERE / "icon.ico")
    for density, size in (("xhdpi", 96), ("xxxhdpi", 192)):
        draw(r, size).save(str(ROOT / f"android/res/mipmap-{density}/ic_launcher.png"))
    draw(r, 128).save(str(ROOT / "docs/img/logo.png"))
    shutil.copyfile(SVG, ROOT / "android/ui/img/icon.svg")
    print("ok")
