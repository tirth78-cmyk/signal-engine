"""
ICP (Ideal Customer Profile) Scorer — Scores accounts on 5 dimensions.
Score range: 5-25 (5 dimensions x 1-5 each).
"""

from src.models import ICPAccount
from src.utils.logging import get_logger

logger = get_logger("scoring.icp")


# Industry classification for pharma/life sciences ICP
INDUSTRY_SCORES = {
    "pharmaceutical": 5, "pharma": 5, "biopharma": 5,
    "biotechnology": 5, "biotech": 5,
    "medical devices": 4, "medtech": 4,
    "cro": 4, "contract research": 4,
    "cdmo": 4, "contract manufacturing": 4,
    "diagnostics": 3,
    "healthcare": 3, "health tech": 3,
    "life sciences": 4,
    "animal health": 2,
    "consumer health": 2,
}

# Company size scoring (by employee count)
SIZE_TIERS = [
    (50000, 5),   # mega-pharma
    (10000, 4),   # large pharma
    (1000, 3),    # mid-size
    (100, 2),     # small
    (0, 1),       # startup
]

# Technology stack indicators
TECH_INDICATORS = {
    5: ["databricks", "snowflake", "aws", "azure", "gcp"],
    4: ["veeva", "salesforce", "sap"],
    3: ["oracle", "sas", "tableau"],
    2: ["excel", "on-premise"],
    1: [],
}


class ICPScorer:
    """
    Scores accounts across 5 ICP dimensions:
    1. Industry Fit (1-5): How closely does the industry match our ICP?
    2. Size Fit (1-5): Is the company the right size?
    3. Technology Fit (1-5): Does their tech stack align with our offering?
    4. Geography Fit (1-5): Are they in target geographies?
    5. Budget Fit (1-5): Do they have the budget?
    """

    # Target geographies
    TARGET_GEOS = {
        5: ["united states", "usa", "us", "united kingdom", "uk", "germany", "switzerland"],
        4: ["france", "japan", "canada", "netherlands", "sweden", "denmark"],
        3: ["india", "china", "australia", "singapore", "ireland"],
        2: ["brazil", "south korea", "spain", "italy"],
        1: [],  # default
    }

    def score_industry(self, industry: str) -> int:
        """Score industry fit."""
        if not industry:
            return 1
        industry_lower = industry.lower()
        for keyword, score in INDUSTRY_SCORES.items():
            if keyword in industry_lower:
                return score
        return 1

    def score_size(self, employee_count: int) -> int:
        """Score company size fit."""
        for threshold, score in SIZE_TIERS:
            if employee_count >= threshold:
                return score
        return 1

    def score_technology(self, tech_stack: list[str]) -> int:
        """Score technology fit based on known stack."""
        if not tech_stack:
            return 1

        tech_lower = [t.lower() for t in tech_stack]
        best = 1
        for score, indicators in TECH_INDICATORS.items():
            if any(ind in " ".join(tech_lower) for ind in indicators):
                best = max(best, score)
        return best

    def score_geography(self, country: str, hq_location: str = "") -> int:
        """Score geographic fit."""
        location = f"{country} {hq_location}".lower()
        for score, geos in self.TARGET_GEOS.items():
            if any(geo in location for geo in geos):
                return score
        return 1

    def score_budget(self, revenue_usd: float = 0, funding_usd: float = 0) -> int:
        """Score budget fit based on revenue or funding."""
        total = max(revenue_usd, funding_usd)
        if total >= 10_000_000_000:   # $10B+
            return 5
        elif total >= 1_000_000_000:  # $1B+
            return 4
        elif total >= 100_000_000:    # $100M+
            return 3
        elif total >= 10_000_000:     # $10M+
            return 2
        else:
            return 1

    def score_account(
        self,
        account: ICPAccount,
        industry: str = "",
        employee_count: int = 0,
        tech_stack: list[str] | None = None,
        country: str = "",
        hq_location: str = "",
        revenue_usd: float = 0,
        funding_usd: float = 0,
    ) -> ICPAccount:
        """Compute full ICP score for an account."""
        account.industry_fit = self.score_industry(industry)
        account.size_fit = self.score_size(employee_count)
        account.tech_fit = self.score_technology(tech_stack or [])
        account.geo_fit = self.score_geography(country, hq_location)
        account.budget_fit = self.score_budget(revenue_usd, funding_usd)

        account.icp_score = (
            account.industry_fit +
            account.size_fit +
            account.tech_fit +
            account.geo_fit +
            account.budget_fit
        )

        # Tier assignment
        account.tier = "1" if account.icp_score >= 18 else "2"

        logger.debug(
            "account_scored",
            company=account.company_name,
            icp_score=account.icp_score,
            tier=account.tier,
        )
        return account
