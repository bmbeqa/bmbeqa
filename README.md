# jobs.ge Scraper + API

## სისტემა
```
scraper.py  → jobs.ge-ს ყველა გვერდი პარსავს → SQLite
api.py      → FastAPI სერვერი
main.py     → Uvicorn + APScheduler (60 წუთი)
```

## Railway-ზე განთავსება

### 1. GitHub-ზე ატვირთვა
```bash
git init
git add .
git commit -m "jobs.ge scraper"
git remote add origin https://github.com/შენი-username/jobs-ge-scraper.git
git push -u origin main
```

### 2. Railway.app
1. railway.app → New Project → Deploy from GitHub
2. ირჩევ repo-ს
3. Deploy! Railway თავად ამოიცნობს `railway.json`

### 3. URL
Railway გაძლევს URL-ს სახით: `https://xxx.railway.app`

## API Endpoints

| Endpoint | აღწერა |
|----------|---------|
| `GET /api/jobs` | ვაკანსიების სია |
| `GET /api/stats` | სტატისტიკა |
| `POST /api/scrape` | ხელით გაშვება |
| `GET /api/health` | სერვერის სტატუსი |

## /api/jobs პარამეტრები
- `q` — საძიებო სიტყვა
- `category` — კატეგორია
- `location` — ადგილი
- `salary=true` — მხოლოდ ხელფასიანი
- `vip=true` — მხოლოდ VIP
- `sort` — `new` / `deadline` / `salary` / `vip`
- `page`, `per_page`

## Artifact-ის კონფიგურაცია
Artifact-ში შეცვალე `API_BASE`:
```js
const API_BASE = "https://შენი-სახელი.railway.app";
```
