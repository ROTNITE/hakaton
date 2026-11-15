import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json
from pathlib import Path
import tempfile
import unittest
import wave
from dataclasses import replace
import shutil
import subprocess

from PIL import Image

from compose_film import load_spec, synthesize_score, title_panel, persistent_panel, title_fade_filter


class FilmEditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.frames = self.root/"frames"
        self.frames.mkdir()
        for index in range(6):
            Image.new("RGB", (320, 180), (20+index, 50, 80)).save(self.frames/f"frame-{index:06d}.png")
        self.spec = {"fps":30, "shots":[{"id":"city", "frames":"frames", "start":0, "end":.2,
                                       "title":"Город ждёт помощи", "subtitle":"Поиск и спасение", "kicker":"01 / ГОРОД"}]}

    def write(self):
        path = self.root/"edit.json"
        path.write_text(json.dumps(self.spec, ensure_ascii=False), encoding="utf-8")
        return path

    def test_requested_frame_window_and_cyrillic_panels(self):
        self.spec["shots"][0]["start"] = 1/30
        _, shots = load_spec(self.write())
        self.assertEqual((shots[0].first, shots[0].count), (1, 5))
        for renderer in (title_panel, persistent_panel):
            path = self.root/(renderer.__name__+".png")
            renderer(shots[0], path)
            with Image.open(path) as image:
                self.assertEqual(image.size, (1920, 1080))
                self.assertEqual(image.mode, "RGBA")
                self.assertIsNotNone(image.getbbox())

    def test_rejects_missing_or_nonzero_first_frame(self):
        (self.frames/"frame-000000.png").unlink()
        with self.assertRaisesRegex(ValueError, "contiguous"):
            load_spec(self.write())

    def test_rejects_gap(self):
        (self.frames/"frame-000003.png").unlink()
        with self.assertRaisesRegex(ValueError, "contiguous"):
            load_spec(self.write())

    def test_rejects_overshoot_and_empty_interval(self):
        for start, end in ((0, .21), (.1, .1), (.3, .2)):
            with self.subTest(start=start, end=end):
                self.spec["shots"][0].update(start=start, end=end)
                with self.assertRaisesRegex(ValueError, "range"):
                    load_spec(self.write())

    def test_rejects_nonfinite_and_boolean_times(self):
        for value in (float("nan"), float("inf"), True, -1):
            with self.subTest(value=value):
                self.spec["shots"][0]["start"] = value
                with self.assertRaises(ValueError):
                    load_spec(self.write())

    def test_rejects_duplicate_and_unsafe_ids(self):
        self.spec["shots"].append(dict(self.spec["shots"][0]))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            load_spec(self.write())
        self.spec["shots"] = self.spec["shots"][:1]
        self.spec["shots"][0]["id"] = "../escape"
        with self.assertRaisesRegex(ValueError, "id"):
            load_spec(self.write())

    def test_synthesized_sound_has_exact_length_stereo_and_headroom(self):
        path = self.root/"score.wav"
        receipt = synthesize_score(path, 2.125, (.5, 1.5))
        with wave.open(str(path), "rb") as sound:
            self.assertEqual(sound.getnchannels(), 2)
            self.assertEqual(sound.getframerate(), 48000)
            self.assertEqual(sound.getnframes(), 102000)
        self.assertGreater(receipt["peak"], .01)
        self.assertLess(receipt["peak"], .78)
        self.assertEqual(receipt["seconds"], 2.125)

    def test_zero_and_subframe_title_are_valid_and_disabled(self):
        _, shots = load_spec(self.write())
        for seconds in (0, 1e-12, 1/30):
            with self.subTest(seconds=seconds):
                shot = replace(shots[0], title_seconds=seconds)
                self.assertEqual(title_fade_filter(shot), "[graded]null[titled];")

    def test_short_title_still_has_positive_alpha_fades(self):
        _, shots = load_spec(self.write())
        shot = replace(shots[0], count=2, title_seconds=2/30)
        graph = title_fade_filter(shot)
        self.assertIn("alpha=1", graph)
        self.assertNotIn("n=0:", graph)
        self.assertNotIn("s=-", graph)

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg not installed")
    def test_rendered_title_alpha_rises_and_reaches_zero_at_deadline(self):
        _, shots = load_spec(self.write())
        shot = replace(shots[0], count=210, title_seconds=5.5)
        frames = (0, 6, 9, 12, 16, 30, 157, 160, 163, 165, 171)
        chain = title_fade_filter(shot).split(";")[0].replace("[1:v]", "[0:v]").replace("[titlefade]", "")
        filters = chain + ",alphaextract,crop=1:1:0:0,select='" + "+".join(f"eq(n,{n})" for n in frames) + "'[a]"
        result = subprocess.run([shutil.which("ffmpeg"), "-hide_banner", "-v", "error", "-f", "lavfi",
                                 "-i", "color=white:size=2x2:rate=30", "-filter_complex", filters,
                                 "-map", "[a]", "-frames:v", str(len(frames)), "-fps_mode", "passthrough",
                                 "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"], capture_output=True, check=True)
        alpha = list(result.stdout)
        self.assertEqual(len(alpha), len(frames))
        self.assertEqual(alpha[:2], [0, 0])
        self.assertTrue(0 < alpha[2] < alpha[3] < alpha[4] == alpha[5] == alpha[6] == 255, alpha)
        self.assertTrue(alpha[6] > alpha[7] > alpha[8] > alpha[9] == alpha[10] == 0, alpha)


if __name__ == "__main__":
    unittest.main()
