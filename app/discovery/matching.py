"""Deterministic pilot heuristics. Every decision includes evidence for review."""
import re

ALIASES = {
    "react": ["react", "react.js", "reactjs"], "react.js": ["react", "react.js", "reactjs"],
    "node.js": ["node.js", "nodejs", "node"], "express.js": ["express.js", "expressjs", "express"],
    "next.js": ["next.js", "nextjs"], "postgresql": ["postgresql", "postgres"],
    "rest apis": ["rest api", "rest apis", "restful api", "restful apis"],
    "rag": ["rag", "retrieval augmented generation", "retrieval-augmented generation"],
    "mcp": ["mcp", "model context protocol"],
    "software engineer": ["software engineer", "software development engineer", "sde"],
    "full stack developer": ["full stack developer", "full-stack developer", "fullstack developer"],
}
ROLE_WORDS = re.compile(r"\b(engineer|developer|analyst|scientist|intern|consultant|administrator|specialist|researcher)\b", re.I)
SENIORITY = {"senior", "staff", "principal", "lead", "manager", "director", "architect"}


def contains(text, phrase):
    normalized = " ".join(text.casefold().replace("\u2013", "-").replace("\u2014", "-").split())
    variants = ALIASES.get(phrase.casefold(), [phrase.casefold()])
    return any(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", normalized) for term in variants)


def workbook_weights(configs):
    config = configs.get("Keywords for DATA")
    if not config:
        raise ValueError("Import the company workbook before discovery: DATA scoring rules are missing")
    rows = {str(row["values"][0]): row["values"][2] for row in config.rules if len(row["values"]) >= 3}
    names = {"title": "Title match", "skills": "Strong skill match", "experience": "Experience fit",
             "location": "Location fit", "exclusion": "Exclusion hit"}
    weights = {}
    for key, name in names.items():
        value = rows.get(name)
        if not isinstance(value, (int, float)) or not -100 <= value <= 100:
            raise ValueError(f"Missing or invalid workbook weight: {name}; reimport the source")
        weights[key] = value
    return weights


def experience_fit(title, description, maximum):
    text = title + " " + description
    # Only numbers attached to years are considered, not arbitrary JD numbers.
    pattern = r"\b(\d{1,2})(?:(?:\s*[-–]\s*|\s+to\s+)(\d{1,2}))?\s*\+?\s*(?:years?|yrs?)\b"
    found = []
    for match in re.finditer(pattern, text, re.I):
        after = text[match.end():match.end() + 90].casefold()
        before = text[max(0, match.start() - 25):match.start()].casefold()
        # Company history or benefit tenures are not experience requirements.
        if re.match(r"\s+(?:of\s+)?(?:(?:professional|relevant|industry|hands-on|work|software development)\s+)?experience\b", after) or re.search(r"(?:minimum|at least|requires?)\s*$", before):
            found.append(match)
    too_high = [m.group(0) for m in found if int(m.group(1)) > maximum]
    if too_high:
        return "mismatch", too_high
    if found:
        return "match", [m.group(0) for m in found]
    if any(contains(title, term) for term in ("junior", "intern", "internship", "graduate", "entry level", "fresher", "associate")):
        return "match", ["Early-career wording in title; verify actual experience requirements"]
    return "unknown", []


def evaluate(posting, company, candidate, configs, weights):
    title, description = posting["title"], posting["description"]
    text = title + " " + description
    keywords = list(dict.fromkeys(k for p in company.keyword_profiles for k in p["keywords"]))
    exclusions = list(dict.fromkeys(k for p in company.keyword_profiles for k in p["exclusions"]))
    roles = [k for k in keywords if ROLE_WORDS.search(k)]
    title_matches = [k for k in roles if contains(title, k)]
    hits = [k for k in exclusions if contains(title if k.casefold() in SENIORITY else text, k)]
    strong = [s for s in candidate.demonstrated_skills if contains(text, s)]
    adjacent = [s for s in candidate.adjacent_skills if contains(text, s) and
                not any(contains(s, known) for known in candidate.demonstrated_skills)]
    experience, experience_evidence = experience_fit(title, description, candidate.max_experience_years)
    locations = [loc for loc in candidate.locations if contains(posting["location"], loc)]
    remote_only = posting["location"].strip().casefold() in ("", "remote", "remote worldwide", "worldwide")
    location = "match" if locations else "unknown" if remote_only else "mismatch"
    # Extract mentions only; a keyword occurrence does not establish a required skill.
    vocabulary = set(candidate.demonstrated_skills + candidate.adjacent_skills)
    for profile in company.keyword_profiles:
        config = configs.get(profile["sheet"])
        if config:
            for entry in config.keyword_bank:
                if str(entry.get("type", "")).casefold() in ("skill", "skill or domain") and entry["phrase"] in keywords:
                    vocabulary.add(entry["phrase"])
    skill_mentions = sorted(s for s in vocabulary if contains(text, s))
    missing = [s for s in skill_mentions if not any(contains(s, known) or contains(known, s) for known in candidate.demonstrated_skills)]
    # DATA supplies the common 100-point baseline. AI/Cyber allow limited stretch.
    adjacent_enabled = any(p["sheet"] in ("Keywords for AI", "Keywords for Cyber") for p in company.keyword_profiles)
    points = {
        "title": weights["title"] if title_matches else 0,
        "demonstrated_skills": min(5, len(strong)) * weights["skills"] / 5,
        "adjacent_skills": min(10, 2 * len(adjacent)) if adjacent_enabled else 0,
        "experience": weights["experience"] if experience == "match" else 0,
        "location": weights["location"] if location == "match" else 0,
        "exclusion": weights["exclusion"] if hits else 0,
    }
    flags = ["Verify work authorization and the live description before applying"]
    if not description:
        flags.append("Job description missing")
    if experience != "match":
        flags.append(f"Experience fit: {experience}")
    if location != "match":
        flags.append(f"Location eligibility: {location}; remote alone does not establish India eligibility")
    if hits:
        flags.append("Workbook exclusion terms matched; inspect context")
    disposition = "review_required"
    if not title_matches:
        disposition = "irrelevant"
    elif hits or experience == "mismatch" or location == "mismatch":
        disposition = "excluded"
    score = max(0, min(100, sum(points.values())))
    if disposition in ("excluded", "irrelevant"):
        score = 0
    return {
        "policy_version": "pilot-v1", "score": score, "disposition": disposition,
        "points": points, "title_matches": title_matches, "exclusion_matches": hits,
        "demonstrated_skill_matches": strong, "adjacent_skill_matches": adjacent,
        "skill_mentions": skill_mentions, "skills_to_review": missing,
        "experience_fit": experience, "experience_evidence": experience_evidence,
        "location_fit": location, "location_matches": locations, "review_flags": flags,
        "workbook_sheets": list(dict.fromkeys(p["sheet"] for p in company.keyword_profiles)),
        "weights": weights,
        "scoring_note": "DATA workbook weights form the baseline. AI/Cyber use a pilot adjacent bonus of 2 per skill, capped at 10. Total capped at 100; failed gates force zero. Skill mentions are not verified job requirements.",
    }
