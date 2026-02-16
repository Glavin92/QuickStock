# tools/train_asr_mappings.py
import json
import os
from collections import defaultdict, Counter

ASR_LOG = os.path.join(os.path.dirname(__file__), "..", "asr_corrections_log.jsonl")
CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", "asr_corrections_cache.json")
REVIEW_PATH = os.path.join(os.path.dirname(__file__), "..", "asr_corrections_review.json")

PROMOTE_THRESHOLD = 0.9   # auto-add to cache
REVIEW_LOW = 0.5
REVIEW_HIGH = 0.9

def load_log(path):
    if not os.path.exists(path):
        return []
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except Exception:
                continue
    return items

def load_cache():
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_cache(cache):
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

def save_review(review_list):
    with open(REVIEW_PATH, "w", encoding="utf-8") as f:
        json.dump(review_list, f, ensure_ascii=False, indent=2)

def train():
    log = load_log(ASR_LOG)
    counts = defaultdict(Counter)
    weights = {"manual": 5.0, "auto": 1.0, "llm": 1.5}  # example weights
    for rec in log:
        frag = rec.get("fragment","").lower().strip()
        chosen = rec.get("chosen")
        source = rec.get("source","auto")
        w = rec.get("confidence", 1.0) * weights.get(source, 1.0)
        if not frag or not chosen:
            continue
        counts[frag][chosen] += w

    cache = load_cache()
    review = []

    for frag, counter in counts.items():
        total = sum(counter.values())
        best, best_count = counter.most_common(1)[0]
        prob = best_count / total
        if prob >= PROMOTE_THRESHOLD:
            cache[frag] = best
        elif REVIEW_LOW <= prob < REVIEW_HIGH:
            review.append({"fragment": frag, "top": best, "prob": prob, "counts": dict(counter)})
        # else ignore low-confidence mappings

    save_cache(cache)
    save_review(review)
    print(f"Promoted {len([1 for frag in counts if frag in cache])} mappings. {len(review)} items for review.")

if __name__ == "__main__":
    train()