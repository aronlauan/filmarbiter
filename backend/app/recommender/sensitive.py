"""Keywords we never show as a reason for a recommendation.

"Because you liked films tagged 'interracial relationship'" (or "woman director",
"east asian lead") reads as us profiling the user or the film by race, ethnicity or
gender. These tags still count towards similarity; they're only hidden from the
explanation. Matching is on whole words so "car race", "black and white" or
"blackmail" survive.
"""

import re
from functools import cache

_PATTERNS = [
    # Race and racial relationships ("interracial romance", "racism", "biracial").
    r"\b(inter|bi|multi)?racial(ly)?\b",
    r"\bracis[mt]s?\b",
    r"\brace (relations|politics|riots?|issues|war)\b",
    r"\bmixed[- ]race\b",
    r"\bblack(face| (american|british|cinema|lead|lgbt|people|community|culture|history|"
    r"power|panther party|lives matter|man|woman|women|men|girl|boy|teen|family|"
    r"character|actor|actress|director))\b",
    r"\bwhite (supremac\w*|privilege|savior|saviour|nationalis\w*|power|trash)\b",
    r"\bpassing (for|as) white\b",
    r"\b(segregation|apartheid|ku klux klan|kkk|jim crow|civil rights)\b",
    # Ethnicity and ethnic identity ("asian american", "east asian lead", "jewish family").
    r"\bethnic\w*\b",
    r"\b(african|asian|chinese|japanese|korean|vietnamese|filipino|indian|mexican|cuban|"
    r"puerto rican|italian|irish|jewish|arab|armenian|native|black|latino|latina) americans?\b",
    r"\b(east|south|southeast|british) asians?\b",
    r"\basian (lead|cinema|people|community|culture|family|woman|man|girl|boy)\b",
    r"\b(african american|hispanic|latin[aox]s?|latinx|chican[ao]s?)\b",
    r"\b(indigenous|aborigin\w*|first nations|native americans?|native peoples?|inuit|romani)\b",
    r"\b(jew|jews|jewish|antisemit\w*|anti-semit\w*)\b",
    r"\barabs?\b",
    r"\bminorit(y|ies)\b",
    # Gender ("woman director", "female protagonist", "male friendship", "teenage girl").
    r"\b(wom[ae]n\w*|manhood|m[ae]n)\b",  # "old man" too, minus the idioms below
    r"\b(fe)?males?\b",
    r"\b(girls?|boys?|girlhood|boyhood)\b",
    r"\b(gender\w*|feminis[mt]\w*|femininity|masculinity|sexis[mt]|misogyn\w*|misandry|"
    r"patriarch\w*|matriarch\w*|transgender|trans (wo)?m[ae]n|non-binary|nonbinary|"
    r"sex change|battle of the sexes)\b",
]
_RE = re.compile("|".join(f"(?:{p})" for p in _PATTERNS), re.IGNORECASE)

# Idioms where "man" isn't about gender. They're removed before matching, so
# "man vs woman" is still hidden but "one man army" isn't.
_IDIOMS = [
    "one man army",
    "two man army",
    "con man",
    "best man",
    "hit man",
    "repo man",
    "dead man",
    "wanted man",
    "masked man",
    "invisible man",
    "iron man",
    "spider-man",
    "ice cream man",
    "newspaper man",
    "prehistoric man",
    "ape man",
    "mountain man",
    "slender man",
    "hanged man",
    "inside man",
    "law man",
    "right hand man",
    "last man on earth",
    "no man's land",
    "man on the run",
    "man hunt",
    "man child",
    "man beast",
    "man eating plant",
    "men in black",
]
_MAN_VS = r"\bman (vs\.?|versus|against) "
_IDIOM_RE = re.compile(
    "|".join([rf"\b{re.escape(i)}\b" for i in _IDIOMS] + [_MAN_VS]), re.IGNORECASE
)


@cache  # explain() asks about the same ~24k catalog keywords repeatedly
def is_sensitive(keyword: str) -> bool:
    keyword = _IDIOM_RE.sub(" ", keyword)
    return _RE.search(keyword) is not None
