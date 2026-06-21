"""
Tuning constants for the strategy HMM pipeline.

Every value here is copied verbatim from Hyeongjo's training Colab. They have to
stay in lockstep with the saved model (model.pkl) for live inference to match
how it was trained, so treat them as fixed rather than knobs to tweak.
"""
import os

MODEL_PATH = os.path.join(os.path.dirname(__file__), "model.pkl")

# The cutoff between a "step by step" edit and a full "rewrite" when bucketing
# change_score. It's the 95th percentile of the non-zero change scores in
# Hyeongjo's training data.
REWRITE_THRESHOLD = 0.221151

# APTED edit costs, the BlocklyConfig defaults used at training time.
DELETION_COST = 1.0
INSERTION_COST = 1.0
FIELD_CHANGE_COST = 0.3
TYPE_CHANGE_COST = 1.0
EDGE_CHANGE_COST = 1.0

# Smoothing term in the similarity normalization:
#   sim = 1 - dist / (max_tree_size + SIMILARITY_SMOOTHING)
# It damps the score for very small trees, where a one-block change would
# otherwise look like a near-total rewrite.
SIMILARITY_SMOOTHING = 10

# Human-readable names for the three observation buckets fed into the HMM.
OBS_LABELS = {
    0: "relying_on_fortune",   # change_score == 0 (the code didn't change at all)
    1: "step_by_step",         # 0 < change_score < REWRITE_THRESHOLD (incremental)
    2: "rewrite",              # change_score >= REWRITE_THRESHOLD (large overhaul)
}
