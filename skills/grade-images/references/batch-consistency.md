# Batch consistency

Use the batch renderer after reviewing one shared look and deciding skin
protection through scene routing.

```text
python scripts/batch_render.py INPUT [INPUT ...] --look LOOK.json \
  --output-dir results --workers 4 --max-size 1200 \
  [--disable-skin-protection]
```

The renderer preserves input order, derives correction independently for each
image, applies one byte-identical shared look, and uses bounded parallelism. Set
workers between 1 and 8 according to available memory.

Review `batch-render-manifest.json` before accepting outputs:

- `all_looks_identical` and `output_order_deterministic` must be true;
- inspect every `outlier_reasons` entry;
- compare exposure and white-balance correction outliers separately from output
  luminance and saturation outliers;
- retain pixel hashes for deterministic repeat checks;
- treat `estimated_peak_array_bytes` as an array-memory estimate, not total
  process RSS.

Robust outlier flags use the batch median and MAD. They identify review targets,
not defects. A deliberately different frame may be valid, while a coherent but
incorrect set may contain no statistical outlier. Do not delete or silently
weaken outliers; review them against the treatment contract.
