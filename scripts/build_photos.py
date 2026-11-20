"""Build and validate photo assets before publishing the site."""
import sys
from io import BytesIO
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from campus_photos import SOURCES, WIDTHS, render_photo

for name, url in SOURCES.items():
    req = Request(url, headers={"User-Agent": "CampusServiceDesk/1.0 (https://github.com/Aloysiouskyle/campus-service-desk)"})
    with urlopen(req, timeout=45) as source:
        original = source.read()
    folder = ROOT / "public" / "campus-photos" / name
    folder.mkdir(parents=True, exist_ok=True)
    for width in WIDTHS:
        data, height = render_photo(BytesIO(original), width)
        (folder / f"{width}.webp").write_bytes(data)
        print(f"{name}: {width}x{height}, {len(data)} bytes")
