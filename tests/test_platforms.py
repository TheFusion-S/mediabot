import pytest

from bot.platforms import analyze, classify, reclassify_as_short

YT = "dQw4w9WgXcQ"


@pytest.mark.parametrize("text,kind,canonical", [
    (f"https://www.youtube.com/watch?v={YT}", "video", f"https://www.youtube.com/watch?v={YT}"),
    (f"https://youtube.com/watch?v={YT}&t=42s&list=PL123", "video", f"https://www.youtube.com/watch?v={YT}"),
    (f"http://m.youtube.com/watch?feature=share&v={YT}", "video", f"https://www.youtube.com/watch?v={YT}"),
    (f"https://music.youtube.com/watch?v={YT}", "video", f"https://www.youtube.com/watch?v={YT}"),
    (f"https://youtu.be/{YT}", "video", f"https://www.youtube.com/watch?v={YT}"),
    (f"https://youtu.be/{YT}?si=abcdef", "video", f"https://www.youtube.com/watch?v={YT}"),
    (f"https://www.youtube.com/live/{YT}", "video", f"https://www.youtube.com/watch?v={YT}"),
    (f"https://www.youtube.com/embed/{YT}", "video", f"https://www.youtube.com/watch?v={YT}"),
    (f"https://www.youtube.com/shorts/{YT}", "short", f"https://www.youtube.com/shorts/{YT}"),
    (f"https://youtube.com/shorts/{YT}/?feature=share", "short", f"https://www.youtube.com/shorts/{YT}"),
    (f"HTTPS://WWW.YOUTUBE.COM/shorts/{YT}", "short", f"https://www.youtube.com/shorts/{YT}"),
    (f"youtu.be/{YT}", "video", f"https://www.youtube.com/watch?v={YT}"),
    (f"youtube.com/shorts/{YT}", "short", f"https://www.youtube.com/shorts/{YT}"),
    (f"Mana bu video: <https://youtu.be/{YT}>, ko'ring!", "video", f"https://www.youtube.com/watch?v={YT}"),
    (f"(https://www.youtube.com/shorts/{YT}).", "short", f"https://www.youtube.com/shorts/{YT}"),
])
def test_youtube_valid(text, kind, canonical):
    link = classify(text)
    assert link is not None
    assert link.platform == "youtube"
    assert link.kind == kind
    assert link.id == YT
    assert link.canonical_url == canonical
    assert link.section == ("shorts" if kind == "short" else "videos")


@pytest.mark.parametrize("text,kind,code,canonical", [
    ("https://www.instagram.com/reel/C1a2B3c4D5e/", "reel", "C1a2B3c4D5e", "https://www.instagram.com/reel/C1a2B3c4D5e/"),
    ("https://instagram.com/reels/C1a2B3c4D5e", "reel", "C1a2B3c4D5e", "https://www.instagram.com/reel/C1a2B3c4D5e/"),
    ("https://www.instagram.com/p/Cxyz_-123/?igsh=MWQ1", "post", "Cxyz_-123", "https://www.instagram.com/p/Cxyz_-123/"),
    ("https://m.instagram.com/tv/CODE12345/", "reel", "CODE12345", "https://www.instagram.com/reel/CODE12345/"),
    ("https://www.instagram.com/some.user_1/reel/C1a2B3c4D5e/", "reel", "C1a2B3c4D5e", "https://www.instagram.com/reel/C1a2B3c4D5e/"),
    ("https://www.instagram.com/some.user/p/C1a2B3c4D5e/", "post", "C1a2B3c4D5e", "https://www.instagram.com/p/C1a2B3c4D5e/"),
    ("instagram.com/reel/C1a2B3c4D5e", "reel", "C1a2B3c4D5e", "https://www.instagram.com/reel/C1a2B3c4D5e/"),
])
def test_instagram_valid(text, kind, code, canonical):
    link = classify(text)
    assert link is not None and link.platform == "instagram"
    assert (link.kind, link.id, link.canonical_url, link.section) == (kind, code, canonical, "instagram")
    assert link.media_key == f"instagram:{code}"


@pytest.mark.parametrize("text", [
    "",
    "salom dunyo",
    "javascript:alert(1)",
    "javascript://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "data:text/html,<script>alert(1)</script>",
    "file:///etc/passwd",
    "ftp://www.youtube.com/watch?v=dQw4w9WgXcQ",
    # userinfo tricks
    "https://youtube.com@evil.com/watch?v=dQw4w9WgXcQ",
    "https://evil.com@youtube.com/watch?v=dQw4w9WgXcQ",
    "https://user:pass@www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://www.youtube.com%40evil.com/watch?v=dQw4w9WgXcQ",
    "https://evil.com\\@www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://evil.com\\.youtube.com/watch?v=dQw4w9WgXcQ",
    # lookalike / subdomain-of-attacker domains
    "https://youtube.com.evil.com/watch?v=dQw4w9WgXcQ",
    "https://evil-youtube.com/watch?v=dQw4w9WgXcQ",
    "https://evilyoutube.com/watch?v=dQw4w9WgXcQ",
    "https://www.youtube.co/watch?v=dQw4w9WgXcQ",
    "https://youtube.com.evil/watch?v=dQw4w9WgXcQ",
    "https://www.youtуbe.com/watch?v=dQw4w9WgXcQ",  # cyrillic у
    "https://xn--yutube-wqf.com/watch?v=dQw4w9WgXcQ",
    "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ",
    "https://instagram.com.evil.io/reel/C1a2B3c4D5e/",
    "https://instagran.com/reel/C1a2B3c4D5e/",
    "https://www.instagram.com./reel/C1a2B3c4D5e/",
    "https://www.youtube.com./watch?v=dQw4w9WgXcQ",
    "https://www.youtu.be/dQw4w9WgXcQ",
    # IPs & ports
    "http://142.250.74.46/watch?v=dQw4w9WgXcQ",
    "http://[2a00:1450::200e]/watch?v=dQw4w9WgXcQ",
    "http://127.0.0.1:8080/watch?v=dQw4w9WgXcQ",
    "https://www.youtube.com:8443/watch?v=dQw4w9WgXcQ",
    "https://www.youtube.com:443/watch?v=dQw4w9WgXcQ",
    "https://www.instagram.com:80/reel/C1a2B3c4D5e/",
    # bad IDs / paths
    "https://www.youtube.com/watch?v=short",
    "https://www.youtube.com/watch?v=dQw4w9WgXcQX",
    "https://www.youtube.com/watch?v=dQw4w9WgXc%00",
    "https://www.youtube.com/watch?v=dQw4w9WgX%2F%2E",
    "https://www.youtube.com/shorts/dQw4w9WgXc!",
    "https://www.youtube.com/shorts/../watch?v=dQw4w9WgXcQ",
    "https://www.youtube.com//shorts/dQw4w9WgXcQ",
    "https://www.youtube.com/@somechannel",
    "https://www.youtube.com/playlist?list=PL1234567890",
    "https://www.youtube.com/watch",
    "https://youtu.be/",
    "https://www.instagram.com/someuser/",
    "https://www.instagram.com/stories/someuser/1234567890/",
    "https://www.instagram.com/reel/abc/",  # too short
    "https://www.instagram.com/reel/C1a2B3c4D5e/extra/",
    "https://www.instagram.com/reel/C1a2B3c4D5e%2F..%2F/",
    "evil.com/youtube.com/watch?v=dQw4w9WgXcQ",
    "https://evil.com/?u=https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://evil.com/https://youtu.be/dQw4w9WgXcQ",
])
def test_rejected(text):
    assert classify(text) is None


def test_first_valid_link_wins_and_junk_is_skipped():
    text = "https://evil.com/x https://www.instagram.com/reel/C1a2B3c4D5e/ https://youtu.be/dQw4w9WgXcQ"
    link = classify(text)
    assert link.platform == "instagram"


def test_newline_does_not_smuggle_hosts():
    link = classify("https://www.youtube.com/watch?v=dQw4w9WgXcQ\nhttps://evil.com")
    assert link.canonical_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_canonical_never_contains_user_input_extras():
    link = classify("https://www.youtube.com/watch?v=dQw4w9WgXcQ&x=$(rm%20-rf)&exec=1")
    assert link.canonical_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_analyze_error_codes():
    assert analyze("https://www.youtube.com/@channel") == (None, "unsupported")
    assert analyze("https://www.instagram.com/stories/x/1/") == (None, "unsupported")
    assert analyze("https://evil.com/watch?v=dQw4w9WgXcQ") == (None, "invalid_url")
    assert analyze("hello") == (None, "invalid_url")
    assert analyze(None) == (None, "invalid_url")


def test_overlong_rejected():
    assert classify("https://www.youtube.com/watch?v=dQw4w9WgXcQ&" + "a" * 5000) is None


def test_reclassify_vertical_watch_as_short():
    link = classify("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    s = reclassify_as_short(link, 1080, 1920, 59)
    assert (s.kind, s.section) == ("short", "shorts")
    assert reclassify_as_short(link, 1920, 1080, 59) == link
    assert reclassify_as_short(link, 1080, 1920, 600) == link


def test_percent_encoded_query_is_decoded_then_validated():
    link = classify("https://www.youtube.com/watch?v=dQw4w9WgXc%51")
    assert link.canonical_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
