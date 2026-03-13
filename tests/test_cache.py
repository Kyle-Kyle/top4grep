import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from top4grep.bundle import create_cache_bundle, install_cache_bundle
from top4grep.cache import cached_get_json, cached_get_text


class CacheTests(unittest.TestCase):
    def test_cached_get_json_negative_caches_404(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "missing.json"
            response = Mock(status_code=404)

            with patch("top4grep.cache.HTTP.get", return_value=response) as mock_get:
                self.assertIsNone(cached_get_json("https://example.com/missing.json", cache_path))
                self.assertIsNone(cached_get_json("https://example.com/missing.json", cache_path))

            mock_get.assert_called_once()

    def test_cached_get_text_negative_caches_404(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "missing.html"
            response = Mock(status_code=404)

            with patch("top4grep.cache.HTTP.get", return_value=response) as mock_get:
                self.assertIsNone(cached_get_text("https://example.com/missing.html", cache_path))
                self.assertIsNone(cached_get_text("https://example.com/missing.html", cache_path))

            mock_get.assert_called_once()

    def test_create_cache_bundle_includes_db_and_raw_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "data"
            raw_dir = data_dir / "raw" / "openalex"
            raw_dir.mkdir(parents=True)
            (data_dir / "papers.db").write_text("db", encoding="utf-8")
            (raw_dir / "paper.json").write_text("{}", encoding="utf-8")
            bundle_path = Path(tmpdir) / "bundle.zip"

            result = create_cache_bundle(bundle_path, data_dir=data_dir)

            self.assertEqual(result["file_count"], 2)
            with zipfile.ZipFile(bundle_path, "r") as bundle:
                names = set(bundle.namelist())

            self.assertIn("manifest.json", names)
            self.assertIn("papers.db", names)
            self.assertIn("raw/openalex/paper.json", names)

    def test_install_cache_bundle_restores_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "source"
            source_raw = source_dir / "raw" / "publisher_html"
            source_raw.mkdir(parents=True)
            (source_dir / "papers.db").write_text("db", encoding="utf-8")
            (source_raw / "page.html").write_text("<html></html>", encoding="utf-8")
            bundle_path = Path(tmpdir) / "bundle.zip"
            create_cache_bundle(bundle_path, data_dir=source_dir)

            install_dir = Path(tmpdir) / "install"
            result = install_cache_bundle(bundle_path, data_dir=install_dir)

            self.assertEqual(result["extracted_files"], 2)
            self.assertEqual((install_dir / "papers.db").read_text(encoding="utf-8"), "db")
            self.assertEqual(
                (install_dir / "raw" / "publisher_html" / "page.html").read_text(encoding="utf-8"),
                "<html></html>",
            )

    def test_install_cache_bundle_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_path = Path(tmpdir) / "bundle.zip"
            with zipfile.ZipFile(bundle_path, "w") as bundle:
                bundle.writestr("../escape.txt", "bad")

            with self.assertRaises(ValueError):
                install_cache_bundle(bundle_path, data_dir=Path(tmpdir) / "install")


if __name__ == "__main__":
    unittest.main()
