# 🚀 Getting Started

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

## 3. Run the streamlit app

### ✅ Option A (Recommended): Without Manual Activation

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
