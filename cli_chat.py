# --- START OF FILE cli_chat.py ---

import sys
import os
from dotenv import load_dotenv
from database import SessionLocal, create_db_tables
from models import Base, CustomerLead # CustomerLead import edildi
# db_utils import etmeye gerek yok, agent içinden kullanılıyor ama get_random_customer_lead lazım.
from db_utils import get_random_customer_lead
from openrouter_api import OpenRouterAPI
from agent import AIAgent
import logging

# Setup logging
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=log_level,
                    format='%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
                    handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger(__name__)

def run_interactive_chat():
    """Starts and manages the interactive command-line chat session, potentially starting proactively."""

    load_dotenv()
    log.info(".env file loaded (if present).")
    log.info(f"Log level set to: {log_level}")

    db = None
    try:
        log.info("Creating OpenRouter API client...")
        openrouter_client = OpenRouterAPI()
        log.info("OpenRouter API client created.")

        log.info("Checking/creating database tables...")
        create_db_tables() # Bu CustomerLead tablosunu da oluşturmalı
        log.info("Database tables check/creation complete.")

        log.info("Creating database session...")
        db = SessionLocal()
        if not db:
             log.critical("Failed to create database session.")
             raise ConnectionError("Veritabanı oturumu oluşturulamadı.")
        log.info("Database session opened successfully.")

        log.info("Initializing AI Agent (Rule-Based)...")
        agent = AIAgent(db=db, openrouter=openrouter_client)
        log.info("AI Agent initialized.")

        print("\n------------------------------------------")
        print("  Araba Merkezi - AI Satış Danışmanı")
        print("------------------------------------------")

        # --- PROAKTİF BAŞLANGIÇ ---
        initial_message = None
        try:
            # Rastgele bir müşteri adayı seçmeyi dene
            customer_to_greet = get_random_customer_lead(db)

            if customer_to_greet:
                print("(Veritabanından rastgele bir müşteri adayı seçildi...)")
                # Agent'a proaktif mesajı oluşturmasını söyle
                initial_message = agent.generate_proactive_start_message(customer_to_greet)
            else:
                # Müşteri bulunamazsa veya DB boşsa, standart karşılama
                print("(Veritabanında müşteri adayı bulunamadı, standart karşılama yapılıyor.)")
                initial_message = agent.RESPONSE_TEMPLATES["greeting"]
                # Agent context'ini sıfırla (generate_proactive_start_message zaten yapıyor ama emin olalım)
                agent._reset_context()
                agent.current_context['last_response'] = initial_message # Standart selamlamayı da loglamak için
                agent._log_query_db("<<INITIAL_GREETING>>", initial_message)


        except Exception as proactive_err:
             log.error(f"Error during proactive start: {proactive_err}", exc_info=True)
             print("\n!!! Başlangıçta bir hata oluştu, standart modda devam ediliyor.", file=sys.stderr)
             initial_message = agent.RESPONSE_TEMPLATES["greeting"]
             agent._reset_context() # Hata durumunda context'i sıfırla
             agent.current_context['last_response'] = initial_message
             agent._log_query_db("<<PROACTIVE_ERROR>>", initial_message)


        # Oluşturulan ilk mesajı yazdır
        print(f"Temsilci : {initial_message}")
        print("------------------------------------------\n")
        print("(Yanıtınızı yazabilirsiniz. Çıkmak için 'çıkış', sıfırlamak için 'reset')")

        # --- Ana Sohbet Döngüsü ---
        while True:
            try:
                user_input = input("Siz      : ").strip()
                if not user_input:
                    continue
            except (EOFError, KeyboardInterrupt):
                 print("\n\nTemsilci: Görüşme sonlandırıldı. İyi günler!")
                 break

            if user_input.lower() in ["çıkış", "exit", "quit"]:
                # Agent'a veda mesajı ürettirebiliriz (opsiyonel)
                farewell_msg = agent.process_message("<<<FAREWELL_TRIGGER>>>") # Özel bir tetikleyici
                # process_message zaten farewell'i handle etmeli, bu yüzden direkt break yeterli olabilir.
                # print(f"Temsilci: {farewell_msg}") # Yerine agent'ın ürettiği son mesajı yazdıralım
                print(f"\nTemsilci: {agent.current_context.get('last_response', 'Görüşürüz!')}")
                break

            # Mesajı agent ile işle (process_message artık kullanıcıdan gelen mesajları işleyecek)
            try:
                log.debug(f"Processing user input: '{user_input}'")
                response = agent.process_message(user_input)
                print(f"Temsilci : {response}")
            except Exception as processing_error:
                log.exception("Critical error during agent.process_message:")
                print(f"\nHATA: Mesajınız işlenirken beklenmedik bir sorun oluştu: {processing_error}", file=sys.stderr)
                print(f"Temsilci : {agent.RESPONSE_TEMPLATES['error_fallback']}")

    # --- Hata Yakalama ve Kapatma Bloğu ... (Mevcut kod) ---
    except ValueError as config_err:
        log.error(f"Configuration Error: {config_err}", exc_info=True)
        print(f"\nYapılandırma Hatası: {config_err}", file=sys.stderr)
    except ConnectionError as db_conn_err:
        log.critical(f"Database Connection Error: {db_conn_err}", exc_info=True)
        print(f"\nVeritabanı Bağlantı Hatası: {db_conn_err}", file=sys.stderr)
    except Exception as startup_err:
        log.critical(f"Application failed to start: {startup_err}", exc_info=True)
        print(f"\nKritik Başlangıç Hatası: {startup_err}", file=sys.stderr)
    finally:
        if db:
            try:
                db.close()
                log.info("Database session closed.")
                print("\n(Veritabanı bağlantısı kapatıldı)")
            except Exception as db_close_err:
                 log.error(f"Error closing database session: {db_close_err}", exc_info=True)

if __name__ == "__main__":
    run_interactive_chat()

# --- END OF FILE cli_chat.py ---