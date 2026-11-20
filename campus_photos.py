"""Serve fixed, photo-specific WebP renditions through the deployment CDN."""
from functools import lru_cache
from io import BytesIO
from urllib.error import URLError
from urllib.request import Request, urlopen

from flask import Blueprint, Response, abort, redirect, request
from PIL import Image, ImageFilter, ImageOps

photos = Blueprint("photos", __name__)
COMMONS = "https://upload.wikimedia.org/wikipedia/commons/"
SOURCES = {
    "hamu-mukasa": COMMONS + "c/c3/Hamu_Mukasa_Library.jpg",
    "bishop-tucker": COMMONS + "6/61/The_Bishop_Tucker_Building_-_UCU_Mukono_05.jpg",
}
WIDTHS = (960, 1920, 3840)


def render_photo(source, width):
    with Image.open(source) as original:
        photo = ImageOps.exif_transpose(original).convert("RGB")
        height = round(photo.height * width / photo.width)
        enlarged = width > photo.width
        photo = photo.resize((width, height), Image.Resampling.LANCZOS)
        if enlarged:
            photo = photo.filter(ImageFilter.UnsharpMask(radius=1.2, percent=90, threshold=3))
        output = BytesIO()
        photo.save(output, "WEBP", quality=90, method=4)
        return output.getvalue(), height


@lru_cache(maxsize=6)
def rendition(name, width):
    remote = Request(SOURCES[name], headers={"User-Agent": "CampusServiceDesk/1.0 (github.com/Aloysiouskyle/campus-service-desk)"})
    with urlopen(remote, timeout=12) as source:
        return render_photo(BytesIO(source.read()), width)


@photos.get("/campus-photos/<name>/<int:width>.webp")
def photo(name, width):
    if name not in SOURCES or width not in WIDTHS:
        abort(404)
    try:
        data, height = rendition(name, width)
    except (URLError, OSError):
        return redirect(SOURCES[name], code=302)
    response = Response(data, mimetype="image/webp", headers={
        "Cache-Control": "public, max-age=86400, s-maxage=2592000",
        "X-Image-Dimensions": f"{width}x{height}",
    })
    response.add_etag()
    return response.make_conditional(request)
