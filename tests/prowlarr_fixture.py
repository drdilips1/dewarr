from copy import deepcopy

INDEXER = {
    "id": 7,
    "name": "Book tracker",
    "definitionName": "booktracker",
    "protocol": "torrent",
    "enable": True,
    "supportsSearch": True,
    "supportsPagination": True,
    "capabilities": {"categories": [{"id": 3000, "subCategories": [{"id": 3030}]}, {"id": 7020}]},
    "fields": [{"name": "passkey", "value": "secret-indexer-passkey"}],
}
RELEASE = {
    "guid": "https://tracker.test/item/1?passkey=secret-guid",
    "indexerId": 7,
    "indexer": "Book tracker",
    "title": "A Book - Reader A [M4B]",
    "protocol": "torrent",
    "categories": [{"id": 3030}],
    "size": 10240,
    "seeders": 0,
    "downloadUrl": "https://prowlarr.test/base/7/download?apikey=secret-api&link=secret_proxy_link&file=title",
    "infoUrl": "https://tracker.test/private?passkey=hidden",
}


def indexer(**changes):
    return {**deepcopy(INDEXER), **changes}


def release(**changes):
    return {**deepcopy(RELEASE), **changes}
