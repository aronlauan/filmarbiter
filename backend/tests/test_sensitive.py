import pytest

from app.recommender.sensitive import is_sensitive


@pytest.mark.parametrize(
    "keyword",
    [
        # race and racial relationships
        "interracial relationship",
        "interracial romance",
        "racism",
        "racial segregation",
        "race relations",
        "biracial",
        "mixed race",
        "black cinema",
        "blackface",
        "white supremacy",
        "passing for white",
        "ku klux klan",
        # ethnicity
        "east asian lead",
        "asian american",
        "african american",
        "native american",
        "indigenous peoples",
        "hispanic",
        "jewish family",
        "ethnic stereotype",
        # gender
        "woman director",
        "female protagonist",
        "male friendship",
        "teenage girl",
        "older man younger woman relationship",
        "old man",
        "ladies' man",
        "man vs woman",
        "feminism",
        "gender roles",
        "transgender",
        "Woman Director",  # case-insensitive
    ],
)
def test_hidden(keyword: str) -> None:
    assert is_sensitive(keyword)


@pytest.mark.parametrize(
    "keyword",
    [
        "heist",
        "black and white",
        "black magic",
        "blackmail",
        "black hole",
        "car race",
        "race against time",
        "alien race",
        "the white house",
        "great white shark",
        "one man army",
        "con man",
        "man vs machine",
        "iron man",
        "spider-man",
        "no man's land",
        "father son relationship",
        "manhattan",
        "salesman",
        "immigrant",
    ],
)
def test_kept(keyword: str) -> None:
    assert not is_sensitive(keyword)
