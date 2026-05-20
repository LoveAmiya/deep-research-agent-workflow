import unittest

from search.content_extraction import (
    clean_text,
    extract_main_text,
    extract_title,
    strip_html_tags,
    truncate_text,
)


class TestContentExtraction(unittest.TestCase):
    def test_extract_title_reads_html_title(self) -> None:
        title = extract_title("<html><head><title>Deep Research &amp; AI</title></head></html>")

        self.assertEqual(title, "Deep Research & AI")

    def test_extract_main_text_removes_script_and_style(self) -> None:
        html = """
        <html>
          <head><style>.hidden { display: none; }</style></head>
          <body>
            <script>console.log("noise")</script>
            <main><h1>Article</h1><p>Main evidence text.</p></main>
          </body>
        </html>
        """

        text, metadata = extract_main_text(html)

        self.assertIn("Article Main evidence text.", text)
        self.assertNotIn("console.log", text)
        self.assertGreaterEqual(metadata["removed_noise_blocks"], 2)
        self.assertEqual(metadata["extraction_method"], "main")

    def test_clean_text_merges_whitespace(self) -> None:
        self.assertEqual(clean_text("A\n\n  B\t&nbsp; C"), "A B C")

    def test_truncate_text_limits_length(self) -> None:
        text, truncated = truncate_text("abcdef", max_chars=3)

        self.assertEqual(text, "abc")
        self.assertTrue(truncated)

    def test_strip_html_tags_unescapes_entities(self) -> None:
        text = strip_html_tags("<p>Open-source &amp; enterprise&nbsp;AI</p>")

        self.assertEqual(text, "Open-source & enterprise AI")


if __name__ == "__main__":
    unittest.main()
