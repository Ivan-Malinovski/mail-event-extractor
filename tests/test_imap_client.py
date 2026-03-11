"""Tests for IMAP client HTML text extraction."""


class TestIMAPTextExtraction:
    def test_strip_html_basic(self):
        from mail_events_to_caldav.imap_client import IMAPClient

        client = IMAPClient.__new__(IMAPClient)
        html = "<p>Hello <b>World</b></p>"
        result = client._strip_html(html)
        assert "Hello" in result
        assert "World" in result
        assert "<" not in result

    def test_strip_html_with_scripts(self):
        from mail_events_to_caldav.imap_client import IMAPClient

        client = IMAPClient.__new__(IMAPClient)
        html = "<script>alert('xss')</script><p>Content</p>"
        result = client._strip_html(html)
        assert "alert" not in result
        assert "Content" in result

    def test_strip_html_with_styles(self):
        from mail_events_to_caldav.imap_client import IMAPClient

        client = IMAPClient.__new__(IMAPClient)
        html = "<style>.foo { color: red; }</style><p>Text</p>"
        result = client._strip_html(html)
        assert ".foo" not in result
        assert "color" not in result
        assert "Text" in result

    def test_strip_html_with_entities(self):
        from mail_events_to_caldav.imap_client import IMAPClient

        client = IMAPClient.__new__(IMAPClient)
        html = "<p>&nbsp;&copy;2026</p>"
        result = client._strip_html(html)
        assert "&nbsp;" not in result
        assert "2026" in result
