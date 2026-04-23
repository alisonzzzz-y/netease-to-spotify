import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://music.163.com/",
}

def get_session():
    session = requests.Session()
    session.headers.update(HEADERS)
    session.cookies.set("MUSIC_U", os.environ["NETEASE_MUSIC_U"], domain=".music.163.com")
    session.cookies.set("__csrf", os.environ["NETEASE_CSRF"], domain=".music.163.com")
    return session

def get_liked_playlist_id(session, uid):
    resp = session.post(
        "https://music.163.com/api/user/playlist",
        data={"uid": uid, "limit": 1, "offset": 0},
    )
    resp.raise_for_status()
    data = resp.json()
    playlists = data.get("playlist", [])
    if not playlists:
        raise RuntimeError("找不到歌单，请检查 Cookie 是否有效")
    return playlists[0]["id"]

def get_playlist_tracks(session, playlist_id):
    resp = session.post(
        "https://music.163.com/api/v6/playlist/detail",
        data={"id": playlist_id, "n": 5000},
    )
    resp.raise_for_status()
    data = resp.json()

    playlist = data.get("playlist", {})
    all_track_ids = [t["id"] for t in playlist.get("trackIds", [])]
    tracks = playlist.get("tracks", [])

    # API 只返回前300首完整信息，剩余的用 ID 补全
    fetched_ids = {t["id"] for t in tracks}
    missing_ids = [tid for tid in all_track_ids if tid not in fetched_ids]
    if missing_ids:
        print(f"  补全剩余 {len(missing_ids)} 首歌曲信息...")
        tracks += fetch_tracks_by_ids(session, missing_ids)

    # 按原始歌单顺序排序
    id_order = {tid: i for i, tid in enumerate(all_track_ids)}
    tracks.sort(key=lambda t: id_order.get(t["id"], 9999))

    result = []
    for t in tracks:
        artists = [ar["name"] for ar in t.get("ar", [])]
        result.append({
            "id": t["id"],
            "name": t["name"],
            "artists": artists,
            "album": t.get("al", {}).get("name", ""),
            "duration_ms": t.get("dt", 0),
        })
    return result

def fetch_tracks_by_ids(session, ids):
    tracks = []
    for i in range(0, len(ids), 1000):
        batch = ids[i:i+1000]
        c = json.dumps([{"id": bid} for bid in batch])
        resp = session.post(
            "https://music.163.com/api/song/detail",
            data={"c": c, "ids": json.dumps(batch)},
        )
        resp.raise_for_status()
        tracks.extend(resp.json().get("songs", []))
    return tracks

def export_liked_songs():
    uid = os.environ["NETEASE_UID"]
    session = get_session()
    print("正在连接网易云音乐...")
    playlist_id = get_liked_playlist_id(session, uid)
    print(f"找到喜欢的音乐歌单，ID: {playlist_id}")
    tracks = get_playlist_tracks(session, playlist_id)
    print(f"共获取 {len(tracks)} 首歌曲")
    return tracks
