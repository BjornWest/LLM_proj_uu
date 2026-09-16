from browser_training.apple_probe import splits, score, summarize


def test_disjoint_combinations_with_known_words():
    data = splits()
    assert data == splits()
    assert len(data["train"]) == 64 and len(data["heldout"]) == 16
    training = {tuple(r["words"]) for r in data["train"]}
    heldout = {tuple(r["words"]) for r in data["heldout"]}
    assert not training & heldout
    assert {w for r in data["heldout"] for w in r["words"]} <= {w for r in data["train"] for w in r["words"]}
    for row in data["train"] + data["heldout"]:
        assert "apple" not in str(row["messages"][:-1])
        assert all(score(row["words"], row["messages"][-1]["content"]).values())


def test_scoring_rejects_repetition_loss_and_explanations():
    words = ["red", "boat"]
    assert all(score(words, "red apple boat apple").values())
    assert not score(words, "red boat")["exact_match"]
    assert not score(words, "red apple red apple")["word_preservation"]
    assert score(words, "red apple red apple")["apple_placement"]
    assert not score(words, "red apple boat apple extra")["apple_placement"]
    assert not score(words, "red apple boat apple.")["exact_match"]
    assert summarize([score(words, "red apple boat apple"), score(words, "red boat")])["exact_match"] == 0.5
