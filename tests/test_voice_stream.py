import unittest

import numpy as np

from app.voice.funasr_stream import CHUNK_SAMPLES, FINAL_SILENCE_SAMPLES, FunASRStream


class FakeStreamingModel:
    def __init__(self):
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return [{"text": " final" if kwargs["is_final"] else "partial"}]


class FunASRStreamTests(unittest.TestCase):
    def test_decodes_full_chunk_without_waiting_for_next_chunk(self):
        model = FakeStreamingModel()
        stream = FunASRStream(model=model)
        first_chunk = np.zeros(CHUNK_SAMPLES, dtype="<i2").tobytes()

        self.assertEqual(stream.push(first_chunk), "partial")
        self.assertEqual(stream.finish(), "partial final")
        self.assertFalse(model.calls[0]["is_final"])
        self.assertTrue(model.calls[1]["is_final"])
        self.assertEqual(model.calls[1]["input"].size, CHUNK_SAMPLES)
        self.assertTrue(np.all(model.calls[1]["input"][-FINAL_SILENCE_SAMPLES:] == 0))

    def test_rejects_partial_pcm_sample(self):
        stream = FunASRStream(model=FakeStreamingModel())
        with self.assertRaises(ValueError):
            stream.push(b"\x00")


if __name__ == "__main__":
    unittest.main()
