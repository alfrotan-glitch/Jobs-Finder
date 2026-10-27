"""Evidence-preserving editorial decisions for employer-facing applications.

Deliberately deterministic/offline: only reorders or selects owner-verified text.
Never fabricates numbers, outcomes, positions, locations, or employer claims.
"""
from __future__ import annotations

import re

# Concept matches apply to real vacancy titles, not arbitrary long job pages.
# Pattern matching is token-bounded to prevent accidental hits such as
# "nutrition" from occurring inside "malnutrition".
_ROLE_SIGNALS: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (
        re.compile(r"\b(?:polio|immunization|immunisation|vaccination|vaccine|epi)\b", re.IGNORECASE),
        ("provincial", "public health", "ministry", "authority", "coordinat", "monitor",
         "report", "community", "team", "supervis", "train", "emergency", "response",
         "health", "outreach", "field"),
    ),
    (
        re.compile(r"\b(?:coordinator|coordination|manager|management|director|programme officer|program officer)\b", re.IGNORECASE),
        ("coordinat", "stakeholder", "authority", "ministry", "provincial", "supervis", "monitor",
         "report", "program", "programme", "team", "implementation", "management"),
    ),
    (
        re.compile(r"\b(?:supervisor|supervision|team lead|team leader|head)\b", re.IGNORECASE),
        ("supervis", "team", "staff", "coach", "mentor", "capacity", "operat",
         "coordinat", "quality", "monitor", "supply"),
    ),
    (
        re.compile(r"\b(?:tfu|sam|nutrition|feeding|imam|cmam|tsfp|otp)\b", re.IGNORECASE),
        ("tfu", "sam", "nutrition", "feeding", "therapeutic", "clinical", "imam",
         "cmam", "otp", "stock", "supply", "referral"),
    ),
    (
        re.compile(r"\b(?:physician|medical doctor|clinician|clinical|medical officer|doctor)\b", re.IGNORECASE),
        ("clinical", "patient", "diagnos", "treatment", "referral", "medical",
         "inpatient", "health", "hmis"),
    ),
    (
        re.compile(r"\b(?:safeguarding|psea|protection|child protection)\b", re.IGNORECASE),
        ("safeguarding", "psea", "protection", "confidential", "policy", "child"),
    ),
    (
        re.compile(r"\b(?:emergency|outbreak|covid|response)\b", re.IGNORECASE),
        ("emergency", "outbreak", "covid", "response", "contact trac", "provincial", "health"),
    ),
    (
        re.compile(r"\b(?:administration|administrative|finance|procurement|logistics)\b", re.IGNORECASE),
        ("administ", "finance", "procure", "record", "report", "logistic", "stock"),
    ),
)


def _preferred_terms(vacancy_title: str) -> tuple[str, ...]:
    seen: list[str] = []
    for pattern, terms in _ROLE_SIGNALS:
        if pattern.search(vacancy_title or ""):
            for term in terms:
                if term not in seen:
                    seen.append(term)
    return tuple(seen)


def _count_phrase(text: str, term: str) -> int:
    normalized = str(text).casefold()
    # Match word beginnings, never inside unrelated longer words.
    return int(bool(re.search(r"(?<!\w)" + re.escape(term), normalized)))


def factual_relevance_score(value: str, vacancy_title: str, description: str = "") -> int:
    """Score an *existing attested sentence* without rewriting its contents."""
    text = str(value or "")
    title_terms = _preferred_terms(vacancy_title)
    title_score = sum((len(title_terms) - i) * _count_phrase(text, term)
                      for i, term in enumerate(title_terms))
    # A real vacancy's description breaks ties, but it must not override
    # strong title-specific relevance through sheer length or repetition.
    description_terms = set(re.findall(r"[a-z]{5,}", str(description or "").lower()))
    matching_words = {word for word in re.findall(r"[a-z]{5,}", text.lower())
                      if word in description_terms}
    description_score = min(4, len(matching_words))
    return title_score * 2 + description_score


def rank_attested_statements(
    statements: list[str], vacancy_title: str, description: str = ""
) -> list[str]:
    """Stable ordering, preserving the original list and every exact sentence."""
    return [
        text for _, text in sorted(
            enumerate(statements),
            key=lambda pair: (-factual_relevance_score(pair[1], vacancy_title, description), pair[0]),
        )
    ]


def target_verified_summary(summary: str, vacancy_title: str, description: str = "") -> str:
    """Focus a long *owner-verified* CV paragraph without adding a single claim.

    Keep the first identity sentence and rank all remaining original
    attested sentences for the target role. No factual scope is lost just
    to satisfy arbitrary page-count targets. Never paraphrase.
    """
    original = str(summary or "").strip()
    if len(original) <= 270 or not vacancy_title:
        return original
    sentences = [
        match.group().strip()
        for match in re.finditer(r"[^.!?]+(?:[.!?]+|$)", original)
        if match.group().strip()
    ]
    if len(sentences) < 3:
        return original
    # Preserve the applicant's identity/experience lead unchanged.
    identity = sentences[0]
    selected = rank_attested_statements(sentences[1:], vacancy_title, description)
    return " ".join([identity, *selected])


def concise_attested_highlights(
    highlights: list[str], *, has_cover_letter: bool
) -> list[str]:
    """Never truncate factual sentences mid-claim for a short employer email.

    A separate attached cover letter carries the full supporting argument;
    the email is just a professional introduction and attachment hand-off.
    """
    max_items = 1 if has_cover_letter else 2
    seen: set[str] = set()
    result: list[str] = []
    for candidate in highlights:
        sentence = re.sub(r"\s+", " ", str(candidate or "")).strip().strip(" -•")
        if not sentence or len(sentence) > 220:
            continue
        normalized = sentence.casefold().rstrip(".")
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(sentence)
        if len(result) == max_items:
            break
    return result


def select_employer_facing_experience(
    experience: list[dict], vacancy_title: str, description: str = "",
    *, detail: str = "focused",
) -> tuple[list[dict], int]:
    """Curate a targeted CV, preserving the unabridged Master CV separately.

    Keep every job, employer and employment date in ATS-safe reverse chronology.
    The owner-selected detailed mode retains every approved responsibility.
    Focused mode maintains substantive scope (at least two existing duties
    where available). Both preserve employer chronology and exact wording.
    """
    import copy

    original = copy.deepcopy(experience)
    total = sum(len(row.get("bullets") or []) for row in original)
    if not original:
        return [], total
    if detail == "detailed":
        return original, total
    if detail != "focused":
        raise ValueError("CV detail must be 'focused' or 'detailed'.")
    priorities: list[tuple[int, int]] = []
    for i, row in enumerate(original):
        bullets = list(row.get("bullets") or [])
        if not bullets:
            continue
        # Score the role separately, then its strongest confirmed examples.
        # Each role gets at least one real line, never an invented filler.
        role_text = str(row.get("role") or "")
        role_score = factual_relevance_score(role_text, vacancy_title, description)
        target = vacancy_title.casefold()
        role_lower = role_text.casefold()
        # For medical coordination, the source-verified supervisory and
        # clinical roles must both receive substantive space. Otherwise a
        # long generic coordination sentence from an older administrative
        # post can incorrectly outrank direct medical team leadership.
        if "coordinator" in target or "manager" in target:
            if "supervisor" in role_lower or "team leader" in role_lower:
                role_score += 10_000
            if "medical" in target and ("medical doctor" in role_lower or "clinician" in role_lower):
                role_score += 10_000
        best = sorted(
            (factual_relevance_score(bullet, vacancy_title, description)
             for bullet in bullets), reverse=True
        )[:3]
        priorities.append((i, role_score * 2 + sum(best)))
    ranked = [i for i, _ in sorted(priorities, key=lambda pair: (-pair[1], pair[0]))]
    # Focused CV retains at least two statements per verified employment
    # role where available, plus more detail in the most relevant positions.
    max_total = max(16, 2 * len(original))
    caps = {}
    for rank, index in enumerate(ranked):
        caps[index] = 6 if rank < 2 else 3 if rank < 4 else 2
    chosen = {i: min(2, len(row.get("bullets") or [])) for i, row in enumerate(original)}
    remaining = max_total - sum(chosen.values())
    # Fill strongest roles first, but allocate one further example per pass.
    while remaining > 0:
        moved = False
        for index in ranked:
            limit = min(caps.get(index, 1), len(original[index].get("bullets") or []))
            if chosen[index] < limit:
                chosen[index] += 1
                remaining -= 1
                moved = True
                if remaining <= 0:
                    break
        if not moved:
            break
    # A medical coordinator's two most recent owner-verified frontline roles
    # must not collapse to a single or double line merely because an older
    # response-team title happens to match both 'medical' and 'team leader'.
    # Reallocate existing slots from other roles; never enlarge the CV,
    # create a claim, remove a position or change source evidence.
    if "medical" in vacancy_title.casefold() and (
        "coordinator" in vacancy_title.casefold() or "manager" in vacancy_title.casefold()
    ):
        for index in range(min(2, len(original))):
            minimum = min(4, len(original[index].get("bullets") or []))
            while chosen[index] < minimum:
                donor = next(
                    (other for other in reversed(ranked)
                     if other >= 2 and chosen[other] > min(2, len(original[other].get("bullets") or []))),
                    None,
                )
                if donor is None:
                    break
                chosen[donor] -= 1
                chosen[index] += 1
    for i, row in enumerate(original):
        row["bullets"] = list(row.get("bullets") or [])[:chosen[i]]
    return original, total
