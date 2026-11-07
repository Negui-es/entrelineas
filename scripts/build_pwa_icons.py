"""Export the existing vector symbol as opaque, antialiased mobile app icons."""
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent


def outline(data):
    tokens = iter(re.findall(r"[MCVZ]|-?\d+(?:\.\d+)?", data))
    points, current = [], (0, 0)
    for command in tokens:
        if command == "M":
            current = float(next(tokens)), float(next(tokens))
            points.append(current)
        elif command == "V":
            current = current[0], float(next(tokens))
            points.append(current)
        elif command == "C":
            a = float(next(tokens)), float(next(tokens))
            b = float(next(tokens)), float(next(tokens))
            end = float(next(tokens)), float(next(tokens))
            for step in range(1, 49):
                t = step / 48
                points.append(tuple((1-t)**3 * current[i] + 3*(1-t)**2*t*a[i] + 3*(1-t)*t*t*b[i] + t**3*end[i] for i in range(2)))
            current = end
        elif command != "Z":
            raise ValueError("Unsupported symbol path command: " + command)
    return points


def main():
    svg = ET.parse(ROOT / "static/brand/entrelineas-symbol-white.svg").getroot()
    paths = list(svg.iter("{http://www.w3.org/2000/svg}path"))
    folder = ROOT / "static/pwa"
    folder.mkdir(exist_ok=True)
    for name, size, fraction in [("icon-192.png", 192, .72), ("icon-512.png", 512, .72),
                                 ("icon-maskable-512.png", 512, .58), ("apple-touch-icon.png", 180, .72)]:
        scale = size * fraction / 512
        x, y = size * (1-fraction) / 2, (size - 412*scale) / 2
        image = Image.new("RGB", (size*4, size*4), "#6845a5")
        draw = ImageDraw.Draw(image)
        for path in paths:
            points = outline(path.attrib["d"])
            transform = path.get("transform", "")
            if transform:
                if transform != "translate(512 0) scale(-1 1)":
                    raise ValueError("Unexpected symbol transform")
                points = [(512-px, py) for px, py in points]
            draw.polygon([((x+px*scale)*4, (y+py*scale)*4) for px, py in points], fill="white")
        image.resize((size, size), Image.Resampling.LANCZOS).save(folder / name, optimize=True)
    print("Mobile icons exported from the Entrelíneas symbol.")


if __name__ == "__main__":
    main()
