from __future__ import annotations
import re
import unicodedata
from unidecode import unidecode
from rapidfuzz import fuzz

STRIP_PATTERN = re.compile(r'\s*[\(\[（【][^\)\]）】]*[\)\]）】]')
FEAT_PATTERN = re.compile(r'\s*(feat\.?|ft\.?|featuring)\s+.+', re.IGNORECASE)
PUNCT_PATTERN = re.compile(r'[^\w\s]')
SPACE_PATTERN = re.compile(r'\s+')

MARKETS = ["HK", "TW", "US"]

AUTO_ACCEPT = 85
REVIEW_MIN = 60


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.lower()
    text = STRIP_PATTERN.sub("", text)
    text = FEAT_PATTERN.sub("", text)
    text = PUNCT_PATTERN.sub(" ", text)
    text = SPACE_PATTERN.sub(" ", text).strip()
    return text


def score_candidate(ne_track: dict, sp_track: dict) -> float:
    ne_title = normalize(ne_track["name"])
    sp_title = normalize(sp_track["name"])
    ne_artist = normalize(ne_track["artists"][0]) if ne_track["artists"] else ""
    sp_artists = [normalize(a["name"]) for a in sp_track.get("artists", [])]

    title_score = fuzz.token_sort_ratio(ne_title, sp_title)
    artist_score = max((fuzz.token_sort_ratio(ne_artist, a) for a in sp_artists), default=0)

    duration_penalty = 0
    sp_duration = sp_track.get("duration_ms", 0)
    if sp_duration and abs(ne_track["duration_ms"] - sp_duration) > 10000:
        duration_penalty = 15

    return title_score * 0.6 + artist_score * 0.4 - duration_penalty


def search_strategies(track: dict):
    name = track["name"]
    artist = track["artists"][0] if track["artists"] else ""
    name_ascii = unidecode(name)
    artist_ascii = unidecode(artist)

    return [
        # (query, market)
        (f"track:{name} artist:{artist}", "HK"),
        (f"{name} {artist}", "HK"),
        (f"{name} {artist}", "TW"),
        (f"{name_ascii} {artist_ascii}", "US"),
        (f"track:{name}", "HK"),
        (f"{name_ascii}", "US"),
    ]


def find_best_match(sp, track: dict) -> dict:
    import time
    best_score = 0
    best_sp_track = None

    for query, market in search_strategies(track):
        # 已经高置信度，不需要继续搜索
        if best_score >= AUTO_ACCEPT:
            break
        try:
            results = sp.search(q=query, type="track", limit=5, market=market)
            items = results.get("tracks", {}).get("items", [])
            time.sleep(0.5)
        except Exception:
            time.sleep(2)
            continue

        for sp_track in items:
            score = score_candidate(track, sp_track)
            if score > best_score:
                best_score = score
                best_sp_track = sp_track

        if best_score >= AUTO_ACCEPT:
            break

    return {
        "netease_id": track["id"],
        "netease_name": track["name"],
        "netease_artist": track["artists"][0] if track["artists"] else "",
        "spotify_uri": best_sp_track["uri"] if best_sp_track else None,
        "spotify_name": best_sp_track["name"] if best_sp_track else None,
        "spotify_artist": best_sp_track["artists"][0]["name"] if best_sp_track else None,
        "score": round(best_score, 1),
    }
