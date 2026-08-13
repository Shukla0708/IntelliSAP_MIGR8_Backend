import time

from services.comparison_engine import canonical_key_part, classify_difference

ROWS = 200_000

padded_keys = [f"{i:010d}" for i in range(ROWS)]
plain_keys = [str(i) for i in range(ROWS)]

start = time.perf_counter()
for text in padded_keys:
    canonical_key_part(text)
for text in plain_keys:
    canonical_key_part(text)
print(f"canonical_key_part, {ROWS * 2:,} calls: {time.perf_counter() - start:.2f}s")

# Worst realistic case: every compared cell differs and needs the parsers.
amounts_a = [f"{i}.50" for i in range(ROWS)]
amounts_b = [f"{i:,}.5" for i in range(ROWS)]
start = time.perf_counter()
for a, b in zip(amounts_a, amounts_b):
    classify_difference(a, b)
print(f"classify_difference on differing numbers, {ROWS:,} calls: {time.perf_counter() - start:.2f}s")

texts_a = [f"user{i}@example.com" for i in range(ROWS)]
texts_b = [f"user{i}@other.com" for i in range(ROWS)]
start = time.perf_counter()
for a, b in zip(texts_a, texts_b):
    classify_difference(a, b)
print(f"classify_difference on differing text, {ROWS:,} calls: {time.perf_counter() - start:.2f}s")

start = time.perf_counter()
for a in texts_a:
    classify_difference(a, a)
print(f"classify_difference on identical cells, {ROWS:,} calls: {time.perf_counter() - start:.2f}s")
