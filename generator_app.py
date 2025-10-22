# generator_app.py
import os, io, zipfile, uuid, shutil, json, pathlib
from fastapi import FastAPI, File, UploadFile, Form
from fastapi.responses import StreamingResponse, JSONResponse
from jinja2 import Template
import httpx
from typing import Optional
from datetime import datetime

app = FastAPI()

# ---------- Config ----------
GROK_API_URL = os.environ.get("GROK_API_URL", "https://api.groq.ai/v1/chat/completions")
GROK_API_KEY = os.environ.get("GROK_API_KEY", "")
GITHUB_PUSH_ENABLED = os.environ.get("GITHUB_PUSH_ENABLED", "false").lower() == "true"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

TMP_DIR = "/tmp/generator"
os.makedirs(TMP_DIR, exist_ok=True)

# ---------- Helper: call Grok ----------
def call_grok_system(narrative: str, task: str) -> str:
    """
    task: short description like "generate website copy", "generate bot responses"
    """
    if not GROK_API_KEY:
        # Fallback: simple heuristic
        return f"# GROK_NOT_CONFIGURED\n{task}\n\n{narrative}"
    headers = {"Authorization": f"Bearer {GROK_API_KEY}", "Content-Type":"application/json"}
    prompt = [
        {"role": "system", "content": "You are Grok: generate code-ready content for meme coin website & telegram bot."},
        {"role": "user", "content": f"Task: {task}\n\nNarrative:\n{narrative}"}
    ]
    payload = {"model":"llama3-8b-8192","messages":prompt, "temperature":0.2}
    try:
        r = httpx.post(GROK_API_URL, json=payload, headers=headers, timeout=30.0)
        r.raise_for_status()
        data = r.json()
        # NOTE: response parsing depends on Grok's schema. Here we attempt common fields:
        return data.get("choices", [{}])[0].get("message", {}).get("content", "") or json.dumps(data)
    except Exception as e:
        return f"# GROK_ERROR\n{str(e)}\n\n{task}\n\n{narrative}"

# ---------- Jinja templates (minimal examples) ----------
INDEX_HTML_TPL = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{{ coin_name }} — Launchpad</title>
  <meta name="description" content="{{ tagline }}">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <style>
    body{font-family:Inter,system-ui;display:flex;min-height:100vh;align-items:center;justify-content:center;background:#0b1020;color:#e6f2ff}
    .card{max-width:900px;padding:24px;border-radius:16px;background:rgba(255,255,255,0.04);box-shadow:0 6px 24px rgba(2,6,23,0.6)}
    h1{font-size:36px;margin-bottom:8px}
    p.lead{opacity:.9}
    .media{margin-top:16px}
    .links a{display:inline-block;margin-right:12px;background:#0f1724;padding:8px 12px;border-radius:8px;text-decoration:none;color:#9be7a1}
  </style>
</head>
<body>
  <div class="card">
    <h1>{{ coin_name }} <small>({{ ticker }})</small></h1>
    <p class="lead">{{ intro }}</p>
    <div class="media">
      {% if image_path %}
        <img src="{{ image_path }}" alt="hero" style="max-width:100%;border-radius:12px"/>
      {% endif %}
      {% if video_path %}
        <video controls style="max-width:100%;border-radius:12px"><source src="{{ video_path }}"></video>
      {% endif %}
    </div>
    <h3>Roadmap</h3>
    <pre>{{ roadmap }}</pre>
    <div class="links">
      <a href="{{ pump_fun }}">Buy on Pump.fun</a>
      <a href="{{ website_url }}">Website</a>
      <a href="{{ x_url }}">X</a>
      <a href="{{ telegram_url }}">Telegram</a>
    </div>
  </div>
</body>
</html>
"""

DOCKERFILE_PY = """FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python3","main.py"]
"""

RENDER_YAML_SERVICE = """services:
  - type: web
    name: {service_name}
    env: docker
    plan: free
    healthCheck:
      path: /health
"""

REQUIREMENTS_PY = "Flask==3.0.3\npyTelegramBotAPI==4.15.4\nhttpx==0.27.0\nwaitress==3.0.0\npsycopg2-binary==2.9.9\n"

# Bot templates (truncated, minimal but functional)
BOT_MAIN_PY = '''import os, logging, time
from flask import Flask, request, abort
import telebot
from logic import BotLogic
from config import Config
from waitress import serve
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
bot = telebot.TeleBot(Config.BOT_TOKEN(), threaded=False)
logic = BotLogic(bot)
@app.route(f'/{Config.BOT_TOKEN()}', methods=['POST'])
def webhook():
    if request.headers.get('content-type')=='application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return "OK",200
    else:
        abort(403)
@app.route('/health')
def health(): return "",204
if __name__=='__main__':
    try:
        bot.remove_webhook()
        bot.set_webhook(url=f"{Config.WEBHOOK_BASE_URL()}/{Config.BOT_TOKEN()}")
    except Exception as e:
        logging.error(e)
    serve(app, host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
'''

BOT_LOGIC_PY = '''import random, logging, time
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import Config
logging.basicConfig(level=logging.INFO)
class BotLogic:
    def __init__(self, bot):
        self.bot = bot
        self.coin_name = os.environ.get("COIN_NAME","NPEPE")
        self.ticker = os.environ.get("TICKER","NPEPE")
    def greet(self, message):
        txt = f"Welcome to {self.coin_name}! {self.ticker} — LFG!"
        self.bot.reply_to(message, txt)
'''

CONFIG_PY = '''import os
class Config:
    @staticmethod
    def BOT_TOKEN(): return os.environ.get("BOT_TOKEN")
    @staticmethod
    def WEBHOOK_BASE_URL(): return os.environ.get("WEBHOOK_BASE_URL","")
    @staticmethod
    def GROUP_CHAT_ID(): return os.environ.get("GROUP_CHAT_ID")
    @staticmethod
    def CONTRACT_ADDRESS(): return os.environ.get("CONTRACT_ADDRESS","")
    @staticmethod
    def PUMP_FUN_LINK(): return os.environ.get("PUMP_FUN_LINK","")
    @staticmethod
    def WEBSITE_URL(): return os.environ.get("WEBSITE_URL","")
    @staticmethod
    def TELEGRAM_URL(): return os.environ.get("TELEGRAM_URL","")
'''

# ---------- Generator core ----------
def render_website_files(context, outdir):
    (pathlib.Path(outdir)/"website").mkdir(parents=True, exist_ok=True)
    idx = Template(INDEX_HTML_TPL).render(**context)
    open(pathlib.Path(outdir)/"website"/"index.html","w",encoding="utf-8").write(idx)
    # copy media if provided
    if context.get("image_filename"):
        shutil.copy(context["image_filename"], pathlib.Path(outdir)/"website"/pathlib.Path(context["image_filename"]).name)

def render_bot_files(context, outdir, kind="main"):
    folder = pathlib.Path(outdir)/f"bot_{kind}"
    folder.mkdir(parents=True, exist_ok=True)
    open(folder/"Dockerfile","w").write(DOCKERFILE_PY)
    open(folder/"requirements.txt","w").write(REQUIREMENTS_PY)
    open(folder/"render.yaml","w").write(RENDER_YAML_SERVICE.format(service_name=f"npepe-{kind}"))
    open(folder/"config.py","w").write(CONFIG_PY)
    open(folder/"main.py","w").write(BOT_MAIN_PY)
    open(folder/"logic.py","w").write(BOT_LOGIC_PY)

def make_zip(source_dir):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(source_dir):
            for f in files:
                full = os.path.join(root, f)
                arc = os.path.relpath(full, source_dir)
                zf.write(full, arc)
    buf.seek(0)
    return buf

@app.post("/generate")
async def generate(
    narrative: str = Form(...),
    coin_name: str = Form("NEXTPEPE"),
    ticker: str = Form("NPEPE"),
    pump_fun: Optional[str] = Form("https://pump.fun/"),
    x_url: Optional[str] = Form("https://x.com/"),
    telegram_url: Optional[str] = Form("https://t.me/"),
    file: Optional[UploadFile] = File(None)
):
    uid = str(uuid.uuid4())[:8]
    work = pathlib.Path(TMP_DIR)/f"gen_{uid}"
    if work.exists(): shutil.rmtree(work)
    work.mkdir(parents=True)
    # Save upload if any
    image_path = None
    if file:
        ext = pathlib.Path(file.filename).suffix
        save_to = work / f"media{ext}"
        content = await file.read()
        open(save_to,"wb").write(content)
        image_path = str(save_to)
    # Use Grok to produce website copy and bot replies
    site_copy = call_grok_system(narrative, "generate website intro, tagline, roadmap (short) in plain text")
    bot_texts = call_grok_system(narrative, "generate arrays of bot short replies: GREET_NEW_MEMBERS, HYPE, WISDOM, SCHEDULED_BUY in JSON")
    # Context for templates
    context = {
        "coin_name": coin_name,
        "ticker": ticker,
        "tagline": site_copy.splitlines()[0] if site_copy else "",
        "intro": site_copy,
        "roadmap": site_copy,
        "pump_fun": pump_fun,
        "x_url": x_url,
        "telegram_url": telegram_url,
        "website_url": f"https://{coin_name.lower().replace(' ','-')}.example.app",
        "image_path": pathlib.Path(image_path).name if image_path else ""
    }
    # render
    render_website_files(context, str(work))
    render_bot_files(context, str(work), kind="main")
    render_bot_files(context, str(work), kind="sidekick")
    # write bot_texts as json for logic use
    open(pathlib.Path(work)/"bot_texts.json","w",encoding="utf-8").write(bot_texts)
    # zip
    z = make_zip(str(work))
    # optionally push to github: omitted here for security/complexity (can be added)
    return StreamingResponse(z, media_type="application/zip", headers={"Content-Disposition":f"attachment; filename=generated_{coin_name}_{uid}.zip"})
