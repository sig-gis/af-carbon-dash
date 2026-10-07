# Getting Started

## 1. Clone the repo

SSH: 
```
git clone git@github.com:sig-gis/af-carbon-dash.git
```

HTTPS:
```
git clone https://github.com/sig-gis/af-carbon-dash.git
```

## 2. Install `uv`
   
This app uses uv for dependency managment. 
[Read more about uv in the docs.](https://docs.astral.sh/uv/getting-started/) 

Install `uv`:

macOS/Linux
```
curl -LsSf https://astral.sh/uv/install.sh | sh
```

See the [uv installation docs for Windows installation instructions](https://docs.astral.sh/uv/getting-started/installation/#__tabbed_1_2)


### 2b. (Optional) Manually activate the `uv` environment

You can skip this if you prefer to use uv run in Step 3.

If you prefer a manually activated environment:

```
uv sync
source .venv/bin/activate
```

This creates and activates the .venv, syncing dependencies from pyproject.toml and uv.lock.

## 3. Prep data

The Makefile downloads the [FVS Variants shapefile](https://www.fs.usda.gov/fmsc/ftp/fvs/docs/overviews/FVSVariantMap20210525.zip) and simplifies it into a GeoJSON for efficiency. 

The Variants are automatically filtered to the line-separated list of supported FVS Variants in `conf/base/supported_variants.txt`

Simply run the Makefile to prep the data:

```
make
```


## 4. Run the streamlit app

### Option A (Recommended): Without Manual Activation

This is the simplest method. It will:

- Create .venv if needed
- Sync dependencies
- Run the app

```
uv run streamlit run carbon_dash.py
```

### Option B: With Activated Environment 

If you’ve activated the environment manually (see 2b):

```
streamlit run carbon_dash.py
```

---

## 5. Run the FastAPI service locally (optional)

If you want the dashboard to call a locally running API instead of Cloud Run, start the
FastAPI service in a separate terminal:

```
uv run uvicorn model_service.main:app --reload --port 8001
```

This starts the API at `http://127.0.0.1:8001`, which the dashboard will use by default
when no `CARBON_API_BASE_URL` is set.

---

## 6. Run the dashboard against a Cloud Run API

To point the dashboard at a hosted API, set `CARBON_API_BASE_URL` before starting
Streamlit.

**Linux:**
```
export CARBON_API_BASE_URL="https://YOUR-CLOUD-RUN-URL"
uv run streamlit run carbon_dash.py
```

**Windows PowerShell:**
```
$env:CARBON_API_BASE_URL = "https://YOUR-CLOUD-RUN-URL"
uv run streamlit run carbon_dash.py
```

The hosted API requires a key. The dashboard reads its own key from the model
store automatically (see below), so nothing else is needed when both services
share a store. To point at an API whose store you can't read, set
`CARBON_API_KEY` alongside the URL (env var or `.streamlit/secrets.toml`).

---

## 7. API authentication

The model service authenticates calling *systems* with static bearer keys; it
has no notion of users. Full details, including how an external system should
integrate, are in `model_service_documentation.md` under "Authentication".

**Nothing to set up.** Keys live in the model store as `api_keys.json`, next to
`registry.json`. Whichever process starts first (service or dashboard) creates
the file with one admin key for the dashboard client, and both then use it.
Locally with the default store that file is `./api_keys.json` (gitignored);
with MinIO or Cloud Storage it is an object in the bucket, so every deployment
of an environment reuses the same keys.

**Adding a client** (for example the American Forests dashboard): generate a
key, add an entry to `api_keys.json` in the store, and hand the key over. The
service picks up the change on the next request that presents the new key; no
redeploy. Removing a key takes effect within a minute.

```
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

```json
{
  "sig-dashboard": {"keys": ["<dashboard-key>"], "role": "admin"},
  "af-dashboard":  {"keys": ["<af-key>"], "role": "client"}
}
```

**Rotating a client:** add the new key to its `keys` list, let the client
switch over, then remove the old key.

**Overrides:** `CARBON_API_KEYS` (the same JSON as an env var) replaces the
store file entirely, for anyone who prefers Secret Manager. `CARBON_API_AUTH=off`
disables authentication outside production.
