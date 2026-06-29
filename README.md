# NEPSE News & Market Data Pipeline

A real-time pipeline that scrapes 20 Nepali news portals and NEPSE live market index every 30 minutes. Built for analyzing news and market data that impacts the Nepal Stock Exchange (NEPSE).

---

## What This Project Does

1. Every 30 minutes, scrapes 20 Nepali news portals
2. Saves articles (title, body, category, source) to PostgreSQL
3. Scrapes NEPSE main index + selected sector indices from Merolagani
4. Saves all index data to PostgreSQL
5. Exposes results via a REST API
6. Serves a React dashboard via Nginx for market/news monitoring

---

## News Portals Scraped (20 total)

### Tier 1 — Finance and NEPSE Focused
Merolagani, Sharesansar, Nepsealpha, NepseKhabar, Nepali Paisa, Karobar Daily, Arthik Abhiyan, Biznews Nepal, Stock Nepali, NEPSE Trading

### Tier 2 — General News (Politics, Economy, Policy)
Onlinekhabar, Setopati, Ratopati, Ekantipur, Nagarik News, The Himalayan Times, MyRepublica, Republica, Annapurna Post, Nepal Live

---

## NEPSE Sector Indices Tracked
Banking, Development Bank, Finance, Hydropower, Insurance, Microfinance, Manufacturing, Investment, Hotel, Trading

---

## Technology Used

| Technology | Purpose |
|---|---|
| Python 3.11 | Main programming language |
| BeautifulSoup4 | Web scraping |
| PostgreSQL | Database |
| FastAPI | REST API |
| APScheduler | Runs every 30 minutes automatically |
| Docker | Deployment |

---

## Project Structure

```
nepali-news-pipeline/
│
├── config/
│   ├── __init__.py
│   └── config.py              # Settings from environment variables
│
├── db/
│   ├── __init__.py
│   ├── connection.py          # PostgreSQL connection + creates tables
│   └── writer.py              # Saves news articles and NEPSE index data
│
├── scraper/
│   ├── __init__.py
│   ├── scrapers.py            # 20 portal scrapers using BeautifulSoup
│   ├── nepse_scraper.py       # NEPSE live index + sector index scraper
│   └── scheduler.py           # Runs full pipeline every 30 minutes
│
├── main.py                    # FastAPI — starts scheduler + API endpoints
├── Dockerfile                 # Server setup instructions
├── docker-compose.yml         # Runs pipeline + PostgreSQL together
├── requirements.txt           # Python libraries needed
├── .env.example               # Environment variable template
└── .gitignore
```

---

## Database Tables

### `nepse_news`
Stores all scraped news articles.
| Column | Description |
|---|---|
| source | Which portal (merolagani, setopati, etc.) |
| portal_tier | finance or general |
| url | Article URL (unique) |
| title | Article headline |
| body | Article text |
| category | News category |
| published_at | When article was published |
| scraped_at | When we collected it |

### `nepse_index`
Stores NEPSE index values every 30 minutes.
| Column | Description |
|---|---|
| index_name | NEPSE or sector name (Banking, Hydropower etc.) |
| value | Index value |
| change | Change from previous |
| percent_change | Percentage change |
| scraped_at | When we collected it |

---

## How to Deploy

```bash
git clone https://github.com/shiksha777-max/Sim-Alpha-Web-Scrapping-
cd Sim-Alpha-Web-Scrapping-
cp .env.example .env
# Fill in DB credentials in .env
docker-compose up --build
```

After startup:
- Dashboard (Nginx): `http://localhost`
- FastAPI direct: `http://localhost:8001`

---

## API Endpoints

### GET /articles
```
GET /articles?hours=24&tier=finance&limit=50
```
Returns recently scraped news articles.

### GET /nepse-index
```
GET /nepse-index?hours=24
```
Returns NEPSE main index and sector indices for the last N hours.

### GET /health
Returns `{"status": "ok"}` if running.

### Dashboard APIs
These endpoints power the dashboard UI.

### GET /dashboard/overview
Returns summary metrics, latest NEPSE value, sector snapshot, and top sources.

### GET /dashboard/latest-news
Returns latest scraped news for dashboard cards.

### GET /dashboard/nepse-history
Returns NEPSE time-series points for trend chart.

---

## Data Collection Plan
- Interval: every 30 minutes
- Duration: minimum 2 weeks
- Expected articles: ~400 per run (20 portals x 20 articles)
- Expected total: 20,000 to 30,000 articles over 2 weeks
