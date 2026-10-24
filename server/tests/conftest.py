import os

os.environ["MIC_DEVICE"] = "off"  # tests never open the real microphone (bench.main reads it per app)
