"""Synthesize the narration lines defined in render.py with VoiSona Talk.

Writes one WAV per cue to out/narration/<cue>.wav and records text and duration in
out/narration/manifest.json. render.py reads the durations to make room for each line on the
timeline, and make_music.py mixes the WAVs into the soundtrack.
Lines whose text and voice settings are unchanged are skipped unless --overwrite is given.

usage: uv run --env-file path/to/.env python make_narration.py [--overwrite]
"""
import hashlib
import io
import json
import os
import sys
import wave

import render as R
import voisona


def _settings_key(text):
    payload = json.dumps([text, R.NARRATION_VOICE], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def _duration(wav_bytes):
    with wave.open(io.BytesIO(wav_bytes)) as w:
        return w.getnframes() / w.getframerate()


def main():
    overwrite = "--overwrite" in sys.argv[1:]
    os.makedirs(R.NARRATION_DIR, exist_ok=True)
    manifest_path = os.path.join(R.NARRATION_DIR, "manifest.json")
    manifest = {}
    if os.path.exists(manifest_path):
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)

    texts = R.narration_texts()
    for cid, text in texts.items():
        key = _settings_key(text)
        wav_path = os.path.join(R.NARRATION_DIR, f"{cid}.wav")
        if not overwrite and manifest.get(cid, {}).get("key") == key and os.path.exists(wav_path):
            print(f"{cid}: unchanged")
            continue
        wav = voisona.synthesize_wav(text, **R.NARRATION_VOICE)
        with open(wav_path, "wb") as f:
            f.write(wav)
        manifest[cid] = {"text": text, "key": key, "duration": round(_duration(wav), 3)}
        print(f"{cid}: {manifest[cid]['duration']:.2f}s")

    # drop cues that no longer exist in render.py
    manifest = {cid: m for cid, m in manifest.items() if cid in texts}
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    total = sum(m["duration"] for m in manifest.values())
    print(f"{len(manifest)} lines, {total:.1f}s of narration")


if __name__ == "__main__":
    main()
