"""Literature minimum-distance targets for known BB code stems (benchmark defaults)."""

from __future__ import annotations

from typing import Dict

# Bivariate bicycle codes (Bravyi et al. / IBM); values are literature d.
LITERATURE_BB_DISTANCES: Dict[str, int] = {
    "BB_72_12_6": 6,
    "BB_90_8_10": 10,
    "BB_108_8_10": 10,
    "BB_144_12_12": 12,
    "BB_216_8_10": 10,
    "BB_144_14_14": 14,
    "BB_288_12_unknown": 18,
    "BB_360_12_unknown": 24,
    "BB_576_8_24": 24,
    "BB_648_4_32": 32,
    "BB_756_16_34": 34,
    "BB_864_4_40": 40,
    "BB_1080_4_54": 54,
    "BB_1152_4_36": 36,
    "BB_1296_4_48": 48,
    "BB_1728_4_64": 64,
    "BB_2016_8_54": 54,
    "BB_2160_8_64": 64,
    "BB_2520_8_54": 54,
    "BB_2592_8_36": 36,
    "BB_3024_4_78": 78,
}
