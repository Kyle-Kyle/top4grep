import re

from nltk.stem import PorterStemmer

TOKEN_RE = re.compile(r"[A-Za-z0-9_+#.-]+")
STEMMER = PorterStemmer()
SEARCH_FIELDS = ("title", "abstract", "authors", "conference", "all")
CONFERENCE_ORDER = {
    "CCS": 3,
    "USENIX": 2,
    "IEEE S&P": 1,
    "NDSS": 0,
}


def normalize_token(token):
    token = token.strip().lower()
    if not token:
        return ""
    return STEMMER.stem(token)


def tokenize(text):
    if not text:
        return []
    tokens = []
    for raw in TOKEN_RE.findall(text.lower()):
        normalized = normalize_token(raw)
        if normalized:
            tokens.append(normalized)
    return tokens


def normalize_term(term):
    return [token for token in tokenize(term) if token]


def parse_query(query):
    groups = []
    for clause in query.split(","):
        clause = clause.strip()
        if not clause:
            continue

        options = []
        for option in clause.split("|"):
            normalized = normalize_term(option)
            if normalized:
                options.append(normalized)

        if options:
            groups.append(options)
    return groups


def build_search_text(paper, field):
    values = {
        "title": paper.title or "",
        "abstract": paper.abstract or "",
        "authors": paper.authors or "",
        "conference": paper.conference or "",
    }
    if field == "all":
        return " ".join(values.values())
    return values[field]


def paper_matches(paper, query_groups, field):
    if not query_groups:
        return True

    token_set = set(tokenize(build_search_text(paper, field)))
    for group in query_groups:
        if not any(all(token in token_set for token in option) for option in group):
            return False
    return True


def paper_sort_key(paper):
    conference_order = CONFERENCE_ORDER.get(paper.conference)
    if conference_order is None:
        return (-paper.year, 1, 0, (paper.title or "").lower())
    return (-paper.year, 0, -conference_order, (paper.title or "").lower())
