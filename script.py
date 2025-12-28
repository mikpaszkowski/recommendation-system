import pathlib

import pandas as pd


path = pathlib.Path("datasets/meta_Electronics.jsonl")
total = with_data = 0

for chunk in pd.read_json(path, lines=True, chunksize=50000):
    mask = chunk["bought_together"].notna()
    total += len(chunk)
    with_data += mask.sum()

print(f"total rows: {total}, with bought_together: {with_data}")