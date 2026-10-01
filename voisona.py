"""Minimal client for the local VoiSona Talk REST API.

Credentials come from environment variables, e.g. `uv run --env-file path/to/.env ...`:
  VOISONA_API_USERNAME  registered email address
  VOISONA_API_KEY       API password configured in VoiSona Talk
  VOISONA_API_URL       optional, defaults to http://localhost:32766/api/talk/v1

usage:
  uv run --env-file .env python voisona.py voices               list voice libraries
  uv run --env-file .env python voisona.py voice NAME VERSION   show one voice (incl. style names)
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request


def _config():
    user = os.environ.get("VOISONA_API_USERNAME")
    key = os.environ.get("VOISONA_API_KEY")
    if not user or not key:
        sys.exit("Set VOISONA_API_USERNAME and VOISONA_API_KEY before running this command.")
    base = os.environ.get("VOISONA_API_URL", "http://localhost:32766/api/talk/v1").rstrip("/")
    token = base64.b64encode(f"{user}:{key}".encode()).decode()
    return base, token


def request(path, method="GET", body=None, raw=False):
    base, token = _config()
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{base}{path}", data=data, method=method, headers={
        "Authorization": f"Basic {token}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            payload = res.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {path}: HTTP {e.code}") from None
    if raw:
        return payload
    return json.loads(payload) if payload else None


def synthesize_wav(text, voice_name, voice_version=None, language="ja_JP", global_parameters=None,
                   timeout=300):
    """Synthesize `text` and return the WAV bytes (synthesized in memory, nothing is played)."""
    body = {"text": text, "language": language, "voice_name": voice_name, "destination": "memory"}
    if voice_version:
        body["voice_version"] = voice_version
    if global_parameters:
        body["global_parameters"] = global_parameters
    created = request("/speech-syntheses", "POST", body)
    path = f"/speech-syntheses/{created['uuid']}"
    try:
        deadline = time.time() + timeout
        while True:
            state = request(path)["state"]
            if state == "succeeded":
                break
            if state == "failed":
                raise RuntimeError(f"speech synthesis failed: {text[:30]}")
            if time.time() > deadline:
                raise RuntimeError("speech synthesis timed out")
            time.sleep(0.25)
        return request(f"{path}/wav", raw=True)
    finally:
        try:
            request(path, "DELETE")
        except RuntimeError:
            print(f"warning: could not remove {path}", file=sys.stderr)


def main():
    args = sys.argv[1:]
    if args[:1] == ["voices"]:
        print(json.dumps(request("/voices"), ensure_ascii=False, indent=2))
    elif args[:1] == ["voice"] and len(args) == 3:
        print(json.dumps(request(f"/voices/{args[1]}/{args[2]}"), ensure_ascii=False, indent=2))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
