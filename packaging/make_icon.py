"""Draws packaging/icon.png and icon.ico (run once; the files are committed)."""
import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QLinearGradient, QPainter, QPen, QRadialGradient

HERE = Path(__file__).resolve().parent


def draw(size: int) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 256
    body = QLinearGradient(0, 0, 0, size)
    body.setColorAt(0, QColor("#38b3b0"))
    body.setColorAt(1, QColor("#1c7674"))
    p.setPen(QPen(QColor("#0f4f4e"), 6 * s))
    p.setBrush(body)
    p.drawRoundedRect(QRectF(12 * s, 12 * s, 232 * s, 232 * s), 44 * s, 44 * s)
    # footswitch
    ring = QRadialGradient(128 * s, 150 * s, 62 * s)
    ring.setColorAt(0, QColor("#ffd34d"))
    ring.setColorAt(1, QColor("#ff8a00"))
    p.setPen(Qt.NoPen)
    p.setBrush(ring)
    p.drawEllipse(QRectF(70 * s, 92 * s, 116 * s, 116 * s))
    cap = QRadialGradient(118 * s, 138 * s, 50 * s)
    cap.setColorAt(0, QColor("#e2e5e9"))
    cap.setColorAt(1, QColor("#5d6168"))
    p.setBrush(cap)
    p.drawEllipse(QRectF(86 * s, 108 * s, 84 * s, 84 * s))
    # label
    p.setPen(QColor("#0b2b2a"))
    f = QFont("DejaVu Sans", max(1, int(34 * s)))
    f.setBold(True)
    p.setFont(f)
    p.drawText(QRectF(0, 26 * s, size, 50 * s), Qt.AlignCenter, "TANK-G")
    p.end()
    return img


if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    draw(256).save(str(HERE / "icon.png"))
    ok = draw(256).save(str(HERE / "icon.ico"))
    print("png ok, ico", "ok" if ok else "FAILED")
