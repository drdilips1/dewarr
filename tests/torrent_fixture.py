"""Invented torrent metadata; no tracker or peer is contacted."""

import hashlib

import libtorrent as lt


def torrent_bytes(**info_changes):
    info = {
        b"name": b"Harbor Stories",
        b"private": 1,
        b"piece length": 16384,
        b"files": [
            {b"length": 12, b"path": [b"01 - Harbor.m4b"]},
            {b"length": 12, b"path": [b"02 - Roads.m4b"]},
        ],
        b"pieces": hashlib.sha1(b"original fixture content").digest(),
    }
    info.update({key.encode(): value for key, value in info_changes.items()})
    return lt.bencode(
        {b"announce": b"https://tracker.test/private-fixture-passkey/announce", b"info": info}
    )
