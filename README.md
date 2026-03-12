# Improzo Signal Engine

**Automated Signal Intelligence Engine** for the Improzo GTM Platform. Collects, classifies, scores, and pushes buying signals from 15+ web sources to HubSpot CRM.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    FastAPI REST API                       │
│              WebSocket Real-Time Feed                     │
├──────────┬──────────┬──────────┬──────────┬─────────────┤
│ Scrapers │   NLP    │ Scoring  │ HubSpot  │  Scheduler  │
│          │ Pipeline │  Engine  │Connector │             │
├──────────┴──────────┴──────────┴──────────┴─────────────┤
│              SQLite / PostgreSQL + Redis                  │
└─────────────────────────────────────────────────────────┘
```

### 4-Stage Pipeline

1. **Collection** — 7 scrapers across 6 source categories
2. **Deduplication** — SHA-256 hash + cosine similarity (0.85 threshold)
3. **Classification** — Sentence-transformers + keyword regex (12 signal types)
4. **Scoring & Push** — 3-dimension scoring (1-15) + HubSpot Custom Objects

## Scrapers

| Scraper | Source Type | Sources |
|---------|-----------|---------|
| NewsAPI | News APIs | NewsAPI.org, GNews |
| RSS Feeds | RSS/Atom | 14 pharma newsrooms + publications |
| PR Wires | Press Releases | PR Newswire, Business Wire, GlobeNewswire |
| Job Boards | Job Postings | Indeed + 10 company career pages |
| SEC EDGAR | SEC Filings | 10-K, 10-Q, 8-K for 10 pharma companies |
| Regulatory | FDA/EMA | FDA Press, EMA News |
| LinkedIn | Social | Google-indexed LinkedIn posts |

## Signal Types

Leadership Change, Job Posting, Technology Adoption, Funding Event, Expansion, Partnership, Regulatory Change, Earnings Event, Product Launch, M&A Activity, Content Engagement, Event Attendance

## Quick Start

```bash
# Clone
git clone https://github.com/TirthankarRay/signal-engine.git
cd signal-engine

# Configure
cp .env.example .env
# Edit .env with your API keys

# Run with Docker
docker compose up -d

# Or run locally
pip install -e .
python -m spacy download en_core_web_sm
python -m src.main
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Health check |
| GET | `/health` | Engine health metrics |
| GET | `/scrapers` | All scraper statuses |
| GET | `/signals` | List signals (filter, sort, paginate) |
| GET | `/signals/{id}` | Get signal detail |
| POST | `/signals/{id}/verify` | Verify a signal |
| POST | `/signals/{id}/reject` | Reject a signal |
| POST | `/signals/{id}/push` | Push to HubSpot |
| POST | `/pipeline/scan` | Trigger full scan |
| POST | `/pipeline/process` | Process single signal |
| GET | `/pipeline/metrics` | Pipeline metrics |
| GET | `/analytics/distribution` | Signal type distribution |
| GET | `/analytics/top-companies` | Top companies by signals |
| GET | `/analytics/source-stats` | Source statistics |
| WS | `/ws/signals` | Real-time signal feed |
| GET | `/hubspot/health` | HubSpot connectivity |
| POST | `/hubspot/setup-schema` | Create custom object schema |

## Scoring Model

**Signal Score** (1-15):
- Recency (1-5): Today=5, This week=4, This month=3, Last month=2, Older=1
- Relevance (1-5): Signal type weight + keyword boost + confidence
- Authority (1-5): SEC=5, Regulatory=5, PR Wire=4, News=3, Jobs=3, LinkedIn=2

**ICP Score** (5-25):
- Industry Fit, Size Fit, Tech Fit, Geography Fit, Budget Fit (1-5 each)

## Tech Stack

- **API**: FastAPI + Uvicorn
- **Scrapers**: httpx, BeautifulSoup, feedparser
- **NLP**: spaCy, sentence-transformers, scikit-learn
- **Database**: SQLAlchemy (async) + SQLite/PostgreSQL
- **CRM**: HubSpot API v3 (Custom Objects)
- **Scheduler**: APScheduler
- **Containerization**: Docker + Docker Compose

## License

MIT
