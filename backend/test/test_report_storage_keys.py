import unittest

from app.reports.storage_keys import (
    layout_key,
    markdown_key,
    page_image_key,
    page_thumbnail_key,
    source_file_key,
)


class ReportStorageKeyTests(unittest.TestCase):
    def test_source_file_key_uses_short_owner_and_report_path(self) -> None:
        self.assertEqual(
            source_file_key("default", "report-1", "file-1", "pdf"),
            "u/default/r/report-1/source/file-1.pdf",
        )

    def test_page_keys_are_zero_padded(self) -> None:
        self.assertEqual(page_image_key("default", "report-1", 1), "u/default/r/report-1/pages/001.png")
        self.assertEqual(page_thumbnail_key("default", "report-1", 12), "u/default/r/report-1/pages/012-thumb.png")
        self.assertEqual(layout_key("default", "report-1", 3), "u/default/r/report-1/layout/003.json")

    def test_markdown_keys_are_fixed_names(self) -> None:
        self.assertEqual(markdown_key("default", "report-1", "original"), "u/default/r/report-1/md/original.md")
        self.assertEqual(markdown_key("default", "report-1", "current"), "u/default/r/report-1/md/current.md")

    def test_invalid_key_parts_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            source_file_key("default", "../report", "file-1", "pdf")
        with self.assertRaises(ValueError):
            markdown_key("default", "report-1", "draft")


if __name__ == "__main__":
    unittest.main()
