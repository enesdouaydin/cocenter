# --- START OF FILE openrouter_api.py ---

import requests
import os
import json
from dotenv import load_dotenv
import logging

log = logging.getLogger(__name__)

# .env dosyasını yükle (ana scriptte zaten yüklenmiş olabilir)
load_dotenv()

class OpenRouterAPI:
    """OpenRouter API ile etkileşim kurmak için bir sınıf."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            log.error("OpenRouter API Anahtarı (OPENROUTER_API_KEY) bulunamadı.")
            raise ValueError("OPENROUTER_API_KEY bulunamadı. Lütfen .env dosyası oluşturun veya ortam değişkeni olarak ayarlayın.")

        self.api_url = os.getenv("OPENROUTER_API_URL", "https://openrouter.ai/api/v1/chat/completions")
        # Entity extraction için daha küçük ve hızlı bir model yeterli olabilir
        self.model = os.getenv("OPENROUTER_MODEL", "google/gemma-2-9b-it:free") # Veya başka uygun bir model
        # self.model = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct:free") # Alternatif

        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": os.getenv("APP_URL", "http://localhost"), # Uygulamanızın URL'si
            "X-Title": os.getenv("APP_TITLE", "Araba Chatbot") # Uygulamanızın adı
        }
        log.info(f"OpenRouter API başlatıldı. URL: {self.api_url}, Model: {self.model}")

    def send_request(self, messages: list, temperature: float = 0.0, max_tokens: int = 250) -> str:
        """OpenRouter API'ye mesaj listesi gönderir ve yanıtın metin içeriğini alır."""
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature, # Düşük temperature entity extraction için daha iyi
            "max_tokens": max_tokens,
            # JSON modu destekleyen modellerde kullanılabilir:
            # "response_format": {"type": "json_object"}
        }

        log.debug(f"Sending to OpenRouter ({self.model}): {json.dumps(payload, indent=2, ensure_ascii=False)}")
        try:
            response = requests.post(self.api_url, json=payload, headers=self.headers, timeout=30) # Timeout süresi
            response.raise_for_status()

            result = response.json()
            log.debug(f"Received from OpenRouter: {json.dumps(result, indent=2, ensure_ascii=False)}")

            if "choices" in result and result["choices"]:
                choice = result["choices"][0]
                if "message" in choice and "content" in choice["message"]:
                    content = choice["message"]["content"]
                    return content.strip() if content else "" # Boş string dönebilir
                else:
                    log.warning("API response missing 'message' or 'content'.")
                    return ""
            elif "error" in result and result["error"]:
                 error_msg = result["error"].get("message", "Unknown API error")
                 code = result["error"].get("code", "N/A")
                 log.error(f"OpenRouter API Error (Code: {code}): {error_msg}")
                 # Hata durumunda boş string dönmek, agent'ın bunu işlemesini sağlar
                 return ""
            else:
                log.error("OpenRouter API Error: Response missing 'choices' or 'error'.")
                return ""

        except requests.exceptions.Timeout:
            log.error("OpenRouter API Error: Request timed out.")
            return ""
        except requests.exceptions.HTTPError as http_err:
             log.error(f"OpenRouter API HTTP Error: {http_err.response.status_code} - {http_err.response.text}")
             return ""
        except requests.exceptions.RequestException as req_err:
            log.error(f"OpenRouter API Connection/Request Error: {req_err}")
            return ""
        except json.JSONDecodeError as json_err:
             # API'den gelen yanıt JSON değilse (nadiren olmalı)
             log.error(f"OpenRouter API Error (JSONDecodeError): Failed to parse JSON response - {json_err}. Raw Response: {response.text}")
             return "" # Boş string dön
        except Exception as e:
             log.exception("Unexpected error during OpenRouter API communication.")
             return ""

# --- END OF FILE openrouter_api.py ---