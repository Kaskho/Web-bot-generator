# generator_app.py
import os, io, zipfile, uuid, shutil, pathlib, json
from fastapi import FastAPI, File, UploadFile, Form
from fastapi.responses import StreamingResponse, JSONResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
import httpx
from typing import Optional
from datetime import datetime

BASE = pathlib.Path(__file__).parent
TEMPLATE_DIR = BASE / "templates"
TMP_DIR = BASE / "tmp"
os.makedirs(TMP_DIR, exist_ok=True)

env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "j2"])
)

app = FastAPI()

# Config via ENV
GROK_API_URL = os.environ.get("GROK_API_URL", "https://api.groq.ai/v1/chat/completions")
GROK_API_KEY = os.environ.get("GROK_API_KEY", "")
GROK_MODEL = os.environ.get("GROK_MODEL", "llama3-8b-8192")

def call_grok(narrative: str, task: str) -> str:
    """Call Grok; if not configured, return a simple fallback text."""
    if not GROK_API_KEY:
        return f"[GROK_NOT_CONFIGURED]\nTask: {task}\n\nNarrative:\n{narrative}"
    payload = {
        "model": GROK_MODEL,
        "messages": [
            {"role": "system", "content": "You are Grok: generate copy & JSON arrays for website and Telegram bot based on narrative."},
            {"role": "user", "content": f"Task: {task}\n\nNarrative:\n{narrative}"}
        ],
        "temperature": 0.25,
        "max_tokens": 1200
    }
    headers = {"Authorization": f"Bearer {GROK_API_KEY}", "Content-Type": "application/json"}
    with httpx.Client(timeout=30.0) as client:
        r = client.post(GROK_API_URL, json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
    # Attempt to parse typical choice content
    try:
        return data.get("choices", [])[0].get("message", {}).get("content", "")
    except Exception:
        return json.dumps(data)

def make_zip(folder_path: pathlib.Path) -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(folder_path):
            for f in files:
                full = os.path.join(root, f)
                arc = os.path.relpath(full, folder_path)
                zf.write(full, arc)
    buf.seek(0)
    return buf

@app.post("/generate")
async def generate(
    narrative: str = Form(...),
    coin_name: str = Form(...),
    ticker: str = Form(...),
    network: str = Form("Pump.fun"),
    x_url: Optional[str] = Form("https://x.com/"),
    telegram_url: Optional[str] = Form("https://t.me/"),
    pump_fun: Optional[str] = Form("https://pump.fun/"),
    file: Optional[UploadFile] = File(None)
):
    uid = str(uuid.uuid4())[:8]
    work = TMP_DIR / f"gen_{uid}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    # save uploaded media if any
    media_folder = work / "website" / "media"
    media_folder.mkdir(parents=True, exist_ok=True)
    media_filename = ""
    if file:
        ext = pathlib.Path(file.filename).suffix
        save_to = media_folder / f"media{ext}"
        content = await file.read()
        open(save_to, "wb").write(content)
        media_filename = f"media/{save_to.name}"

    # Use Grok to create website copy and bot texts
    site_copy = call_grok(narrative, "Generate: short tagline, intro paragraph, and roadmap in plain text")
    bot_json = call_grok(narrative, "Generate: JSON object with arrays: GREET_NEW_MEMBERS, HYPE, WISDOM, SCHEDULED_BUY, SCHEDULED_PUMP. Return valid JSON only.")
    # Try parse bot_json
    try:
        bot_texts = json.loads(bot_json.strip())
    except Exception:
        # Fallback: simple canned arrays
        bot_texts = {
            "GREET_NEW_MEMBERS": [f"Welcome to {coin_name}, fren! LFG!"],
            "HYPE": ["LFG! To the moon!"],
            "WISDOM": ["HODL and stay based."],
            "SCHEDULED_BUY": ["Buy the dip!"],
            "SCHEDULED_PUMP": ["PUMP IT!"]
        }

    # Render website template
    tpl = env.get_template("website_index.j2")
    index_html = tpl.render(
        coin_name=coin_name,
        ticker=ticker,
        network=network,
        tagline=(site_copy.splitlines()[0] if site_copy else ""),
        intro=site_copy,
        roadmap=site_copy,
        pump_fun=pump_fun,
        x_url=x_url,
        telegram_url=telegram_url,
        media_filename=media_filename
    )
    website_dir = work / "website"
    website_dir.mkdir(parents=True, exist_ok=True)
    (website_dir / "index.html").write_text(index_html, encoding="utf-8")
    # Add Dockerfile & requirements & render.yaml from templates
    for tname in ("dockerfile.j2", "requirements_bot.txt", "render_yaml.j2"):
        if (TEMPLATE_DIR / tname).exists():
            content = env.get_template(tname).render(service_name=f"{coin_name.lower().replace(' ','-')}-website")
            (website_dir / (tname.replace(".j2","").replace("_bot",""))).write_text(content, encoding="utf-8")

    # Create bot_main folder
    bot_main_dir = work / "bot_main"
    bot_main_dir.mkdir(parents=True, exist_ok=True)
    # config
    cfg = env.get_template("bot_config.j2").render()
    (bot_main_dir / "config.py").write_text(cfg, encoding="utf-8")
    # main.py (webhook server)
    (bot_main_dir / "main.py").write_text(env.get_template("bot_main_logic.j2").render(role="main"), encoding="utf-8")
    (bot_main_dir / "logic.py").write_text(env.get_template("bot_main_logic.j2").render(role="main_logic"), encoding="utf-8")
    (bot_main_dir / "Dockerfile").write_text(env.get_template("dockerfile.j2").render(), encoding="utf-8")
    (bot_main_dir / "requirements.txt").write_text(env.get_template("requirements_bot.txt").render(), encoding="utf-8")
    (bot_main_dir / "render.yaml").write_text(env.get_template("render_yaml.j2").render(service_name=f"{coin_name.lower().replace(' ','-')}-bot-main"), encoding="utf-8")
    (bot_main_dir / "bot_texts.json").write_text(json.dumps(bot_texts, ensure_ascii=False, indent=2), encoding="utf-8")

    # Create bot_sidekick folder (similar)
    bot_sk_dir = work / "bot_sidekick"
    bot_sk_dir.mkdir(parents=True, exist_ok=True)
    (bot_sk_dir / "config.py").write_text(cfg.replace("BOT_TOKEN","SIDEKICK_BOT_TOKEN").replace("WEBHOOK_BASE_URL","WEBHOOK_BASE_URL"), encoding="utf-8")
    (bot_sk_dir / "sidekick_main.py").write_text(env.get_template("bot_sidekick_logic.j2").render(), encoding="utf-8")
    (bot_sk_dir / "sidekick_logic.py").write_text(env.get_template("bot_sidekick_logic.j2").render(role="sidekick_logic"), encoding="utf-8")
    (bot_sk_dir / "Dockerfile").write_text(env.get_template("dockerfile.j2").render(), encoding="utf-8")
    (bot_sk_dir / "requirements.txt").write_text(env.get_template("requirements_bot.txt").render(), encoding="utf-8")
    (bot_sk_dir / "render.yaml").write_text(env.get_template("render_yaml.j2").render(service_name=f"{coin_name.lower().replace(' ','-')}-bot-sidekick"), encoding="utf-8")
    (bot_sk_dir / "bot_texts.json").write_text(json.dumps(bot_texts, ensure_ascii=False, indent=2), encoding="utf-8")

    # Zip
    zipbuf = make_zip(work)
    filename = f"generated_{coin_name}_{uid}.zip"
    headers = {"Content-Disposition": f"attachment; filename={filename}"}
    return StreamingResponse(zipbuf, media_type="application/zip", headers=headers)
