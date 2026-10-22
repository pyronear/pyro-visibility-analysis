"""Who owns a high point, and what it costs to put a camera on it.

Access cost is a structural criterion, not a detail: a tower operator charges a
recurring fee, an EPCI signs a convention. Ranking sites without that axis
produces a shortlist nobody can afford.

It used to be inferred from the owner string — « OPER » in the label meant
operator, everything else public. On a test département that heuristic fired
for nothing at all: water utilities, delegates and tower operators all came
out « public », so the
public-only scenario was identical to the open one and the comparison said
nothing.

The mapping is now declared per region, under `gestionnaires` in
`data/<region>/scenarios.json`:

    {"gestionnaires": {"defaut": "operateur",
                       "public": ["SDIS", "Syndicat des eaux", "Commune"],
                       "delegataire": ["SUEZ", "VEOLIA"]}}

Matching is on accent-insensitive, case-insensitive substrings, because the
labels come from three sources that spell nothing the same way — a SDIS
spreadsheet, the ANFR `SUP_PROPRIETAIRE` table, and hand-typed conventions.
Defaulting to `operateur` is deliberate: an unrecognised owner is assumed to
cost money, so a missing entry understates the affordable set rather than
overstating it.
"""

import json
import os
import unicodedata

DEFAUT = "operateur"

# Used when a region declares nothing, so the pipeline still runs.
TABLE_PAR_DEFAUT = {
    "defaut": DEFAUT,
    "public": ["SDIS", "Commune", "communaut", "Syndicat des eaux", "ONF",
               "Conseil", "Ets public", "Etat", "SNCF", "DDE", "RTE",
               "Aviation Civile", "ANFR", "PUBLIC"],
    "operateur": ["ORANGE", "TDF", "SFR", "BOUYGUES", "FREE", "TOTEM",
                  "Towercast", "ATC", "Cellnex", "OPERATEUR", "OPER",
                  "Société Privée", "Particulier"],
}


def _norm(value):
    text = unicodedata.normalize("NFD", str(value or ""))
    return "".join(c for c in text if unicodedata.category(c) != "Mn").upper()


def charger(region):
    """Owner categories declared for `region`, falling back to the defaults."""
    path = os.path.join("data", region, "scenarios.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            config = json.load(handle)
        if "gestionnaires" in config:
            return config["gestionnaires"]
    return TABLE_PAR_DEFAUT


def categoriser(owner, table=None):
    """Category of one owner label.

    The longest matching pattern wins, so « Société Privée » is not shadowed by
    a shorter entry that happens to be a substring of it.
    """
    table = table or TABLE_PAR_DEFAUT
    owner_n = _norm(owner)
    best, best_len = table.get("defaut", DEFAUT), 0
    for categorie, motifs in table.items():
        # « defaut » holds a value and « _note » a comment: neither is a
        # category. Without this filter, iterating the comment string would
        # yield its characters, some of which match everything.
        if categorie == "defaut" or categorie.startswith("_"):
            continue
        if isinstance(motifs, str):
            motifs = [motifs]
        for motif in motifs:
            motif_n = _norm(motif)
            if motif_n and motif_n in owner_n and len(motif_n) > best_len:
                best, best_len = categorie, len(motif_n)
    return best


def categories(table=None):
    """Category names declared, in declaration order."""
    table = table or TABLE_PAR_DEFAUT
    return [k for k in table if k != "defaut" and not k.startswith("_")]
