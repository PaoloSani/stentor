"""Numbers fixed by the Sidon model. Every stage of the pipeline agrees on these."""

IN_SR = 16_000  # model input sample rate
OUT_SR = 48_000  # model output sample rate
UPSAMPLE = OUT_SR // IN_SR  # 3 output samples per input sample
FEATURE_RATE = 50  # feature frames per second (100 Hz fbank, 2 frames stacked)
HOP = OUT_SR // FEATURE_RATE  # 960 output samples per feature frame
FEATURE_DIM = 160  # 80 mel bins x 2 stacked frames
HIDDEN_DIM = 1024  # w2v-BERT 2.0 hidden size (vocoder input channels)

# Zeros added on each side of every model call. Without them the vocoder produces a burst on
# the last few milliseconds (the reference code padded 1.5 s at the end for the same reason).
EDGE_PAD_SAMPLES = IN_SR // 4  # 0.25 s
