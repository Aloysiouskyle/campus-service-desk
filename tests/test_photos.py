from io import BytesIO
import unittest
from unittest.mock import patch

from PIL import Image
from app import app
from campus_photos import rendition


class CampusPhotosTests(unittest.TestCase):
    def test_public_4k_rendition_has_correct_pixels_cache_and_type(self):
        source = BytesIO()
        Image.new("RGB", (712, 536), "green").save(source, "JPEG")
        source.seek(0)
        rendition.cache_clear()
        self.addCleanup(rendition.cache_clear)
        with patch("campus_photos.urlopen", return_value=source), app.test_client() as client:
            result = client.get("/campus-photos/hamu-mukasa/3840.webp")
            self.assertEqual(result.mimetype, "image/webp")
            self.assertEqual(Image.open(BytesIO(result.data)).size, (3840, 2891))
            cached = client.get("/campus-photos/hamu-mukasa/3840.webp",
                                headers={"If-None-Match": result.headers["ETag"]})
            self.assertEqual(cached.status_code, 304)
            self.assertEqual(client.get("/campus-photos/unknown/3840.webp").status_code, 404)
