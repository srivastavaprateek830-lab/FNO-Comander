"""
FNO COMMANDER - V2B Ranking Engine
"""

from typing import Iterable


def rank_candidates(results: Iterable):
    """
    Sort conviction results by:
    1. Veto-free status
    2. Conviction score
    3. Directional quality
    """

    def sort_key(result):
        veto_penalty = 1 if getattr(result, "vetoes", []) else 0

        return (
            veto_penalty,
            -float(getattr(result, "score", 0)),
        )

    return sorted(results, key=sort_key)


def priority_from_score(score, vetoes=None):
    score = float(score or 0)
    vetoes = vetoes or []

    if vetoes:
        return "REJECT"

    if score >= 85:
        return "VERY HIGH"

    if score >= 75:
        return "HIGH"

    if score >= 60:
        return "NORMAL"

    return "LOW"
