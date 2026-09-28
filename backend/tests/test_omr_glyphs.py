import numpy as np
import pytest

from app.omr.glyphs import CLASSES, MODEL_PATH, GlyphClassifier, font_files, synth_sample


@pytest.mark.skipif(not MODEL_PATH.exists(), reason="model not trained")
def test_classifier_on_fresh_synthetic_glyphs():
    clf = GlyphClassifier.load()
    rng = np.random.default_rng(123)
    fonts = font_files()
    hits = total = 0
    for label in CLASSES[:10]:
        for _ in range(20):
            r = synth_sample(label, rng, fonts)
            if r is None:
                continue
            total += 1
            hits += clf.classify([r[0]], r[1])[0][0] == label
    assert hits / total > 0.9
