import os

os.environ["MIC_DEVICE"] = "off"  # tests never open the real microphone (bench.main reads it per app)
os.environ["SPEAKER_DEVICE"] = "off"  # ... nor the speakers
os.environ["BENCH_FRAME_DIR"] = "off"  # ... nor write camera frames into recordings/
os.environ["BENCH_RECORD_DIR"] = "off"  # ... nor session logs
os.environ["BENCH_WATCH"] = "off"  # ... nor poll connected test screens for frames (tests/test_watch.py drives it)
