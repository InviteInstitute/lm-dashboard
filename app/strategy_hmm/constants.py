"""
Constants for the strategy HMM pipeline. Values copied verbatim from
Hyeongjo's Colab so live inference matches training exactly.
"""
import os

MODEL_PATH = os.path.join(os.path.dirname(__file__), "model.pkl")

# Threshold for bucketing change_score into the 3 input categories.
# = 95th percentile of non-zero change scores in Hyeongjo's training data.
REWRITE_THRESHOLD = 0.221151

# APTED edit costs (BlocklyConfig defaults used during training).
DELETION_COST = 1.0
INSERTION_COST = 1.0
FIELD_CHANGE_COST = 0.3
TYPE_CHANGE_COST = 1.0
EDGE_CHANGE_COST = 1.0

# Similarity normalization: sim = 1 - dist / (max_tree_size + SMOOTHING)
SIMILARITY_SMOOTHING = 10

# Observed-category labels (input to the HMM).
OBS_LABELS = {
    0: "relying_on_fortune",   # change_score == 0 (identical code)
    1: "step_by_step",         # 0 < change_score < REWRITE_THRESHOLD
    2: "rewrite",              # change_score >= REWRITE_THRESHOLD
}
