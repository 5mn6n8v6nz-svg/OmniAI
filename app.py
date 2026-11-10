import os
import time
from collections import defaultdict
from flask import Flask, request, jsonify, render_template
import requests

app = Flask(__name__)

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL = os.environ.get("MODEL", "claude-haiku-4-5")
MAX_TOKENS = 4096
MAX_MESSAGES = 30            # عدد الرسائل اللي يرسلها الخادم للنموذج
MAX_INPUT_CHARS = 8000       # أقصى طول للرسالة الواحدة
RATE_LIMIT = 20              # أقصى عدد طلبات لكل IP في الدقيقة

_hits = defaultdict(list)

SYSTEM_BASE = (
    "أنت مساعد ذكي اسمه OmniAI. جاوب باللغة التي يكتب بها المستخدم، "
    "وكن واضحاً ومفيداً. ضع الكود داخل كتل markdown مع تحديد اللغة."
)


def rate_limited(ip):
    now = time.time()
    _hits[ip] = [t for t in _hits[ip] if now - t < 60]
    if len(_hits[ip]) >= RATE_LIMIT:
        return True
    _hits[ip].append(now)
    return False


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/chat", methods=["POST"])
def chat():
    if not API_KEY:
        return jsonify(error="لم يتم ضبط ANTHROPIC_API_KEY على الخادم."), 500

    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
    if rate_limited(ip):
        return jsonify(error="طلبات كثيرة، انتظر دقيقة وحاول مرة ثانية."), 429

    data = request.get_json(silent=True) or {}
    memory = str(data.get("memory", ""))[:2000]

    clean = []
    for m in data.get("messages", [])[-MAX_MESSAGES:]:
        role = m.get("role")
        content = str(m.get("content", ""))[:MAX_INPUT_CHARS]
        if role in ("user", "assistant") and content.strip():
            clean.append({"role": role, "content": content})

    if not clean or clean[-1]["role"] != "user":
        return jsonify(error="أرسل رسالة أولاً."), 400

    system = SYSTEM_BASE + f"\nالتاريخ الحالي: {time.strftime('%Y-%m-%d %H:%M')} (UTC)"
    if memory.strip():
        system += "\n\nمعلومات محفوظة عن المستخدم:\n" + memory

    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": MODEL,
                "max_tokens": MAX_TOKENS,
                "system": system,
                "messages": clean,
            },
            timeout=90,
        )
    except requests.RequestException:
        return jsonify(error="تعذّر الاتصال بالنموذج، حاول مرة ثانية."), 502

    try:
        body = r.json()
    except ValueError:
        body = {}

    if r.status_code != 200:
        msg = body.get("error", {}).get("message", "خطأ غير معروف من الخادم.")
        return jsonify(error=msg), r.status_code

    answer = "".join(
        b.get("text", "") for b in body.get("content", []) if b.get("type") == "text"
    ).strip()
    return jsonify(answer=answer or "(رد فارغ)")


if __name__ == "__main__":
    app.run(debug=True)
