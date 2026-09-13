# Frontend (Next.js PWA)

Optional **local development** operator UI.

**Production on Railway** currently serves the mobile operator PWA from the FastAPI backend (`backend/app/static/`) so the Metal/Node builder is not required. Open the API public URL (e.g. `https://api-production-22f23.up.railway.app/`).

Use this Next.js app when developing against a local API:

```bash
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

Do not deploy this `frontend/` service on Railway until the Docker/Nixpacks build is reliable again.
