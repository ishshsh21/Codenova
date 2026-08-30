"""
FR-12 Task Deduplication.
MVP substitute for the pgvector/embeddings-based semantic dedup described in
TRD 4.2: uses RapidFuzz token-set similarity on the task title + thread
subject. Same threadId is always treated as a duplicate/continuation
(FR-05); this adds cross-thread matching (e.g. "Please review proposal" /
"Following up on proposal review").

Swap-in point: replace `find_duplicate` with a pgvector cosine-similarity
query over stored embeddings for production use, per Section 4.2.
"""
from rapidfuzz import fuzz

SIMILARITY_THRESHOLD = 78  # 0-100 scale


def find_duplicate(new_title: str, existing_tasks: list[dict]) -> dict | None:
    """existing_tasks: list of {'id', 'title'} for the same user, still OPEN."""
    best_match, best_score = None, 0
    for task in existing_tasks:
        score = fuzz.token_set_ratio(new_title, task["title"])
        if score > best_score:
            best_match, best_score = task, score
    if best_match and best_score >= SIMILARITY_THRESHOLD:
        return best_match
    return None
