"""Offline replay selection using measured causal-loss tokens, without replacement.

Every browser example is retained. Replay examples are whole conversations;
there is no chunking, packing, repeated oversampling, or change to loss masks.
"""
import hashlib
import json
import random

from .outcomes import canonical, require


def row_hash(row):
    return hashlib.sha256(canonical(row).encode()).hexdigest()


def deduplicate(rows):
    seen, unique = set(), []
    for row in rows:
        require(isinstance(row, dict) and set(row) == {'messages'} and isinstance(row['messages'], list)
                and row['messages'], 'Expected normalized conversation rows with only messages')
        identity = row_hash(row)
        if identity not in seen:
            seen.add(identity)
            unique.append(row)
    return unique, len(rows)-len(unique)


def mix(browser, replay, measure, *, replay_fraction=0.05, seed=42, tolerance=0.005, protected=()):
    require(type(replay_fraction) in (int,float) and 0 <= replay_fraction <= 0.1,
            'Replay fraction must be between 0 and 0.1 for this initial experiment')
    require(type(seed) is int and seed >= 0 and type(tolerance) in (int,float) and 0 <= tolerance <= 0.1,
            'Invalid mixture seed/tolerance')
    browser, b_duplicates=deduplicate(browser)
    replay, r_duplicates=deduplicate(replay)
    require(browser, 'Browser dataset is empty')
    bh, rh={row_hash(row) for row in browser}, {row_hash(row) for row in replay}
    require(not bh & rh, 'Browser/replay exact-content overlap')
    protected_hashes={row_hash(row) for row in protected}
    require(not (bh | rh) & protected_hashes, 'Training content overlaps a protected holdout')
    def measured(row, source):
        stats=measure(row)
        require(set(stats) == {'processed_tokens','loss_tokens'} and
                all(type(v) is int and v > 0 for v in stats.values()) and
                stats['loss_tokens'] <= stats['processed_tokens'], 'Invalid token measurement')
        return dict(row=row, source=source, example_sha256=row_hash(row), **stats)
    b=[measured(row,'browser') for row in browser]
    r=[measured(row,'replay') for row in replay] if replay_fraction else []
    rng=random.Random(seed)
    rng.shuffle(r)
    b_loss=sum(row['loss_tokens'] for row in b)
    target=b_loss*replay_fraction/(1-replay_fraction)
    selected=[]
    total=0
    # Deterministic greedy whole-example subset; reports achieved ratio, never claims exact.
    for row in r:
        if abs(total+row['loss_tokens']-target) < abs(total-target):
            selected.append(row)
            total+=row['loss_tokens']
    actual=total/(b_loss+total)
    require(abs(actual-replay_fraction) <= tolerance+1e-12,
            f'Whole-example replay share {actual:.6f} misses target {replay_fraction:.6f}; supply more/smaller examples or review tolerance')
    mixed=b+selected
    rng.shuffle(mixed)
    processed=sum(row['processed_tokens'] for row in mixed)
    report=dict(schema_version=1, seed=seed, requested_replay_loss_fraction=replay_fraction,
                actual_replay_loss_fraction=actual, tolerance=tolerance,
                replay_processed_fraction=sum(row['processed_tokens'] for row in selected)/processed,
                processed_tokens=processed, loss_tokens=b_loss+total,
                browser_examples=len(b), replay_examples=len(selected), available_replay_examples=len(replay),
                browser_exact_duplicates_removed=b_duplicates, replay_exact_duplicates_removed=r_duplicates,
                protected_examples_checked=len(protected_hashes),
                examples=[{k:v for k,v in row.items() if k!='row'} for row in mixed],
                limitations='Exact content checks only; semantic duplicates and task/instance exposure require the data catalog. No packing or truncation.')
    return [row['row'] for row in mixed], report
