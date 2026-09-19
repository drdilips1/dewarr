"""Synthetic postings following the public ABB page contract; no real books/media."""

HASH = "0123456789abcdef" * 2 + "01234567"
ORIGIN = "https://abb.test"
PATH = "/abss/harbor-alex-morgan/"


def post(*, path=PATH, raw_title="Harbor - Alex Morgan", body=None):
    body = (
        body
        if body is not None
        else """
      <p>Written by: Alex Morgan<br>Read by: Casey Reader<br>
      Format: M4B<br>Bitrate: 64 Kbps<br>File Size: 1.5 GBs<br>Unabridged</p>
      <p>A synthetic harbor story.</p>
    """
    )
    return f"""<div class="post"><div class="postTitle"><h2>
      <a href="{path}">{raw_title}</a></h2></div>
      <div class="postInfo">Language: English</div><div class="postContent">{body}</div></div>"""


def search(*, more=False):
    navigation = (
        '<div class="navigation"><a href="/page/2/?s=Harbor">Next</a></div>' if more else ""
    )
    return '<html><div id="content">' + post() + navigation + "</div></html>"


def detail(*, digest=HASH, extra=""):
    body = f"""<p>Written by: Alex Morgan<br>Read by: Casey Reader<br>Format: M4B<br>Unabridged</p>
    <p>Only source claims; inspect actual metadata before downloading.</p>
    <table><tr><td>Info Hash:</td><td>{digest}</td></tr>
    <tr><td>Tracker:</td><td>udp://tracker.example.com:80/announce</td></tr>
    <tr><td>This is a Multifile Torrent</td></tr>
    <tr><td>Harbor/Harbor.m4b 12 Bytes</td></tr>
    <tr><td>Harbor/cover.jpg 2 Bytes</td></tr>
    <tr><td>Combined File Size:</td><td>14 Bytes</td></tr></table>{extra}"""
    return "<html>" + post(body=body) + "</html>"
