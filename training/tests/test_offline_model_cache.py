"""Regression against the locked Hub library; no network/model weights/GPU."""
from pathlib import Path
import subprocess
import textwrap

import pytest


def test_filtered_download_and_offline_lookup_share_complete_snapshot(tmp_path):
    root = Path(__file__).resolve().parents[1]
    python = root / "envs/rl/.venv/bin/python"
    if not python.exists():
        pytest.skip("Locked RL environment is needed for this Hub integration check")
    script = textwrap.dedent('''
        import sys
        from pathlib import Path
        from huggingface_hub import snapshot_download
        from huggingface_hub.errors import IncompleteSnapshotError
        from huggingface_hub._tree_cache import TreeCacheEntry, write_tree_cache
        from browser_training.launch import MODEL_CACHE_PATTERNS
        cache = Path(sys.argv[1])
        commit = "a" * 40
        repo = "local-fixture/frozen-model"
        storage = cache / "models--local-fixture--frozen-model"
        snapshot = storage / "snapshots" / commit
        snapshot.mkdir(parents=True)
        required = ["config.json", "tokenizer.json", "model.safetensors"]
        metadata = ["README.md", "LICENSE", ".gitattributes"]
        write_tree_cache(str(storage), commit,
                         {name: TreeCacheEntry(size=1, blob_id="b" * 40)
                          for name in required + metadata})
        for name in required:
            (snapshot / name).write_text("fixture, not model weights")
        try:
            snapshot_download(repo, revision=commit, cache_dir=cache, local_files_only=True)
        except IncompleteSnapshotError as error:
            assert "README.md" in str(error) and "LICENSE" in str(error)
        else:
            raise AssertionError("Original missing-metadata failure was not reproduced")
        for name in metadata:
            (snapshot / name).write_text("fixture")
        assert Path(snapshot_download(repo, revision=commit, cache_dir=cache,
                                      local_files_only=True,
                                      allow_patterns=MODEL_CACHE_PATTERNS)) == snapshot
        (snapshot / "model.safetensors").unlink()
        try:
            snapshot_download(repo, revision=commit, cache_dir=cache, local_files_only=True,
                              allow_patterns=MODEL_CACHE_PATTERNS)
        except IncompleteSnapshotError as error:
            assert "model.safetensors" in str(error)
        else:
            raise AssertionError("Actual missing weights must still fail")
        print("Reproduced missing metadata; complete cache passes; missing weights fail")
    ''')
    result = subprocess.run([str(python), "-c", script, str(tmp_path)],
                            cwd=root, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
