"""Vision-LLM document analysis (Google Gemini, OpenAI, Anthropic Claude).

The page image is sent to the selected provider, which returns the page text
and its tables as JSON. Uses plain HTTPS so no vendor SDK is bundled.
"""

from __future__ import annotations

import base64
import io
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from PIL import Image


@dataclass(frozen=True)
class Provider:
    key: str
    name: str
    default_model: str
    key_url: str


PROVIDERS: dict[str, Provider] = {
    p.key: p
    for p in (
        Provider("gemini", "Google Gemini", "gemini-2.5-flash", "https://aistudio.google.com/apikey"),
        Provider("openai", "OpenAI (GPT)", "gpt-4.1", "https://platform.openai.com/api-keys"),
        Provider("anthropic", "Anthropic Claude", "claude-sonnet-4-5",
                 "https://console.anthropic.com/settings/keys"),
    )
}


@dataclass
class AiSettings:
    provider: str = "gemini"
    api_key: str = ""
    model: str = ""

    @property
    def model_name(self) -> str:
        return self.model.strip() or PROVIDERS[self.provider].default_model

    @property
    def configured(self) -> bool:
        return bool(self.api_key.strip()) and self.provider in PROVIDERS


@dataclass
class AiPageResult:
    text: str = ""
    tables: list[list[list[str]]] = field(default_factory=list)
    titles: list[str] = field(default_factory=list)


class AiError(RuntimeError):
    pass


PROMPT = """Sen uzman bir belge sayısallaştırma asistanısın. Ekteki taranmış belge sayfasını dikkatle incele ve içeriğini olabildiğince doğru biçimde çıkar.

Kurallar:
- Yalnızca görüntüde gerçekten yazanı aktar; asla tahmin etme veya uydurma. Okunamayan hücreyi boş bırak.
- Türkçe karakterleri (ç, ğ, ı, İ, ö, ş, ü) doğru kullan.
- Sayıları, tarihleri ve para birimlerini görüntüdeki biçimiyle aynen yaz (ör. 1.250,75 veya 03.11.2026).
- "text": Tablolar dışındaki tüm metin, okuma sırasıyla. Paragrafları boş bir satırla ayır. Tablo içeriğini buraya yazma.
- "tables": Sayfadaki her tablo için bir nesne. "rows" satırların listesidir, her satır hücre metinlerinin listesidir.
  Tüm satırlar aynı sayıda hücre içermeli. Başlık satırı(ları) varsa ilk satır(lar) olarak koru.
  Birleştirilmiş hücrelerin değerini sol üstteki hücreye yaz, kapsadığı diğer hücreleri boş bırak.
  Çizgisiz ama sütunlu düzenleri (fatura kalemleri, listeler) de tablo olarak çıkar.
- Tablo yoksa "tables" boş liste olsun.

Yalnızca şu biçimde geçerli JSON döndür, başka hiçbir şey yazma:
{"text": "...", "tables": [{"title": "tablo başlığı veya boş", "rows": [["hücre", "hücre"], ["...", "..."]]}]}"""

TIMEOUT = 180


def _encode(img: Image.Image, max_side: int = 2200) -> str:
    img = img.convert("RGB") if img.mode not in ("RGB", "L") else img
    scale = max_side / max(img.size)
    if scale < 1:
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _post(url: str, headers: dict[str, str], body: dict) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            err = json.loads(detail)
            detail = (err.get("error") or {}).get("message") or detail
        except (ValueError, AttributeError):
            pass
        hints = {
            400: "İstek reddedildi (model adı veya API anahtarı hatalı olabilir).",
            401: "API anahtarı geçersiz.",
            403: "API anahtarının bu modele erişim izni yok.",
            404: "Model bulunamadı. Ayarlar'dan model adını kontrol edin.",
            429: "Kullanım kotası aşıldı veya çok sık istek gönderildi. Biraz bekleyip tekrar deneyin.",
        }
        raise AiError(f"{hints.get(exc.code, f'HTTP {exc.code}')}\n{detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise AiError(f"Yapay zekâ servisine bağlanılamadı: {exc.reason}") from exc
    except TimeoutError as exc:
        raise AiError("Yapay zekâ servisi zamanında yanıt vermedi.") from exc


def _ask(settings: AiSettings, prompt: str, image_b64: str | None, json_mode: bool = True) -> str:
    model = settings.model_name
    key = settings.api_key.strip()
    if settings.provider == "gemini":
        parts: list[dict] = [{"text": prompt}]
        if image_b64:
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": image_b64}})
        body: dict = {"contents": [{"role": "user", "parts": parts}],
                      "generationConfig": {"temperature": 0}}
        if json_mode:
            body["generationConfig"]["responseMimeType"] = "application/json"
        resp = _post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            {"x-goog-api-key": key}, body,
        )
        try:
            return "".join(p.get("text", "") for p in resp["candidates"][0]["content"]["parts"])
        except (KeyError, IndexError) as exc:
            reason = (resp.get("promptFeedback") or {}).get("blockReason") or resp
            raise AiError(f"Gemini yanıt üretmedi: {reason}") from exc
    if settings.provider == "openai":
        content: list[dict] = [{"type": "text", "text": prompt}]
        if image_b64:
            content.append({"type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{image_b64}", "detail": "high"}})
        body = {"model": model, "messages": [{"role": "user", "content": content}]}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        resp = _post("https://api.openai.com/v1/chat/completions",
                     {"Authorization": f"Bearer {key}"}, body)
        try:
            return resp["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError) as exc:
            raise AiError(f"OpenAI beklenmeyen yanıt: {resp}") from exc
    if settings.provider == "anthropic":
        content = []
        if image_b64:
            content.append({"type": "image",
                            "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}})
        content.append({"type": "text", "text": prompt})
        body = {"model": model, "max_tokens": 16000, "messages": [{"role": "user", "content": content}]}
        resp = _post("https://api.anthropic.com/v1/messages",
                     {"x-api-key": key, "anthropic-version": "2023-06-01"}, body)
        try:
            return "".join(b.get("text", "") for b in resp["content"] if b.get("type") == "text")
        except (KeyError, TypeError) as exc:
            raise AiError(f"Claude beklenmeyen yanıt: {resp}") from exc
    raise AiError(f"Bilinmeyen yapay zekâ servisi: {settings.provider}")


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
    if fence:
        raw = fence.group(1).strip()
    try:
        return json.loads(raw)
    except ValueError:
        start, end = raw.find("{"), raw.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(raw[start : end + 1])
            except ValueError:
                pass
    raise AiError("Yapay zekâ yanıtı okunamadı (geçersiz JSON).")


def _clean_rows(rows) -> list[list[str]]:
    if not isinstance(rows, list):
        return []
    cleaned = [
        [("" if v is None else str(v)).strip() for v in row] if isinstance(row, list) else [str(row)]
        for row in rows
    ]
    cleaned = [r for r in cleaned if any(r)]
    width = max((len(r) for r in cleaned), default=0)
    return [r + [""] * (width - len(r)) for r in cleaned]


def analyze_page(img: Image.Image, settings: AiSettings) -> AiPageResult:
    if not settings.configured:
        raise AiError("Yapay zekâ ayarlanmamış. Ayarlar > Yapay Zekâ bölümüne API anahtarınızı girin.")
    data = _parse_json(_ask(settings, PROMPT, _encode(img)))
    result = AiPageResult(text=str(data.get("text") or "").strip())
    for table in data.get("tables") or []:
        if isinstance(table, dict):
            rows, title = _clean_rows(table.get("rows")), str(table.get("title") or "")
        else:
            rows, title = _clean_rows(table), ""
        if rows and len(rows[0]) > 0:
            result.tables.append(rows)
            result.titles.append(title)
    return result


def test_connection(settings: AiSettings) -> str:
    """Send a tiny text-only request; return the model's reply."""
    if not settings.configured:
        raise AiError("API anahtarı girilmedi.")
    reply = _ask(settings, 'Sadece {"ok": true} JSON nesnesini döndür.', None)
    return reply.strip()[:200]
