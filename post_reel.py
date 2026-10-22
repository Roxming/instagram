#!/usr/bin/env python3
"""Publica un reel al día a partir de las 10:00 (hora de Madrid).
- En la caption, {dia} se sustituye por un contador que sube de 1 en 1 con cada publicación.
- Si en posts.json queda un solo post, se vuelve a publicar cada día (con el contador actualizado)."""
import json, os, sys, time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import requests

BASE = Path(__file__).resolve().parent
QUEUE, DONE = BASE / "posts.json", BASE / "posts_publicados.json"
API = os.environ.get("IG_API_BASE") or "https://graph.instagram.com/v24.0"
USER_ID, TOKEN = os.environ.get("IG_USER_ID"), os.environ.get("IG_ACCESS_TOKEN")
MANUAL = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
now = datetime.now(ZoneInfo("Europe/Madrid"))

def load(p, d): return json.loads(p.read_text(encoding="utf-8")) if p.exists() else d
def save(p, d): p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

def api(method, endpoint, **params):
    params["access_token"] = TOKEN
    r = requests.request(method, f"{API}/{endpoint}", params=params, timeout=120)
    data = r.json()
    if r.status_code != 200 or "error" in data:
        raise RuntimeError(f"Error de la API: {data}")
    return data

def video_url(name):
    # URL pública del video en GitHub Pages: https://usuario.github.io/repo/video.mp4
    owner, repo = os.environ["GITHUB_REPOSITORY"].split("/")
    return f"https://{owner.lower()}.github.io/{repo}/{name}"

def main():
    if not USER_ID or not TOKEN:
        sys.exit("Faltan los secretos IG_USER_ID o IG_ACCESS_TOKEN")
    done = load(DONE, [])
    if not MANUAL:
        if now.hour < 10:
            print("Todavía no son las 10:00 en Madrid, no hago nada"); return
        if any(p.get("publicado", "").startswith(now.date().isoformat()) for p in done):
            print("Hoy ya se publicó un reel, no hago nada"); return
    queue = load(QUEUE, [])
    if not queue:
        print("La cola está vacía"); return

    post = queue[0]
    dia = len(done) + 1
    caption = post.get("caption", "").replace("{dia}", str(dia))

    cid = None
    video = BASE / post["video"] if post.get("video") else None

    # 1) Intento de subida directa del archivo (no depende de enlaces públicos)
    if video and not post.get("video_url"):
        size = video.stat().st_size
        print(f"Subiendo {video.name} ({size / 1e6:.1f} MB) directamente a Instagram")
        r = requests.post(f"{API}/{USER_ID}/media", timeout=120,
                          headers={"Authorization": f"Bearer {TOKEN}"},
                          json={"media_type": "REELS", "upload_type": "resumable",
                                "caption": caption, "share_to_feed": True})
        data = r.json()
        if r.status_code == 200 and "id" in data:
            cid = data["id"]
            upload_uri = data.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{API.rsplit('/', 1)[-1]}/{cid}"
            with open(video, "rb") as f:
                up = requests.post(upload_uri, data=f, timeout=600, headers={
                    "Authorization": f"OAuth {TOKEN}", "offset": "0", "file_size": str(size)})
            print(f"Respuesta de la subida: {up.status_code} {up.text[:300]}")
            if up.status_code != 200:
                cid = None
        else:
            print(f"La subida directa no está disponible: {data}")

    # 2) Plan B: que Instagram descargue el video desde GitHub Pages
    if cid is None:
        url = post.get("video_url") or video_url(post["video"])
        print(f"Publicando desde URL {url}")
        cid = api("POST", f"{USER_ID}/media", media_type="REELS", video_url=url,
                  caption=caption, share_to_feed="true")["id"]

    for _ in range(60):
        status = api("GET", cid, fields="status_code,status")
        if status.get("status_code") == "FINISHED": break
        if status.get("status_code") in ("ERROR", "EXPIRED"):
            print(f"Detalle completo: {api('GET', cid, fields='status_code,status,id')}")
            sys.exit(f"Instagram no pudo procesar el video: {status}")
        time.sleep(10)
    else:
        sys.exit("Tiempo de espera agotado procesando el video")
    media_id = api("POST", f"{USER_ID}/media_publish", creation_id=cid)["id"]

    done.append({**post, "caption": caption, "dia": dia, "media_id": media_id,
                 "publicado": now.isoformat()})
    save(DONE, done)
    if len(queue) > 1:
        save(QUEUE, queue[1:])  # el último post se queda para repetirse
    print(f"✅ Reel del día {dia} publicado (id {media_id})")

if __name__ == "__main__":
    main()
