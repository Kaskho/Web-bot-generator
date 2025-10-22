import os, io, zipfile, uuid, shutil, pathlib, json
from fastapi import FastAPI, File, UploadFile, Form, Request
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Template
import httpx

BASE = pathlib.Path(__file__).parent
TEMPLATE_DIR = BASE / "templates"
TMP_DIR = BASE / "tmp"
STATIC_DIR = BASE / "static"
os.makedirs(TMP_DIR, exist_ok=True)

app = FastAPI(title="Meme Coin Generator")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

GROK_API_URL = os.environ.get("GROK_API_URL", "https://api.groq.ai/v1/chat/completions")
GROK_API_KEY = os.environ.get("GROK_API_KEY", "")
GROK_MODEL = os.environ.get("GROK_MODEL", "llama3-8b-8192")

# --- Helper: panggil Grok
def call_grok(narrative: str, task: str) -> str:
    if not GROK_API_KEY:
        return f"[GROK_DISABLED]\n{narrative}"
    payload = {
        "model": GROK_MODEL,
        "messages": [
            {"role": "system", "content": "You are Grok: generate creative website and bot code for meme coins."},
            {"role": "user", "content": f"Task: {task}\n\nNarrative:\n{narrative}"}
        ],
        "temperature": 0.3,
        "max_tokens": 1200
    }
    headers = {"Authorization": f"Bearer {GROK_API_KEY}", "Content-Type": "application/json"}
    with httpx.Client(timeout=30.0) as client:
        r = client.post(GROK_API_URL, json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
        return data.get("choices", [{}])[0].get("message", {}).get("content", "")

# --- Homepage form
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("ui.html", {"request": request})

# --- Generate ZIP project
@app.post("/generate")
async def generate(
    request: Request,
    narrative: str = Form(...),
    coin_name: str = Form(...),
    ticker: str = Form(...),
    network: str = Form("Pump.fun"),
    x_url: str = Form("https://x.com/"),
    telegram_url: str = Form("https://t.me/"),
    pump_fun: str = Form("https://pump.fun/"),
    file: UploadFile = File(None)
):
    uid = str(uuid.uuid4())[:8]
    work = TMP_DIR / f"gen_{uid}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    # save media
    media_path = ""
    if file:
        ext = pathlib.Path(file.filename).suffix
        save_to = work / f"media{ext}"
        content = await file.read()
        open(save_to, "wb").write(content)
        media_path = save_to.name

    # AI content
    site_copy = call_grok(narrative, "Generate website tagline, intro, roadmap (plain text)")
    bot_json = call_grok(narrative, "Generate JSON with arrays for bot responses")
    try:
        bot_texts = json.loads(bot_json)
    except Exception:
        bot_texts = {"HYPE": ["LFG!"], "WISDOM": ["In chaos we trust."]}

    # render website HTML
    tpl = (TEMPLATE_DIR / "website_index.j2").read_text()
    html = Template(tpl).render(
        coin_name=coin_name,
        ticker=ticker,
        network=network,
        tagline=site_copy.splitlines()[0] if site_copy else "",
        intro=site_copy,
        roadmap=site_copy,
        pump_fun=pump_fun,
        x_url=x_url,
        telegram_url=telegram_url,
        media_filename=media_path
    )
    (work / "index.html").write_text(html, encoding="utf-8")
    (work / "bot_texts.json").write_text(json.dumps(bot_texts, indent=2), encoding="utf-8")

    # zip hasil
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(work):
            for f in files:
                full = os.path.join(root, f)
                arc = os.path.relpath(full, work)
                zf.write(full, arc)
    buf.seek(0)
    headers = {"Content-Disposition": f"attachment; filename={coin_name}_{uid}.zip"}
    return StreamingResponse(buf, media_type="application/zip", headers=headers)

# --- Preview website langsung
@app.post("/preview", response_class=HTMLResponse)
async def preview(
    request: Request,
    narrative: str = Form(...),
    coin_name: str = Form(...),
    ticker: str = Form(...),
    network: str = Form("Pump.fun"),
    x_url: str = Form("https://x.com/"),
    telegram_url: str = Form("https://t.me/"),
    pump_fun: str = Form("https://pump.fun/"),
    file: UploadFile = File(None)
):
    uid = str(uuid.uuid4())[:8]
    work = TMP_DIR / f"preview_{uid}"
    work.mkdir(parents=True, exist_ok=True)

    media_filename = ""
    if file:
        ext = pathlib.Path(file.filename).suffix
        save_to = work / f"media{ext}"
        content = await file.read()
        open(save_to, "wb").write(content)
        media_filename = save_to.name

    # AI content
    site_copy = call_grok(narrative, "Generate website tagline, intro, roadmap (plain text)")

    tpl = (TEMPLATE_DIR / "website_index.j2").read_text()
    html = Template(tpl).render(
        coin_name=coin_name,
        ticker=ticker,
        network=network,
        tagline=site_copy.splitlines()[0] if site_copy else "",
        intro=site_copy,
        roadmap=site_copy,
        pump_fun=pump_fun,
        x_url=x_url,
        telegram_url=telegram_url,
        media_filename=media_filename
    )

    return HTMLResponse(html)
