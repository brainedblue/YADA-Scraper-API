# Yada scraper

built this because i needed to scrape sites that kept blocking me. started with just basic http requests but that only worked on like half the sites, so i kept adding more layers until it could handle most things.

## how it works

it tries 3 different approaches in order:
- first it tries a simple http request (fast, works on easy sites)
- if that gets blocked, it opens a real browser with fingerprint spoofing
- if that also fails, it goes full stealth mode — fake mouse movements, scrolling, the works

it also remembers which method worked for each site so it doesnt waste time next time.

## running it

```
pip install -r requirements.txt
playwright install chromium
python yada_scraper.py
```

go to `http://localhost:8000/docs` for the api docs

## api

```
GET /scrape?url=example.com          — scrape a url
GET /scrape/compare?url=example.com  — try all methods and compare
POST /scrape/bulk                    — scrape multiple urls
GET /memory                          — see what sites it remembers
GET /health                          — check if its running
```

## the anti-detection stuff

- tls fingerprint impersonation (curl_cffi)
- canvas/webgl/audio fingerprint spoofing
- realistic mouse movements using bezier curves
- random delays, scrolling, tracker blocking
- per-session browser identity (ua + headers + screen size all match)

theres also experimental captcha solving using gemini vision api but its not super reliable yet. you need a GEMINI_API_KEY in .env for that, the scraper works fine without it.
