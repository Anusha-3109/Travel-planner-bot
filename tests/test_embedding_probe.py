"""The embedding probe's scoring, with made-up vectors and no model calls."""

import pytest

from backend.travel_data.catalog import load_catalog
from evaluation import embeddings
from evaluation.embeddings import (
    EUROPE_CITIES,
    GROUPS,
    TEST_CITIES,
    build_questions,
    cosine,
    europe_questions,
    group_scores,
    language_scores,
    retrieval_scores,
)


def test_cosine():
    assert cosine([1, 0], [1, 0]) == 1.0 and cosine([1, 0], [0, 1]) == 0.0
    assert cosine([1, 1], [-1, -1]) == pytest.approx(-1.0) and cosine([0, 0], [1, 0]) == 0.0


def test_every_group_has_ten_distinct_pairs():
    assert set(GROUPS) == {"paraphrase", "cross_lingual", "city_differs", "category_differs", "unrelated"}
    assert all(len(pairs) == 10 and all(a != b for a, b in pairs) for pairs in GROUPS.values())


def test_group_scores_average_each_group_and_give_the_paraphrase_gap(monkeypatch):
    """A fake model where paraphrase pairs are identical and every other pair is at right angles."""
    paraphrases = {text for pair in GROUPS["paraphrase"] for text in pair}
    monkeypatch.setattr(embeddings, "GROUPS", {"paraphrase": GROUPS["paraphrase"],
                                               "city_differs": [("a", "b")]})
    result = group_scores(lambda texts: [[1.0, 0.0] if t in paraphrases or t == "a" else [0.0, 1.0] for t in texts])
    assert result["means"] == {"paraphrase": 1.0, "city_differs": 0.0} and result["gap"] == 1.0
    assert result["pairs"]["paraphrase"] == [1.0] * 10


def test_retrieval_counts_first_places_right_cities_and_margins():
    documents = [{"text": "Zoo, Tulsa", "source": "attraction: Zoo, Tulsa", "city": "Tulsa"},
                 {"text": "Pier, Omaha", "source": "attraction: Pier, Omaha", "city": "Omaha"}]
    questions = {"place": [{"question": "zoo", "city": "Tulsa", "source": "attraction: Zoo, Tulsa"},
                           {"question": "pier", "city": "Omaha", "source": "attraction: Pier, Omaha"}],
                 "city": [{"question": "museums in Tulsa", "city": "Tulsa"}]}
    vectors = {"Zoo, Tulsa": [1.0, 0.0], "Pier, Omaha": [0.0, 1.0], "zoo": [1.0, 0.2], "pier": [1.0, 0.1],
               "museums in Tulsa": [0.9, 0.1]}
    result = retrieval_scores(lambda texts: [vectors[t] for t in texts], documents, questions)
    assert (result["place_hits"], result["city_hits"]) == (1, 1)
    zoo, pier, city = result["rows"]
    assert zoo["hit"] and zoo["margin"] > 0 and not pier["hit"] and pier["margin"] < 0
    assert pier["first"] == "attraction: Zoo, Tulsa" and city["hit"]


def test_questions_have_a_place_and_a_city_question_per_test_city():
    questions = build_questions(load_catalog())
    assert len(questions["place"]) == len(questions["city"]) == len(TEST_CITIES)
    assert all(q["city"].lower() not in q["question"].lower() for q in questions["place"])
    assert all(q["city"] in q["question"] and q["city"] in q["german"] for q in questions["city"])
    assert {q["kind"] for q in questions["city"]} == {"museum", "restaurant", "stay"}
    assert questions["city"][0]["german"] == "Welche Museen gibt es in Tulsa?"
    assert build_questions(load_catalog()) == questions  # a fixed seed


def test_european_questions_use_the_german_city_names():
    questions = europe_questions()
    assert len(questions) == 2 * len(EUROPE_CITIES)
    assert questions[0] == {"question": "museums in Vienna", "city": "Vienna", "kind": "museum",
                            "german": "Welche Museen gibt es in Wien?"}
    assert all(q["city"] not in q["german"] and EUROPE_CITIES[q["city"]] in q["german"] for q in questions)


def test_language_check_fuses_several_searches_and_counts_city_and_kind():
    documents = [{"text": "Zoo", "source": "attraction: Zoo, Vienna", "city": "Vienna", "category": "attraction"},
                 {"text": "Inn", "source": "accommodation: Inn, Vienna", "city": "Vienna", "category": "accommodation"},
                 {"text": "Pier", "source": "attraction: Pier, Rome", "city": "Rome", "category": "attraction"}]
    vectors = {"Zoo": [1.0, 0.0, 0.0], "Inn": [0.0, 1.0, 0.0], "Pier": [0.0, 0.0, 1.0],
               "Wo schlafen in Wien?": [0.0, 0.0, 1.0], "a place to stay in Vienna": [0.0, 1.0, 0.0]}

    def embed(texts):
        return [vectors[t] for t in texts]

    doc_vectors = embeddings._unit(embed([d["text"] for d in documents]))
    question = [{"question": "a place to stay in Vienna", "city": "Vienna", "kind": "stay"}]
    alone = language_scores(embed, documents, doc_vectors, question, [["Wo schlafen in Wien?"]])
    assert (alone["city_hits"], alone["kind_hits"]) == (0, 0)  # the German search alone finds Rome's pier first
    fused = language_scores(embed, documents, doc_vectors, question,
                            [["Wo schlafen in Wien?", "a place to stay in Vienna"]])
    assert fused["questions"] == 1 and fused["kind_share"] == 0.333
    assert embeddings._fused([[2, 0], [1, 2]])[0] == 2  # found by both searches, so first
