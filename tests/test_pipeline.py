"""Exercise the local paths used to make the movie without a VoiSona service."""

import io
import json
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

import make_narration
import render


ROOT = Path(__file__).resolve().parents[1]


class MediaPipelineTest(unittest.TestCase):
    def test_preview_frames(self):
        samples = (0, render.TOTAL / 2, render.TOTAL - 2)
        args = [str(round(sample, 3)) for sample in samples]
        outputs = [ROOT / "out" / "previews" / f"preview_{arg}.png" for arg in args]
        for output in outputs:
            output.unlink(missing_ok=True)

        subprocess.run([sys.executable, "render.py", "--preview", *args], cwd=ROOT, check=True)

        for output in outputs:
            with self.subTest(frame=output.name), Image.open(output) as frame:
                self.assertEqual(frame.size, (render.W, render.H))
                self.assertEqual(frame.mode, "RGB")
                self.assertTrue(any(low < high for low, high in frame.getextrema()))

    def test_soundtrack(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "soundtrack.wav"
            subprocess.run([sys.executable, "make_music.py", str(output)], cwd=ROOT, check=True)

            with wave.open(str(output)) as audio:
                self.assertEqual(audio.getnchannels(), 2)
                self.assertEqual(audio.getframerate(), 48_000)
                self.assertAlmostEqual(audio.getnframes() / audio.getframerate(), render.TOTAL, delta=0.01)
                sample = np.frombuffer(audio.readframes(48_000), dtype="<i2")
                self.assertGreater(np.max(np.abs(sample.astype(np.int32))), 0)

    def test_narration_manifest_and_cache(self):
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(48_000)
            audio.writeframes(b"\0\0" * 9_600)
        wav = buffer.getvalue()

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(render, "NARRATION_DIR", directory), patch.object(
                sys, "argv", ["make_narration.py"]
            ), patch.object(make_narration.voisona, "synthesize_wav", return_value=wav) as synthesize:
                make_narration.main()
                manifest = json.loads((Path(directory) / "manifest.json").read_text())
                self.assertEqual(set(manifest), set(render.narration_texts()))
                self.assertEqual(synthesize.call_count, len(manifest))
                self.assertTrue(all(item["duration"] == 0.2 for item in manifest.values()))

                make_narration.main()
                self.assertEqual(synthesize.call_count, len(manifest))


if __name__ == "__main__":
    unittest.main()
