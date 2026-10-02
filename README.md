# c-movie

Create a narrated Claude and ChatGPT timeline video. The renderer uses the macOS
Japanese system font; full video encoding also needs `ffmpeg` on `PATH`.

```sh
uv sync --locked
uv run --locked python render.py --preview 0 80 145
```

To create the complete movie, first synthesize narration through a running
VoiSona Talk service with `VOISONA_API_USERNAME` and `VOISONA_API_KEY` in an
environment file. Then generate the soundtrack and render the video:

```sh
uv run --locked --env-file path/to/.env python make_narration.py
uv run --locked python make_music.py
uv run --locked python render.py
```

Run the local pipeline checks with:

```sh
uv run --locked python -m unittest discover -s tests -v
```
