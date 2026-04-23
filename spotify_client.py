from __future__ import annotations
import os
import time
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv

load_dotenv()

SCOPE = "user-library-read user-library-modify"
BATCH_SIZE = 20


def get_spotify():
    return spotipy.Spotify(auth_manager=SpotifyOAuth(
        client_id=os.environ["SPOTIPY_CLIENT_ID"],
        client_secret=os.environ["SPOTIPY_CLIENT_SECRET"],
        redirect_uri=os.environ["SPOTIPY_REDIRECT_URI"],
        scope=SCOPE,
    ))


def save_liked_songs(sp, uris: list[str]):
    total = len(uris)
    saved = 0
    for i in range(0, total, BATCH_SIZE):
        batch = uris[i:i + BATCH_SIZE]
        _save_with_retry(sp, batch)
        saved += len(batch)
        print(f"  已保存 {saved}/{total} 首...", end="\r")
        time.sleep(0.5)
    print()


def _save_with_retry(sp, uris: list[str], max_retries=3):
    track_ids = [uri.split(":")[-1] for uri in uris]
    for attempt in range(max_retries):
        try:
            sp.current_user_saved_tracks_add(tracks=track_ids)
            return
        except spotipy.SpotifyException as e:
            if e.http_status == 429:
                retry_after = int(e.headers.get("Retry-After", 5)) + 1
                print(f"\n触发限流，等待 {retry_after} 秒...")
                time.sleep(retry_after)
            else:
                raise
    raise RuntimeError(f"重试 {max_retries} 次后仍然失败")
