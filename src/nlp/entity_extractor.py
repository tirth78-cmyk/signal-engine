"""
Entity Extractor — spaCy-based NER for company names, people, technologies.
"""

import re
from typing import Optional

from src.utils.logging import get_logger

logger = get_logger("nlp.entity_extractor")


# Known pharma companies for fuzzy matching
KNOWN_COMPANIES = {
    "pfizer", "novartis", "roche", "astrazeneca", "sanofi", "amgen",
    "gilead", "bms", "bristol-myers squibb", "merck", "eli lilly", "lilly",
    "abbvie", "regeneron", "vertex", "biogen", "moderna", "biontech",
    "takeda", "novo nordisk", "gsk", "glaxosmithkline", "johnson & johnson",
    "j&j", "astellas", "daiichi sankyo", "boehringer ingelheim",
    "iqvia", "veeva", "medidata", "covance", "labcorp", "ppd",
}

# Known technology platforms
KNOWN_TECHNOLOGIES = {
    "databricks", "snowflake", "aws", "azure", "gcp", "google cloud",
    "veeva", "salesforce", "sap", "oracle", "tableau", "power bi",
    "python", "r", "spark", "kafka", "airflow", "dbt",
    "terraform", "kubernetes", "docker", "redis",
}


class EntityExtractor:
    """Extracts named entities from signal text using spaCy + custom rules."""

    def __init__(self):
        self._nlp = None
        self._initialized = False

    async def initialize(self):
        """Load spaCy model."""
        if self._initialized:
            return

        try:
            import spacy
            from config.settings import settings
            logger.info("loading_spacy_model", model=settings.nlp.spacy_model)
            self._nlp = spacy.load(settings.nlp.spacy_model)
            self._initialized = True
            logger.info("entity_extractor_initialized")
        except (ImportError, OSError) as e:
            logger.warning("spacy_not_available", error=str(e))
            self._initialized = True  # continue with rule-based only

    def extract(self, text: str) -> dict:
        """
        Extract entities from text.
        Returns dict with: companies, people, technologies, locations, organizations.
        """
        entities = {
            "companies": [],
            "people": [],
            "technologies": [],
            "locations": [],
            "organizations": [],
            "monetary": [],
        }

        # Phase 1: spaCy NER
        if self._nlp:
            doc = self._nlp(text[:5000])
            for ent in doc.ents:
                if ent.label_ == "PERSON":
                    entities["people"].append(ent.text)
                elif ent.label_ == "ORG":
                    entities["organizations"].append(ent.text)
                elif ent.label_ in ("GPE", "LOC"):
                    entities["locations"].append(ent.text)
                elif ent.label_ == "MONEY":
                    entities["monetary"].append(ent.text)

        # Phase 2: Rule-based company matching
        text_lower = text.lower()
        for company in KNOWN_COMPANIES:
            if company in text_lower:
                entities["companies"].append(company.title())

        # Phase 3: Technology detection
        for tech in KNOWN_TECHNOLOGIES:
            if tech.lower() in text_lower:
                entities["technologies"].append(tech)

        # Phase 4: Extract job titles via regex
        title_pattern = r"(?i)\b(chief\s+\w+\s+officer|vp\s+of\s+\w+|head\s+of\s+\w+|director\s+of\s+\w+|svp|evp|president|ceo|cto|cfo|cdo|cmo|cio)\b"
        titles = re.findall(title_pattern, text)
        if titles:
            entities["job_titles"] = list(set(titles))

        # Deduplicate
        for key in entities:
            entities[key] = list(set(entities[key]))

        return entities

    def extract_company_name(self, text: str) -> Optional[str]:
        """Try to extract the primary company name from signal text."""
        text_lower = text.lower()

        # Check known companies first
        for company in KNOWN_COMPANIES:
            if company in text_lower:
                return company.title()

        # Use spaCy ORG entities
        if self._nlp:
            doc = self._nlp(text[:1000])
            orgs = [ent.text for ent in doc.ents if ent.label_ == "ORG"]
            if orgs:
                return orgs[0]

        return None

    def extract_keywords(self, text: str, top_n: int = 10) -> list[str]:
        """Extract top keywords using TF-based approach with spaCy."""
        if not self._nlp:
            # Fallback: simple word frequency
            words = re.findall(r"\b[a-zA-Z]{4,}\b", text.lower())
            freq = {}
            for w in words:
                freq[w] = freq.get(w, 0) + 1
            return sorted(freq, key=freq.get, reverse=True)[:top_n]

        doc = self._nlp(text[:5000])
        # Extract nouns and proper nouns
        keywords = []
        for token in doc:
            if token.pos_ in ("NOUN", "PROPN") and not token.is_stop and len(token.text) > 3:
                keywords.append(token.lemma_.lower())

        # Frequency ranking
        freq = {}
        for kw in keywords:
            freq[kw] = freq.get(kw, 0) + 1

        return sorted(freq, key=freq.get, reverse=True)[:top_n]
