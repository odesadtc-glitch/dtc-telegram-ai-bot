import os
import logging
from datetime import datetime

from fastapi import FastAPI, Request, HTTPException
from openai import AsyncOpenAI
import httpx

logging.basicConfig(level=logging.INFO)

app = FastAPI()

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
PUBLIC_URL = os.environ["PUBLIC_URL"].rstrip("/")
WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"]
ADMIN_CHAT_ID = os.environ["ADMIN_CHAT_ID"]

OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.6")

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# Тимчасове зберігання стану діалогу.
# Для першої версії цього достатньо.
user_states = {}


SYSTEM_PROMPT = """
Ти — AI-адміністратор Автошколи DTC – Одеса.

Твоя задача — ввічливо та зрозуміло консультувати клієнтів
і допомагати їм записатися на навчання.

ІНФОРМАЦІЯ ПРО DTC:

Автошкола: DTC – Одеса

Адреса:
м. Одеса, вул. Базарна, 73

Сайт:
https://dtc.od.ua/

Телефони:
+38 (050) 708 08 78
+38 (095) 228 23 10

Email:
odesa.dtc@gmail.com

НАПРЯМКИ НАВЧАННЯ:

Теорія:
- онлайн та офлайн навчання.

Практичні заняття:
- АКПП та МКПП.
- Пакет БАЗОВИЙ — 40 академічних годин — 26 000 грн.

Додаткові заняття:
- 5 занять по 90 хв — 6 500 грн.
- 10 занять по 90 хв — 13 000 грн.
- 1 заняття 90 хв — 1 400 грн.

Також можливі:
- підготовка до практичного іспиту;
- відпрацювання маршрутів;
- паркування;
- маневрування;
- додаткове водіння.

ПРАВИЛА:

1. Не вигадуй ціни, акції, дати або розклад.
2. Якщо актуальної інформації немає — скажи, що її потрібно уточнити.
3. Не вигадуй юридичні вимоги.
4. Відповідай українською мовою.
5. Відповіді мають бути короткими та зрозумілими.
6. Не вигадуй наявність місць у групах.
7. Якщо клієнт хоче записатися, використовуй команду /signup
   або запропонуй натиснути кнопку «Записатися».
8. Якщо клієнт хоче поговорити з менеджером —
   дай телефони DTC.
"""


async def telegram_request(method, data):
    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/{method}"
    )

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(url, json=data)
        response.raise_for_status()
        return response.json()


async def ask_ai(user_message):
    response = await openai_client.responses.create(
        model=OPENAI_MODEL,
        instructions=SYSTEM_PROMPT,
        input=user_message,
    )

    return response.output_text.strip()


async def send_admin_lead(lead):
    message = (
        "🔔 <b>НОВА ЗАЯВКА DTC</b>\n\n"
        f"👤 <b>Ім'я:</b> {lead['name']}\n"
        f"📞 <b>Телефон:</b> {lead['phone']}\n"
        f"🚗 <b>Напрямок:</b> {lead['service']}\n"
    )

    if lead.get("transmission"):
        message += (
            f"⚙️ <b>КПП:</b> {lead['transmission']}\n"
        )

    message += (
        f"🕐 <b>Час:</b> {lead['time']}\n"
        f"🆔 <b>Telegram ID:</b> {lead['chat_id']}"
    )

    await telegram_request(
        "sendMessage",
        {
            "chat_id": ADMIN_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
        }
    )


async def process_signup(chat_id, text):
    state = user_states.get(chat_id)

    if not state:
        user_states[chat_id] = {
            "step": "name",
            "name": None,
            "phone": None,
            "service": None,
            "transmission": None,
        }

        return (
            "Із задоволенням допоможу із записом 😊\n\n"
            "Як вас звати?"
        )

    step = state["step"]

    if step == "name":
        state["name"] = text.strip()
        state["step"] = "phone"

        return (
            f"Дякую, {state['name']}! 👍\n\n"
            "Вкажіть, будь ласка, ваш номер телефону."
        )

    if step == "phone":
        state["phone"] = text.strip()
        state["step"] = "service"

        return (
            "Що вас цікавить?\n\n"
            "1️⃣ Теорія\n"
            "2️⃣ Практичні заняття\n\n"
            "Напишіть «теорія» або «практика»."
        )

    if step == "service":
        normalized = text.lower().strip()

        if "теор" in normalized:
            state["service"] = "Теорія"
            state["step"] = "complete"

        elif "практ" in normalized:
            state["service"] = "Практичні заняття"
            state["step"] = "transmission"

            return (
                "Чудово 🚗\n\n"
                "На якій коробці передач плануєте навчатися?\n\n"
                "🔵 АКПП\n"
                "⚙️ МКПП"
            )

        else:
            return (
                "Будь ласка, напишіть:\n"
                "«теорія» або «практика»."
            )

    if step == "transmission":
        normalized = text.lower().strip()

        if "акпп" in normalized or "автомат" in normalized:
            state["transmission"] = "АКПП"
        elif "мкпп" in normalized or "механ" in normalized:
            state["transmission"] = "МКПП"
        else:
            return (
                "Будь ласка, оберіть:\n"
                "🔵 АКПП\n"
                "⚙️ МКПП"
            )

        state["step"] = "complete"

    if state["step"] == "complete":

        lead = {
            "name": state["name"],
            "phone": state["phone"],
            "service": state["service"],
            "transmission": state["transmission"],
            "time": datetime.now().strftime("%d.%m.%Y %H:%M"),
            "chat_id": chat_id,
        }

        await send_admin_lead(lead)

        del user_states[chat_id]

        return (
            "Дякуємо! ✅\n\n"
            "Вашу заявку передано адміністратору "
            "Автошколи DTC – Одеса.\n\n"
            "Ми зв'яжемося з вами найближчим часом. 🚗"
        )

    return "Дякую! Заявку отримано."


@app.get("/")
async def health():
    return {
        "status": "ok",
        "service": "DTC Telegram AI Bot"
    }


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):

    secret = request.headers.get(
        "X-Telegram-Bot-Api-Secret-Token"
    )

    if secret != WEBHOOK_SECRET:
        raise HTTPException(
            status_code=403,
            detail="Forbidden"
        )

    update = await request.json()

    message = update.get("message", {})

    if not message:
        return {"ok": True}

    chat = message.get("chat", {})
    text = message.get("text")

    if not chat or not text:
        return {"ok": True}

    chat_id = chat["id"]

    try:

        if text.startswith("/start"):

            user_states.pop(chat_id, None)

            reply = (
                "Вітаємо в Автошколі DTC – Одеса! 🚗\n\n"
                "Я AI-адміністратор DTC.\n\n"
                "Можу розповісти про теорію, практику, "
                "ціни та допомогти із записом.\n\n"
                "Напишіть своє питання або натисніть "
                "«Записатися»."
            )

        elif text.lower().strip() in [
            "записатися",
            "записатись",
            "/signup"
        ]:

            reply = await process_signup(
                chat_id,
                ""
            )

        elif chat_id in user_states:

            reply = await process_signup(
                chat_id,
                text
            )

        else:

            reply = await ask_ai(text)

        await telegram_request(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": reply,
                "disable_web_page_preview": True
            }
        )

    except Exception:

        logging.exception(
            "Error while processing message"
        )

        await telegram_request(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": (
                    "Перепрошую, зараз виникла технічна "
                    "помилка. Будь ласка, зателефонуйте "
                    "до DTC: +38 (050) 708 08 78."
                )
            }
        )

    return {"ok": True}
