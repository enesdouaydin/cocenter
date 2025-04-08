# --- START OF FILE agent.py ---

import json
import re
from datetime import datetime
from sqlalchemy.orm import Session
from models import UserQuery, Car, CustomerLead # CustomerLead modelini import et
# Import necessary functions from db_utils
from db_utils import (
    get_distinct_brands, find_cars_by_criteria, find_customer_lead_by_phone,
    get_distinct_models, get_random_customer_lead, find_similar_priced_cars # find_similar_priced_cars eklendi
)
from openrouter_api import OpenRouterAPI
# --- UPDATED Memory Imports ---
from memory_utils import MemoryManager, MemoryVerifier # Import from the combined file
# --- END Memory Imports ---
from typing import Dict, Optional, Any, List
import logging
import decimal

log = logging.getLogger(__name__)

class AIAgent:
    """
    Rule-based dialogue agent acting as a customer representative.
    Uses consistent internal naming based on DB model fields.
    LLM *only* for entity extraction, potentially enhanced by short-term memory.
    Flow managed by Python logic, including proactive personalized greeting, similarity search,
    and model clarification when brand is missing. Allows searching on single specific criteria.
    Includes Turkish value mapping and shortening in normalization.
    Prioritizes specific filters over 'list all' requests.
    Suggests alternative models after showing results.
    Includes short-term conversation memory.
    """

    # --- Configuration and Templates (CLASS LEVEL) ---
    FILTER_QUESTIONS = {
        # Field Name (Model): (Question Template, Context Key for Asked Flag, Priority)
        "brand": ("Özellikle ilgilendiğiniz bir marka var mı? (Mevcut markalarımız: {available_brands})", "asked_brand", 1),
        "engine_type": ("Anladım. Peki motor tipi tercihiniz nedir? (Elektrik, Dizel, Benzin, Hibrit vb.)", "asked_engine", 2),
        "body_type": ("Ne tür bir gövde tipi düşünüyorsunuz? (SUV, Sedan, Hatchback vb.)", "asked_body", 3),
        "price_range": ("Bütçe aralığınızı öğrenebilir miyim? (örn: 500 bin - 750 bin TL)", "asked_price", 4),
        "transmission": ("Vites tipi tercihiniz var mı? (Otomatik, Manuel)", "asked_transmission", 5),
        "year_range": ("Belirli bir model yılı aralığı (örn: 2020 sonrası) sizin için önemli mi?", "asked_year", 6),
        "model": ("{brand} markasında aklınızda özel bir model var mı?", "asked_model", 7),
    }
    # Fields that trigger a search when filled (using model field names)
    SEARCH_TRIGGER_FIELDS = {'brand', 'model', 'engine_type', 'body_type', 'transmission', 'year'} # Price/Year ranges handled separately

    # Display names for filters shown to the user
    DISPLAY_NAMES = {
        "brand": "Marka", "model": "Model", "engine_type": "Motor Tipi",
        "body_type": "Gövde Tipi", "transmission": "Vites Tipi",
        "min_price": "Min Fiyat", "max_price": "Maks Fiyat",
        "min_year": "Min Yıl", "max_year": "Maks Yıl",
        "price_range": "Fiyat Aralığı", "year_range": "Yıl Aralığı", # For summary
        # For customer info (usually not shown directly)
        "first_name": "Ad", "last_name": "Soyad", "phone": "Telefon"
    }

    # Response templates used by the agent
    RESPONSE_TEMPLATES = {
        "greeting": "Merhaba! Araba Merkezi'ne hoş geldiniz. Size nasıl yardımcı olabilirim? Aradığınız aracı tarif edebilirsiniz.",
        "personalized_greeting": "Merhaba {customer_name}! Araba Merkezi'ne tekrar hoş geldiniz. Daha önce ilgilendiğiniz '{desired_car}' hakkında bilgi almak istediğinizi görüyorum. Bu kritere uygun araçları sizin için listeliyorum:",
        "proactive_greeting_intro": "Merhaba {customer_name}! Araba Merkezi'nden arıyorum. Daha önceki görüşmemizde '{desired_car}' ile ilgilendiğinizi not almıştık.",
        "proactive_search_results": "Bu kritere uygun bulduğumuz bazı araçlar şunlar:\n{car_details}\n\n{alternative_suggestion}Bu araçlarla veya farklı bir modelle ilgilenirseniz ya da benzer fiyatlı alternatifleri görmek isterseniz lütfen belirtin.",
        "proactive_no_results": "Şu an için '{desired_car}' kriterlerinize tam uyan bir araç bulamadık, ancak envanterimiz sürekli güncelleniyor.\n{alternative_suggestion}Farklı bir model veya özellikle ilgilenirseniz yardımcı olabilirim.",
        "proactive_cannot_parse": "İlgilendiğiniz '{desired_car}' hakkında daha fazla detay verebilir misiniz? (Marka, model, tip vb.) Size uygun seçenekleri bulmak isterim.",
        "ask_next_question": "{question}",
        "acknowledge_and_ask": "Anladım, {acknowledged_info}. Peki, {question}",
        "show_results": "Harika! Belirttiğiniz kriterlere ({criteria_summary}) uygun bulduğum bazı araçlar şunlar:\n{car_details}\n\n{alternative_suggestion}Bu araçlardan ilginizi çeken oldu mu, yoksa aramayı biraz değiştirelim veya benzer fiyatlı alternatiflere mi bakalım?",
        "no_results": "Üzgünüm, belirttiğiniz kriterlere ({criteria_summary}) uygun araç envanterimizde bulunamadı. {alternative_suggestion_onerror}Yeni bir arama için kriterlerinizi belirtebilirsiniz.",
        "show_similar_results": "Son baktığınız {target_car_name} modeline ({target_car_price}) benzer fiyatta bulduğum bazı alternatifler şunlar:\n{similar_car_details}\n\nBu araçlardan biri ilginizi çekti mi?",
        "no_similar_results": "Üzgünüm, son baktığınız {target_car_name} modeline ({target_car_price}) benzer fiyatta başka uygun araç bulamadım. Farklı bir kriterle arama yapmak ister misiniz?",
        "similarity_context_missing": "Hangi araca benzer alternatifler aradığınızı anlayamadım. Lütfen önce bir arama yapıp sonuçları görelim, ardından benzerlerini isteyebilirsiniz.",
        "confirm_reset": "Arama kriterleriniz sıfırlandı. Şimdi nasıl bir araç aradığınızı belirtin.",
        "farewell": "Yardımcı olabildiğime sevindim! Tekrar görüşmek üzere, iyi günler dilerim!",
        "generic_fallback": "Üzgünüm, tam olarak anlayamadım. Bana aradığınız aracın markasını, modelini, tipini (elektrikli, SUV vb.) veya bütçenizi söyleyebilir misiniz?",
        "error_fallback": "Özür dilerim, teknik bir sorun nedeniyle şu anda yardımcı olamıyorum. Lütfen daha sonra tekrar deneyin.",
        "ask_customer_info": "Size daha sonra ulaşabilmemiz ve kişiselleştirilmiş hizmet sunabilmemiz için adınızı, soyadınızı ve telefon numaranızı paylaşır mısınız?",
        # --- Model Clarification Templates ---
        "confirm_model_match": "Sanırım '{model_name}' modelinden bahsediyorsunuz. Şöyle bir araç buldum:\n\n{car_details}\n\nBu araç mıydı ilgilendiğiniz? (Evet/Hayır)",
        "confirm_multiple_model_match": "Sanırım '{model_name}' modelinden bahsediyorsunuz. Birkaç farklı markada buldum:\n\n{car_details}\n\nHangi markanın modeliyle ilgilenmiştiniz veya bu araçlardan biri mi?",
        "model_not_found_ask_brand": "Üzgünüm, '{model_name}' modelini envanterimizde bulamadım. Hangi markanın modeli olduğunu belirtebilir misiniz?",
        "confirmation_acknowledge_ask_next": "Anlaşıldı ({confirmed_brand} {confirmed_model}). {next_question_or_search_prompt}",
        "clarification_needed_after_no": "Anladım. O zaman hangi marka ve modelle ilgileniyorsunuz?",
    }
    # --- End Configuration ---

    def __init__(self, db: Session, openrouter: OpenRouterAPI):
        self.db = db
        self.openrouter = openrouter
        # --- Initialize Memory Components ---
        self.memory_manager = MemoryManager(max_turns=3) # Store last 3 turns (6 messages)
        self.memory_verifier = MemoryVerifier(relevance_threshold=0.2) # Adjust threshold as needed
        # --- END Memory Components ---

        # LLM System Prompt for Entity Extraction
        self.system_prompt = {
            "role": "system",
            "content": """Kullanıcı mesajını analiz et ve SADECE JSON formatında şu varlıkları çıkar:
            {"entities": {
                "brand_name": "MARKA|null", "model_name": "MODEL|null", "engine_type": "MOTOR_TIPI|null",
                "body_type": "GÖVDE_TIPI|null", "transmission": "VITES|null", "min_price": SAYI|null",
                "max_price": SAYI|null", "min_year": YIL|null", "max_year": YIL|null",
                "first_name": "İSİM|null", "last_name": "SOYİSİM|null", "phone_number": "TELEFON|null",
                "desired_car_description": "İSTENEN ARAÇ TANIMI|null",
                "confirmation": "yes|no|null",
                "is_greeting": true|false,
                "is_reset": true|false,
                "is_farewell": true|false,
                "is_list_all": true|false,
                "is_similarity_request": true|false // <-- Benzerlik/Alternatif isteme niyeti
            }}
            - ANAHTAR İSİMLERİNİ İngilizce kullan. DEĞERLERİ temiz döndür ('null' string DEĞİL, null değer).
            - Fiyat/Yıl sayı olarak çıkar. Motor/Gövde/Vites tiplerini Türkçe ve kısa belirle.
            - İsim/Soyisim/Telefon çıkar. Telefonu sadece rakam yap.
            - `desired_car_description`: Genel arayışı yakala.
            - `is_similarity_request`: Kullanıcı 'benzer', 'alternatif', 'bu fiyata başka', 'muadil' gibi ifadelerle, genellikle bir önceki sonuçlara atıfta bulunarak benzer araç soruyorsa true yap. Genel listeleme veya yeni filtre belirtme durumuysa false yap.
            - Onay/Red 'confirmation' alanında belirt. Selamlama 'is_greeting'. Genel liste 'is_list_all'. Reset 'is_reset'. Veda 'is_farewell'.
            - *Eğer mesaj listesinde önceki konuşmalar varsa*, bunları da dikkate alarak daha doğru ve bağlama uygun varlık çıkarımı yap.
            - Anlaşılmayanlar için boş 'entities' döndür. Çıktın SADECE JSON olsun."""
        }
        self.current_context = self._reset_context() # Resets context and clears memory
        self.available_brands_cache = None
        log.info("AIAgent initialized with MemoryManager and MemoryVerifier.")

    def _reset_context(self) -> Dict[str, Any]:
        """Resets search filters, customer info, dialogue state, and clears memory."""
        context = {
            "filters": {},
            "asked_questions": set(),
            "last_question_key": None,
            "search_performed": False,
            "results_shown": False,
            "last_acknowledged_info": None,
            "customer_id": None,
            "customer_first_name": None,
            "customer_phone": None,
            "customer_desired_car": None,
            "initial_personalized_greeting_done": False,
            "asked_for_customer_info": False,
            "last_response": None,
            "last_shown_cars": None,
            "last_shown_target_price": None,
            "last_shown_target_model": None,
            "last_shown_target_brand": None,
            "awaiting_model_confirmation": False,
            "potential_model_matches": None,
        }
        # Dynamically initialize filter keys
        filter_keys = ['brand', 'model', 'engine_type', 'body_type', 'transmission', 'price', 'year']
        range_keys = ['min_price', 'max_price', 'min_year', 'max_year']
        for key in filter_keys:
             if hasattr(Car, key): context['filters'][key] = None
        for key in range_keys:
             base_key = key.replace('min_', '').replace('max_', '')
             if hasattr(Car, base_key): context['filters'][key] = None

        # Clear memory on context reset
        if hasattr(self, 'memory_manager'):
            self.memory_manager.clear_memory()

        self.current_context = context
        log.info("Context reset and memory cleared.")
        return context

    def _log_query_db(self, query: str, response: str):
        """Logs the user query and agent response to the database."""
        try:
            timestamp = datetime.utcnow()
            max_len = 4000
            query_log = query[:max_len] if query else ""
            response_log = response[:max_len] if response else ""
            log_entry = UserQuery(query=query_log, result=response_log, timestamp=timestamp)
            self.db.add(log_entry)
            self.db.commit()
            log.debug(f"Query logged: User='{query_log[:50]}...', Agent='{response_log[:50]}...'")
        except Exception as e:
            log.warning(f"Failed to log query: {e}", exc_info=True)
            self.db.rollback()

    def _get_available_brands(self) -> List[str]:
        """Gets distinct car brands from DB (using cache)."""
        if self.available_brands_cache is None:
             log.debug("Fetching and caching distinct brands.")
             self.available_brands_cache = sorted(get_distinct_brands(self.db))
        return self.available_brands_cache

    def _extract_entities_llm(self, user_message: str) -> Optional[Dict[str, Any]]:
        """Extracts entities from user message using LLM, potentially with memory context."""
        try:
            # Prepare messages for LLM
            messages = [self.system_prompt]
            memory_history = self.memory_manager.get_memory()

            # Check memory relevance
            is_relevant = False
            if memory_history:
                 is_relevant = self.memory_verifier.is_memory_relevant(user_message, memory_history)

            if is_relevant:
                 log.debug(f"Adding {len(memory_history)} relevant memory messages to LLM prompt.")
                 messages.extend(memory_history) # Add recent history

            # Add current user message
            messages.append({"role": "user", "content": user_message})

            # Send to LLM
            raw_response = self.openrouter.send_request(messages, temperature=0.0, max_tokens=350)
            log.debug(f"LLM Entity Extraction Raw Response: {raw_response}")
            if not raw_response: return None

            # Parse JSON response
            match_markdown = re.search(r'```json\s*(\{[\s\S]*?\})\s*```', raw_response, re.IGNORECASE)
            match_plain = re.search(r'(\{[\s\S]*\})\s*$', raw_response) # Match JSON at the end

            json_str = None
            if match_markdown: json_str = match_markdown.group(1); log.debug("Extracted JSON from markdown.")
            elif match_plain: json_str = match_plain.group(1); log.debug("Extracted JSON from plain block.")

            if json_str:
                try:
                    result = json.loads(json_str)
                    if isinstance(result, dict) and 'entities' in result and isinstance(result['entities'], dict):
                        cleaned_entities = {k: v for k, v in result['entities'].items() if v is not None and str(v).lower() != 'null'}
                        normalized_entities = self._normalize_entities(cleaned_entities)
                        return normalized_entities
                    else: log.warning(f"LLM response JSON structure incorrect: {json_str}")
                except json.JSONDecodeError as json_err: log.warning(f"LLM JSON parsing failed: {json_err}. Raw JSON: {json_str}")
            else: log.warning(f"No JSON object found in LLM response: {raw_response}")
        except Exception as e: log.error(f"Error during LLM Entity Extraction: {e}", exc_info=True)
        return None

    def _normalize_entities(self, entities: Dict[str, Any]) -> Dict[str, Any]:
        """Cleans, normalizes extracted entities, and maps values (Turkish, short forms)."""
        normalized = {}
        value_mapping = {
            "engine_type": {"electric": "Elektrik", "electrical": "Elektrik", "elektrikli": "Elektrik", "elektrik": "Elektrik", "diesel": "Dizel", "dizel": "Dizel", "gasoline": "Benzin", "petrol": "Benzin", "benzinli": "Benzin", "benzin": "Benzin", "hybrid": "Hibrit", "hibrit": "Hibrit"},
            "body_type": {"suv": "SUV", "sedan": "Sedan", "hatchback": "Hatchback", "hb": "Hatchback"},
            "transmission": {"automatic": "Otomatik", "auto": "Otomatik", "otomatik": "Otomatik", "manual": "Manuel", "manuel": "Manuel"}
        }

        # Price & Year
        min_p = self._parse_price(entities.get('min_price')) # Pass value directly
        max_p = self._parse_price(entities.get('max_price'))
        if min_p is not None: normalized['min_price'] = min_p
        if max_p is not None: normalized['max_price'] = max_p
        min_y = self._parse_year(entities.get('min_year')) # Pass value directly
        max_y = self._parse_year(entities.get('max_year'))
        if min_y is not None: normalized['min_year'] = min_y
        if max_y is not None: normalized['max_year'] = max_y

        # String Filters (Using Mappings)
        llm_filter_keys = ["brand_name", "model_name", "engine_type", "body_type", "transmission"]
        context_mapping = {"brand_name": "brand", "model_name": "model", "engine_type": "engine_type", "body_type": "body_type", "transmission": "transmission"}
        for llm_key in llm_filter_keys:
            value = entities.get(llm_key)
            if isinstance(value, str) and value.strip():
                context_key = context_mapping.get(llm_key, llm_key)
                norm_value_lower = value.strip().lower()
                normalized_value = value.strip().title() # Default
                if context_key in value_mapping:
                    mapped_value = value_mapping[context_key].get(norm_value_lower)
                    if mapped_value:
                        normalized_value = mapped_value # Use mapped Turkish value
                        log.debug(f"Mapped '{llm_key}' value '{value}' to '{normalized_value}' for '{context_key}'")
                normalized[context_key] = normalized_value

        # Customer Information
        if 'first_name' in entities: normalized['first_name'] = str(entities['first_name']).strip().title()
        if 'last_name' in entities: normalized['last_name'] = str(entities['last_name']).strip().title()
        if 'phone_number' in entities: normalized['phone'] = self._normalize_phone(str(entities['phone_number']))
        if 'desired_car_description' in entities: normalized['desired_car_description'] = str(entities['desired_car_description']).strip()

        # Flags & Confirmation
        normalized['is_greeting'] = entities.get('is_greeting', False)
        normalized['is_reset'] = entities.get('is_reset', False)
        normalized['is_farewell'] = entities.get('is_farewell', False)
        normalized['is_list_all'] = entities.get('is_list_all', False)
        normalized['is_similarity_request'] = entities.get('is_similarity_request', False)
        normalized['confirmation'] = entities.get('confirmation')

        log.debug(f"Normalized entities: {normalized}")
        return normalized

    def _normalize_phone(self, phone_str: Optional[str]) -> Optional[str]:
        """Cleans phone number string, keeping only digits."""
        if phone_str is None: return None
        cleaned = re.sub(r'\D', '', str(phone_str)) # Ensure string input
        if 10 <= len(cleaned) <= 13: # Allow for potential country codes
             return cleaned
        log.warning(f"Phone number '{phone_str}' invalid after cleaning ('{cleaned}'). Returning None.")
        return None # Return None if invalid length

    def _parse_price(self, price_val: Optional[Any]) -> Optional[int]:
        """Parses price string/number (e.g., '500 bin TL', 1200000) into integer."""
        if price_val is None: return None
        if isinstance(price_val, (int, float)): # Already a number
             return int(price_val)
        if not isinstance(price_val, str):
            price_str = str(price_val) # Convert to string if needed
        else:
            price_str = price_val

        try:
             price_str = price_str.lower()
             price_str = re.sub(r'[,.]', '', price_str.replace('tl', '').replace('try', '')).strip()
             multiplier = 1
             if 'milyon' in price_str:
                 multiplier = 1000000
                 price_str = price_str.replace('milyon','')
             elif 'bin' in price_str or 'k' in price_str:
                 multiplier = 1000
                 price_str = price_str.replace('bin','').replace('k','')

             num_match = re.search(r'(\d+)', price_str.strip())
             if num_match:
                 return int(num_match.group(1)) * multiplier
        except Exception as e: log.warning(f"Could not parse price string '{price_val}': {e}")
        return None

    def _parse_year(self, year_val: Optional[Any]) -> Optional[int]:
        """Parses year string/number, expecting a 4-digit year."""
        if year_val is None: return None
        if isinstance(year_val, int) and 1900 < year_val < 2100: # Already a valid year int
            return year_val
        if not isinstance(year_val, str):
             year_str = str(year_val)
        else:
             year_str = year_val

        try:
             num_match = re.search(r'(?<!\d)(20\d{2}|19\d{2})(?!\d)', year_str) # Look for 4 digits 19xx or 20xx
             if num_match: return int(num_match.group(1))
        except Exception as e: log.warning(f"Could not parse year '{year_val}': {e}")
        return None

    def _update_context_with_entities(self, entities: Dict[str, Any]) -> bool:
        """Updates agent context (filters & customer info) with normalized entities."""
        if not entities: return False
        updated = False
        acknowledged_parts = []
        self.updated_keys_this_turn = set() # Track keys updated in this specific call

        # --- Update Customer Info ---
        if 'first_name' in entities and self.current_context.get('customer_first_name') != entities['first_name']:
            self.current_context['customer_first_name'] = entities['first_name']
            log.info(f"Context updated with customer first name: {entities['first_name']}")
            updated = True; self.updated_keys_this_turn.add('first_name')
        if 'phone' in entities and self.current_context.get('customer_phone') != entities['phone']:
             self.current_context['customer_phone'] = entities['phone']
             log.info(f"Context updated with customer phone: {entities['phone']}")
             updated = True; self.updated_keys_this_turn.add('phone')

        # --- Update Filters ---
        potential_filter_keys = self.SEARCH_TRIGGER_FIELDS | {'min_price', 'max_price', 'min_year', 'max_year', 'brand', 'model'}
        current_brand_before_update = self.current_context['filters'].get('brand')

        for context_key in potential_filter_keys:
            if context_key in entities:
                new_value = entities[context_key]
                if new_value is not None:
                    base_key = context_key.replace('min_', '').replace('max_', '')
                    if hasattr(Car, base_key) or context_key in ['min_price', 'max_price', 'min_year', 'max_year']:
                        if self.current_context['filters'].get(context_key) != new_value:
                            self.current_context['filters'][context_key] = new_value
                            updated = True; self.updated_keys_this_turn.add(context_key)
                            display_name = self.DISPLAY_NAMES.get(context_key, context_key.replace('_',' ').title())
                            value_str = str(new_value)
                            if isinstance(new_value, (int, float, decimal.Decimal)) and 'price' in context_key:
                                try: value_str = f"{decimal.Decimal(new_value):,.0f} TL"
                                except: value_str = f"{new_value} TL"
                            elif isinstance(new_value, int) and 'year' in context_key:
                                value_str = str(new_value) # Keep year as plain number
                            acknowledged_parts.append(f"{display_name}: {value_str}")
                            # Mark related question as answered
                            q_key_base = context_key # Start with the context key
                            if context_key in ['min_price', 'max_price']: q_key_base = 'price_range'
                            elif context_key in ['min_year', 'max_year']: q_key_base = 'year_range'
                            # Find the question based on the base key
                            if q_key_base in self.FILTER_QUESTIONS:
                                _, asked_flag, _ = self.FILTER_QUESTIONS[q_key_base]
                                self.current_context['asked_questions'].add(asked_flag)
                                log.debug(f"Marked question '{asked_flag}' as answered for '{context_key}'.")
                    else:
                        log.warning(f"Skipping update for non-existent field '{base_key}' from entity '{context_key}'.")

        # Reset model if brand changes
        new_brand = self.current_context['filters'].get('brand')
        if new_brand and new_brand != current_brand_before_update:
            if self.current_context['filters'].get('model') is not None:
                log.info(f"Brand changed from '{current_brand_before_update}' to '{new_brand}'. Resetting model.")
                if hasattr(Car, 'model'):
                    self.current_context['filters']['model'] = None
                    # Find the flag for the model question and discard it
                    if 'model' in self.FILTER_QUESTIONS:
                        _, model_asked_flag, _ = self.FILTER_QUESTIONS['model']
                        if model_asked_flag in self.current_context['asked_questions']:
                            self.current_context['asked_questions'].discard(model_asked_flag)
                            log.debug(f"Unmarked question '{model_asked_flag}' due to brand change.")
                    updated = True

        # Finalize
        if updated:
            log.info(f"Context updated. Keys: {self.updated_keys_this_turn}. Filters: {self.current_context['filters']}, Phone: {self.current_context.get('customer_phone')}")
            if acknowledged_parts: self.current_context['last_acknowledged_info'] = ", ".join(acknowledged_parts)
            else: self.current_context['last_acknowledged_info'] = None
            self.current_context['search_performed'] = False # Reset flags as context changed
            self.current_context['results_shown'] = False
        else:
            self.current_context['last_acknowledged_info'] = None # Clear acknowledgment if no update
        return updated

    def _should_search(self) -> bool:
        """Determines if there are enough criteria to perform a database search."""
        filters = self.current_context['filters']
        filled_trigger_fields = set()
        # Check single value trigger fields
        for key in self.SEARCH_TRIGGER_FIELDS:
            if filters.get(key) is not None and hasattr(Car, key):
                filled_trigger_fields.add(key)
        # Check range fields
        if (filters.get('min_price') is not None or filters.get('max_price') is not None) and hasattr(Car, 'price'):
            filled_trigger_fields.add('price_range')
        if (filters.get('min_year') is not None or filters.get('max_year') is not None) and hasattr(Car, 'year'):
            filled_trigger_fields.add('year_range')

        # Allow search if any valid field or range is filled.
        can_search = bool(filled_trigger_fields)
        log.debug(f"Should search? {'Yes' if can_search else 'No'}. Valid trigger fields/ranges met: {filled_trigger_fields}")
        return can_search

    def _get_next_question(self) -> Optional[str]:
        """Determines the next logical question to ask the user based on context."""
        sorted_questions = sorted(self.FILTER_QUESTIONS.items(), key=lambda item: item[1][2]) # Sort by priority
        current_filters = self.current_context['filters']
        asked_questions = self.current_context['asked_questions']

        for filter_key, (question_template, asked_flag, _) in sorted_questions:
            if filter_key == "customer_info": continue

            base_key = filter_key.replace('price_range', 'price').replace('year_range', 'year')
            is_range = filter_key in ['price_range', 'year_range']
            field_exists_or_is_range = hasattr(Car, base_key) or is_range

            if not field_exists_or_is_range: continue # Skip if field invalid

            if asked_flag in asked_questions: continue # Skip if already asked

            needs_asking = False
            if filter_key == 'price_range': needs_asking = (current_filters.get('min_price') is None and current_filters.get('max_price') is None)
            elif filter_key == 'year_range': needs_asking = (current_filters.get('min_year') is None and current_filters.get('max_year') is None)
            elif filter_key == 'model': needs_asking = (current_filters.get('brand') is not None and current_filters.get('model') is None)
            else: needs_asking = current_filters.get(filter_key) is None

            if needs_asking:
                 question = question_template
                 try:
                     format_args = {}
                     if '{available_brands}' in question:
                         brands = self._get_available_brands()
                         format_args['available_brands'] = ', '.join(brands) if brands else "marka bilgisi yok"
                     if '{brand}' in question:
                         brand_val = current_filters.get('brand', 'ilgili')
                         format_args['brand'] = brand_val if brand_val else 'ilgili'
                     question = question.format(**format_args)
                 except Exception as e: log.error(f"Error formatting question ({filter_key}): {e}"); continue

                 self.current_context['last_question_key'] = filter_key # Store key before returning
                 log.info(f"Next question determined ({filter_key}): {question}")
                 return question

        log.info("No suitable next question found.")
        self.current_context['last_question_key'] = None
        return None

    def _format_single_car_detail(self, car: Car) -> str:
        """Formats a single Car object's details clearly."""
        if not car: return "Araç bilgisi bulunamadı."
        info_parts = [f"**Marka:** {car.brand}", f"**Model:** {car.model}"]
        if car.year: info_parts.append(f"**Yıl:** {car.year}")
        if car.engine_type: info_parts.append(f"**Motor:** {car.engine_type}")
        if car.horsepower: info_parts.append(f"**Güç:** {car.horsepower} HP")
        if car.capacity is not None:
            try: cap_str = f"{decimal.Decimal(car.capacity):.1f} L"
            except: cap_str = f"{car.capacity} L"
            info_parts.append(f"**Hacim:** {cap_str}")
        if car.transmission: info_parts.append(f"**Vites:** {car.transmission}")
        if car.body_type: info_parts.append(f"**Kasa:** {car.body_type}")
        if car.price is not None:
            try: price_str = f"{car.price:,.0f} {car.currency or 'TL'}"
            except: price_str = f"{car.price} {car.currency or 'TL'}"
            info_parts.append(f"**Fiyat:** {price_str}")
        return "\n".join(f"- {part}" for part in info_parts)

    def _format_car_details(self, cars: List[Car]) -> str:
        """Formats a list of Car objects into a user-friendly string."""
        if not cars: return " Uygun araç bulunamadı."
        details_list = []
        for car in cars:
            base_info = f"**{car.brand} {car.model}**"
            if car.year: base_info += f" ({car.year})"
            info_parts = [base_info]
            other_details = []
            if car.engine_type: other_details.append(f"{car.engine_type}")
            if car.transmission: other_details.append(f"{car.transmission}")
            if car.body_type: other_details.append(f"{car.body_type}")
            if other_details: info_parts.append(" / ".join(other_details))
            if car.price is not None:
                try: price_str = f"{car.price:,.0f} {car.currency or 'TL'}"
                except: price_str = f"{car.price} {car.currency or 'TL'}"
                info_parts.append(f"Fiyat: **{price_str}**")
            details_list.append("- " + " / ".join(info_parts))
        return "\n".join(details_list)

    def _get_criteria_summary(self) -> str:
        """Creates a user-friendly summary of the current search filters."""
        parts = []
        display_order = ['brand', 'model', 'body_type', 'engine_type', 'transmission', 'price_range', 'year_range']
        processed_keys = set()
        filters = self.current_context['filters']

        for key in display_order:
            if key in processed_keys: continue
            base_key_check = key.replace('_range', '')
            field_exists = hasattr(Car, base_key_check)
            is_range_key = key in ['price_range', 'year_range']
            if not field_exists and not is_range_key: continue

            value_str = None
            if key == 'price_range':
                min_p = filters.get('min_price'); max_p = filters.get('max_price')
                if min_p is not None or max_p is not None:
                    if min_p is not None and max_p is not None: value_str = f"{min_p:,.0f} - {max_p:,.0f} TL"
                    elif min_p is not None: value_str = f"{min_p:,.0f} TL üzeri"
                    else: value_str = f"{max_p:,.0f} TL altı"
                    parts.append(f"Fiyat Aralığı: {value_str}")
                    processed_keys.update(['min_price', 'max_price'])
            elif key == 'year_range':
                 min_y = filters.get('min_year'); max_y = filters.get('max_year')
                 if min_y is not None or max_y is not None:
                     if min_y is not None and max_y is not None: value_str = f"{min_y} - {max_y}"
                     elif min_y is not None: value_str = f"{min_y} sonrası"
                     else: value_str = f"{max_y} öncesi"
                     parts.append(f"Yıl Aralığı: {value_str}")
                     processed_keys.update(['min_year', 'max_year'])
            else: # Single value fields
                 value = filters.get(key)
                 if value is not None:
                      display_name = self.DISPLAY_NAMES.get(key, key.replace('_',' ').title())
                      parts.append(f"{display_name}: {value}")
                      processed_keys.add(key)
        return ", ".join(parts) if parts else "belirtilen kriterlere"

    def _get_alternative_model_suggestion(self, current_brand: Optional[str], current_model: Optional[str]) -> str:
        """Generates a suggestion for alternative car models based on current context."""
        try:
            exclude_list = [current_model] if current_model else []
            alternative_models = get_distinct_models(self.db, brand=current_brand, exclude_model=exclude_list, limit=3)
            needed = 3 - len(alternative_models)
            if needed > 0:
                 exclude_list.extend(alternative_models)
                 additional_models = get_distinct_models(self.db, brand=None, exclude_model=exclude_list, limit=needed)
                 alternative_models.extend(additional_models)
            alternative_models = sorted(list(set(m for m in alternative_models if m))) # Unique, sorted, non-empty

            if alternative_models:
                model_list = ", ".join(f"**{m}**" for m in alternative_models)
                suggestion = f"Ayrıca {model_list} gibi farklı modeller de ilginizi çekebilir.\n\n"
                return suggestion
            else: return ""
        except Exception as e: log.error(f"Error getting alternative models: {e}", exc_info=True); return ""

    # --- Proactive Start Methods ---
    def _initialize_with_customer(self, customer: CustomerLead):
        """Initializes agent context with data from a CustomerLead object."""
        self._reset_context() # Resets context and clears memory
        self.current_context['customer_id'] = customer.id
        self.current_context['customer_first_name'] = customer.first_name
        self.current_context['customer_phone'] = customer.phone
        self.current_context['customer_desired_car'] = customer.desired_car_info
        self.current_context['initial_personalized_greeting_done'] = True
        log.info(f"Agent context initialized proactively for customer ID: {customer.id} ({customer.first_name})")

    def generate_proactive_start_message(self, customer: CustomerLead) -> str:
        """Creates the initial proactive message for a selected customer."""
        if not customer: return self.RESPONSE_TEMPLATES["greeting"]
        self._initialize_with_customer(customer)
        desired_car_str = customer.desired_car_info or "belirli bir araç"
        intro_message = self.RESPONSE_TEMPLATES["proactive_greeting_intro"].format(
            customer_name=customer.first_name, desired_car=desired_car_str
        )
        initial_filters = self._parse_desired_car_info(customer.desired_car_info)
        search_message_part = ""

        # Clear transient states before proceeding
        self.current_context['last_shown_cars'] = None; self.current_context['last_shown_target_price'] = None
        self.current_context['last_shown_target_model'] = None; self.current_context['last_shown_target_brand'] = None
        self.current_context['awaiting_model_confirmation'] = False; self.current_context['potential_model_matches'] = None
        self.current_context['search_performed'] = False; self.current_context['results_shown'] = False

        if initial_filters:
            log.info(f"Attempting proactive start based on lead info: {initial_filters}")
            self.current_context['filters'].update(initial_filters)
            criteria_summary = self._get_criteria_summary()

            if self.current_context['filters'].get('model') and not self.current_context['filters'].get('brand'):
                 log.info("Proactive start: model without brand. Triggering clarification.")
                 self._execute_action("clarify_model", "<<PROACTIVE_CLARIFICATION>>", {})
                 search_message_part = self.current_context.get('last_response', self.RESPONSE_TEMPLATES["generic_fallback"])
            elif self._should_search():
                 log.info("Proactive start: proceeding with search.")
                 found_cars = find_cars_by_criteria(self.db, filters=self.current_context['filters'], limit=3)
                 self.current_context['search_performed'] = True
                 alt_suggestion = self._get_alternative_model_suggestion(self.current_context['filters'].get('brand'), self.current_context['filters'].get('model'))
                 if found_cars:
                     car_details_str = self._format_car_details(found_cars); self.current_context['results_shown'] = True
                     search_message_part = self.RESPONSE_TEMPLATES["proactive_search_results"].format(car_details=car_details_str, alternative_suggestion=alt_suggestion)
                     first_car = found_cars[0]
                     self.current_context['last_shown_cars'] = found_cars; self.current_context['last_shown_target_price'] = first_car.price
                     self.current_context['last_shown_target_model'] = first_car.model; self.current_context['last_shown_target_brand'] = first_car.brand
                     log.info(f"Proactive search successful. Stored context for similarity.")
                 else:
                     search_message_part = self.RESPONSE_TEMPLATES["proactive_no_results"].format(desired_car=criteria_summary or desired_car_str, alternative_suggestion=alt_suggestion)
                     self.current_context['results_shown'] = False
            else: # Parsed filters but cannot search yet
                log.info("Proactive start: parsed filters but not enough to search. Asking next question.")
                next_q = self._get_next_question()
                if next_q:
                     ack_info = criteria_summary
                     if ack_info: search_message_part = self.RESPONSE_TEMPLATES["acknowledge_and_ask"].format(acknowledged_info=ack_info, question=next_q)
                     else: search_message_part = self.RESPONSE_TEMPLATES["ask_next_question"].format(question=next_q)
                     if self.current_context['last_question_key'] in self.FILTER_QUESTIONS: # Mark as asked
                         _, asked_flag, _ = self.FILTER_QUESTIONS[self.current_context['last_question_key']]
                         self.current_context['asked_questions'].add(asked_flag)
                else:
                     log.warning("Proactive start: Filters parsed, cannot search, no next question found.")
                     search_message_part = self.RESPONSE_TEMPLATES["generic_fallback"]
        else: # Cannot parse desired car info
            search_message_part = self.RESPONSE_TEMPLATES["proactive_cannot_parse"].format(desired_car=desired_car_str)

        full_message = f"{intro_message}\n\n{search_message_part}"
        # Add proactive messages to memory
        self.memory_manager.add_message("assistant", full_message)
        self._log_query_db("<<PROACTIVE_START>>", full_message)
        self.current_context['last_response'] = full_message
        return full_message
    # --- End Proactive Start Methods ---

    # --- Main Message Processing Logic ---
    def process_message(self, user_message: str) -> str:
        """Processes incoming user messages based on dialogue state and context."""
        response = self.RESPONSE_TEMPLATES["generic_fallback"]
        try:
            # Add user message to memory first
            self.memory_manager.add_message("user", user_message)

            # 1. Extract Entities (potentially using memory context)
            entities = self._extract_entities_llm(user_message)
            if entities is None:
                log.warning("LLM entity extraction failed. Using fallback keyword extraction.")
                entities = self._fallback_entity_extraction(user_message)
            log.info(f"Effective Entities (from user msg): {entities}")
            self.updated_keys_this_turn = set()

            # --- SPECIAL: Handle Confirmation for Model Clarification ---
            if self.current_context.get('awaiting_model_confirmation'):
                confirmation = entities.get('confirmation')
                log.info(f"Awaiting model confirmation. User input suggests: {confirmation}")
                action = "handle_model_confirmation"
                self.current_context['last_response'] = None
                self._execute_action(action, user_message, entities) # Handles logic and sets response
                final_response = self.current_context.get('last_response', self.RESPONSE_TEMPLATES["error_fallback"])
                self._log_query_db(user_message, final_response)
                self.memory_manager.add_message("assistant", final_response) # Add final response to memory
                return final_response

            # --- Prioritize Similarity Request ---
            is_similarity_request = entities.get('is_similarity_request', False)
            if is_similarity_request: # Check intent first
                if self.current_context.get('results_shown'):
                    log.info("Handling similarity request.")
                    target_price = self.current_context.get('last_shown_target_price')
                    target_model = self.current_context.get('last_shown_target_model')
                    target_brand = self.current_context.get('last_shown_target_brand')
                    if target_price is not None and target_model and target_brand:
                        action = "find_similar"; self._execute_action(action, user_message, entities)
                        final_response = self.current_context.get('last_response', self.RESPONSE_TEMPLATES["error_fallback"])
                    else:
                        log.warning("Similarity request, but context missing.")
                        final_response = self.RESPONSE_TEMPLATES["similarity_context_missing"]
                        self.current_context['last_response'] = final_response # Store it
                else: # Similarity requested but no results shown
                     log.warning("Similarity request, but no results previously shown.")
                     final_response = self.RESPONSE_TEMPLATES["similarity_context_missing"]
                     self.current_context['last_response'] = final_response # Store it
                # Log and add response to memory, then return
                self._log_query_db(user_message, final_response)
                self.memory_manager.add_message("assistant", final_response)
                return final_response

            # --- Customer Identification ---
            phone_from_entities = entities.get('phone')
            if phone_from_entities and (phone_from_entities != self.current_context.get('customer_phone') or self.current_context.get('customer_phone') is None):
                if self.current_context.get('customer_id'):
                     log.warning(f"User provided phone ({phone_from_entities}), resetting customer context (ID: {self.current_context['customer_id']}).")
                     self.current_context['customer_id'] = None; self.current_context['customer_first_name'] = None
                     self.current_context['customer_desired_car'] = None; self.current_context['initial_personalized_greeting_done'] = False
                log.info(f"Attempting to find customer by phone: {phone_from_entities}")
                customer = find_customer_lead_by_phone(self.db, phone_from_entities)
                if customer:
                    log.info(f"Existing customer found: {customer.first_name} (ID: {customer.id})")
                    self.current_context['customer_id'] = customer.id; self.current_context['customer_first_name'] = customer.first_name
                    self.current_context['customer_phone'] = customer.phone; self.current_context['customer_desired_car'] = customer.desired_car_info
                else:
                    log.info(f"New phone {phone_from_entities}, no customer found.")
                    self.current_context['customer_phone'] = phone_from_entities
                    if entities.get('first_name'): self.current_context['customer_first_name'] = entities['first_name']

            # --- Handle Immediate Actions ---
            action_taken = False
            if entities.get('is_reset') or entities.get('is_farewell') or \
               (entities.get('is_greeting') and not self.current_context.get('initial_personalized_greeting_done')) or \
               entities.get('is_list_all'):
                action_taken = self._handle_immediate_actions(entities)

            if action_taken:
                final_response = self.current_context.get('last_response', self.RESPONSE_TEMPLATES["farewell"])
                self._log_query_db(user_message, final_response)
                self.memory_manager.add_message("assistant", final_response) # Add immediate action response to memory
                return final_response

            # --- Normal Dialogue Flow ---
            context_updated = self._update_context_with_entities(entities)
            confirmation = entities.get('confirmation')
            action = "ask" # Default

            # --- Check for Model Clarification Need ---
            current_filters = self.current_context['filters']
            if current_filters.get('model') and not current_filters.get('brand') and \
               ('model' in self.updated_keys_this_turn or not context_updated):
                 log.info(f"Model '{current_filters['model']}' needs clarification.")
                 action = "clarify_model"; self._execute_action(action, user_message, entities)
                 final_response = self.current_context.get('last_response', self.RESPONSE_TEMPLATES["error_fallback"])
                 self._log_query_db(user_message, final_response)
                 self.memory_manager.add_message("assistant", final_response) # Add response to memory
                 return final_response

            # --- Determine Next Action (Standard Flow) ---
            if action != "clarify_model": # Avoid overwriting clarification
                if context_updated: action = "search" if self._should_search() else "ask"
                elif confirmation == 'yes':
                    if self.current_context['results_shown']: action = "wait"; self.current_context['last_response'] = "Harika! İlgilendiğiniz spesifik bir model veya özellik var mıydı, yoksa benzer fiyatlı alternatiflere mi bakalım?"
                    else: action = "search" if self._should_search() else "ask"
                elif confirmation == 'no':
                    if self.current_context['results_shown']: action = "wait"; self._reset_context(); self.current_context['last_response'] = "Anladım. Farklı kriterlerle yeni bir arama yapmak isterseniz yardımcı olabilirim. Lütfen yeni kriterlerinizi belirtin."
                    elif self.current_context['last_question_key']:
                        log.info(f"User said 'no' to {self.current_context['last_question_key']}. Skipping.")
                        q_key = self.current_context['last_question_key']
                        if q_key in self.FILTER_QUESTIONS: _, asked_flag, _ = self.FILTER_QUESTIONS[q_key]; self.current_context['asked_questions'].add(asked_flag)
                        action = "ask"
                    else: action = "ask"
                else: # No context update, no confirmation
                    if self._should_search() and not self.current_context.get('search_performed'): action = "search"
                    else: action = "ask"

            # --- Execute Determined Action ---
            if action not in ["clarify_model", "handle_model_confirmation"]:
                self._execute_action(action, user_message, entities)

            # --- Log, Add to Memory, and Return Final Response ---
            final_response = self.current_context.get('last_response', self.RESPONSE_TEMPLATES["error_fallback"])
            self._log_query_db(user_message, final_response)
            self.memory_manager.add_message("assistant", final_response) # Add final response to memory
            return final_response

        except Exception as e:
            log.exception("Critical error during message processing:")
            error_msg = self.RESPONSE_TEMPLATES["error_fallback"]
            self.current_context['awaiting_model_confirmation'] = False
            self.current_context['potential_model_matches'] = None
            self._log_query_db(user_message, f"**SYSTEM_ERROR**: {str(e)}")
            self.memory_manager.add_message("assistant", error_msg) # Log error msg to memory too
            return error_msg
    # --- End Main Processing Logic ---


    # --- Helper Methods ---
    def _fallback_entity_extraction(self, user_message: str) -> Dict[str, Any]:
        """Simple keyword-based entity extraction if LLM fails."""
        entities = {}
        um_lower = user_message.lower()
        # Confirmation/Negation
        if um_lower in ['evet', 'tamam', 'olur', 'evet lütfen', 'aynen', 'evet o', 'doğru']: entities['confirmation'] = 'yes'
        elif um_lower in ['hayır', 'hayir', 'yok', 'istemiyorum', 'hayır teşekkürler', 'değil', 'o değil', 'başka']: entities['confirmation'] = 'no'
        elif "değiştir" in um_lower: log.debug("Fallback: 'değiştir' detected, neutral intent.")

        # Flags
        if um_lower in ['merhaba', 'selam', 'iyi günler', 'kolay gelsin', 'selamlar', 'mrb']: entities['is_greeting'] = True
        if um_lower in ['reset', 'sıfırla', 'baştan başla', 'iptal', 'vazgeçtim', 'isteklerimi sıfırla']: entities['is_reset'] = True
        if um_lower in ['çıkış', 'görüşürüz', 'iyi günler', 'bye', 'hoşçakal', 'kapat', 'teşekkürler görüşürüz']: entities['is_farewell'] = True
        if 'benzer' in um_lower or 'alternatif' in um_lower or 'muadil' in um_lower or 'başka ne var' in um_lower or 'bu fiyata' in um_lower: entities['is_similarity_request'] = True
        if 'hepsi' in um_lower or 'tüm araçlar' in um_lower or 'listele' in um_lower or 'ne var ne yok' in um_lower: entities['is_list_all'] = True

        # Basic filter extraction
        brands = self._get_available_brands(); found_brand = None
        for brand in brands:
            if re.search(r'\b' + re.escape(brand.lower()) + r'\b', um_lower):
                entities['brand'] = brand.title(); found_brand = brand.lower(); break

        if not found_brand: # Try model only if brand not found
            potential_models = re.findall(r'\b([A-Z][a-zA-Z0-9]+(?:\s+[A-Z0-9][a-zA-Z0-9\-]+)*)\b', user_message)
            common_non_models = {'Merhaba', 'Evet', 'Hayır', 'Tamam', 'Teşekkürler', 'Lütfen', 'Var', 'Yok', 'Araç', 'Araba', 'Model'}
            filtered_models = [m.strip() for m in potential_models if m not in common_non_models and len(m) > 1 and not m.isdigit()]
            if filtered_models: entities['model'] = filtered_models[-1].title(); log.debug(f"Fallback model: {entities['model']}")

        # Types/Transmission
        if 'elektrik' in um_lower: entities['engine_type'] = 'Elektrik'
        elif 'dizel' in um_lower: entities['engine_type'] = 'Dizel'
        elif 'benzin' in um_lower: entities['engine_type'] = 'Benzin'
        elif 'hibrit' in um_lower: entities['engine_type'] = 'Hibrit'
        if 'suv' in um_lower: entities['body_type'] = 'SUV'
        elif 'sedan' in um_lower: entities['body_type'] = 'Sedan'
        elif 'hatchback' in um_lower or ' hb' in um_lower: entities['body_type'] = 'Hatchback'
        if 'otomatik' in um_lower: entities['transmission'] = 'Otomatik'
        elif 'manuel' in um_lower: entities['transmission'] = 'Manuel'

        # Price/Year (Very basic)
        price_match = re.search(r'(\d+)\s*(?:bin|k)', um_lower)
        if price_match: entities['max_price'] = int(price_match.group(1)) * 1000
        else: price_match_large = re.search(r'(\d{6,})', um_lower);
        if price_match_large: entities['max_price'] = int(price_match_large.group(1))
        year_match = re.search(r'\b(20\d{2}|19\d{2})\b', um_lower) # Allow 19xx or 20xx
        if year_match: entities['min_year'] = int(year_match.group(1))

        # Phone
        phone_match = re.search(r'(\d{10,11})', re.sub(r'\D', '', user_message))
        if phone_match: entities['phone'] = self._normalize_phone(phone_match.group(1))
        log.debug(f"Fallback entities extracted: {entities}")
        return entities

    def _parse_desired_car_info(self, desired_info: Optional[str]) -> Dict[str, Any]:
        """Attempts to parse basic filters from a free text description."""
        if not desired_info: return {}
        filters = {}; info_lower = desired_info.lower()
        brands = self._get_available_brands(); found_brand = None
        for brand in brands:
            if re.search(r'\b' + re.escape(brand.lower()) + r'\b', info_lower):
                filters['brand'] = brand.title(); found_brand = brand.lower(); break
        if found_brand:
            try:
                brand_index = info_lower.index(found_brand)
                text_after_brand = desired_info[brand_index + len(found_brand):].strip()
                model_match = re.search(r'^([A-Za-z0-9][A-Za-z0-9\-\s]+?)(?:\s+|\b|$)', text_after_brand)
                if model_match:
                    potential_model = model_match.group(1).strip().title()
                    if len(potential_model) < 25 and len(potential_model.split()) < 4: filters['model'] = potential_model
            except ValueError: pass

        # Types/Transmission
        if 'elektrik' in info_lower: filters['engine_type'] = 'Elektrik'
        elif 'dizel' in info_lower: filters['engine_type'] = 'Dizel'
        elif 'benzin' in info_lower: filters['engine_type'] = 'Benzin'
        elif 'hibrit' in info_lower: filters['engine_type'] = 'Hibrit'
        if 'suv' in info_lower: filters['body_type'] = 'SUV'
        elif 'sedan' in info_lower: filters['body_type'] = 'Sedan'
        elif 'hatchback' in info_lower or 'hb' in info_lower: filters['body_type'] = 'Hatchback'
        if 'otomatik' in info_lower: filters['transmission'] = 'Otomatik'
        elif 'manuel' in info_lower: filters['transmission'] = 'Manuel'
        log.debug(f"Parsed filters from desired_car_info '{desired_info}': {filters}")
        return filters

    def _handle_immediate_actions(self, entities: Dict[str, Any]) -> bool:
        """Handles actions like reset, farewell, greeting, list_all requiring immediate response."""
        action_taken = False; response = None; action = None
        if entities.get('is_reset', False): action = "reset"; self._reset_context(); response = self.RESPONSE_TEMPLATES["confirm_reset"]; action_taken = True
        elif entities.get('is_farewell', False): action = "farewell"; response = self.RESPONSE_TEMPLATES["farewell"]; action_taken = True
        elif entities.get('is_greeting', False) and not self.current_context.get('initial_personalized_greeting_done'):
             is_context_empty = not any(f for f in self.current_context['filters'].values() if f is not None)
             if is_context_empty and self.current_context.get('customer_id') is None: action = "greeting"; response = self.RESPONSE_TEMPLATES["greeting"]; action_taken = True
             else: log.debug("Greeting ignored: context not empty or personalized done.")
        elif entities.get('is_list_all', False):
             filter_keys = self.SEARCH_TRIGGER_FIELDS | {'min_price', 'max_price', 'min_year', 'max_year', 'brand', 'model'}
             has_other_filters = any(entities.get(k) for k in filter_keys if entities.get(k) is not None)
             if not has_other_filters: action = "list_all"; self._execute_action(action, "<<LIST_ALL>>", entities); action_taken = True # execute sets response
             else: log.info("List all ignored due to other filters.")

        if action_taken:
            if action != 'list_all' and response: self.current_context['last_response'] = response
            if not self.current_context.get('last_response'): self.current_context['last_response'] = self.RESPONSE_TEMPLATES['generic_fallback']
            log.info(f"Immediate action '{action}' handled. Response: {self.current_context['last_response'][:100]}...")
        return action_taken

    def _execute_action(self, action: str, user_message: str, entities: Dict[str, Any]):
        """Executes the determined dialogue action."""
        # Reset turn flags unless handling model confirmation
        if action != "handle_model_confirmation":
             self.current_context['search_performed'] = False; self.current_context['results_shown'] = False
        # Clear similarity context unless finding similar
        if action != "find_similar":
             self.current_context['last_shown_cars'] = None; self.current_context['last_shown_target_price'] = None
             self.current_context['last_shown_target_model'] = None; self.current_context['last_shown_target_brand'] = None
        # Clear model clarification context unless actively clarifying/handling
        if action not in ["clarify_model", "handle_model_confirmation"]:
             self.current_context['potential_model_matches'] = None; self.current_context['awaiting_model_confirmation'] = False

        response = self.RESPONSE_TEMPLATES["generic_fallback"] # Default

        # --- Action Execution Logic ---
        if action == "search":
            active_filters = {k: v for k, v in self.current_context['filters'].items() if v is not None and (hasattr(Car, k.replace('min_','').replace('max_','')) or k in ['min_price','max_price','min_year','max_year'])}
            if active_filters.get('model') and not active_filters.get('brand'): log.warning("Search called with model but no brand. Redirecting to clarify."); action = "clarify_model"
            elif not active_filters: log.info("Search called with no active filters. Asking."); action = "ask"
            else:
                log.info(f"Executing search. Filters: {active_filters}")
                found_cars = find_cars_by_criteria(self.db, filters=active_filters, limit=5)
                self.current_context['search_performed'] = True
                criteria_summary = self._get_criteria_summary()
                alt_suggestion = self._get_alternative_model_suggestion(self.current_context['filters'].get('brand'), self.current_context['filters'].get('model'))
                if found_cars:
                    car_details_str = self._format_car_details(found_cars); self.current_context['results_shown'] = True
                    response = self.RESPONSE_TEMPLATES["show_results"].format(criteria_summary=criteria_summary, car_details=car_details_str, alternative_suggestion=alt_suggestion)
                    first_car = found_cars[0] # Safe access after check
                    self.current_context['last_shown_cars'] = found_cars; self.current_context['last_shown_target_price'] = first_car.price
                    self.current_context['last_shown_target_model'] = first_car.model; self.current_context['last_shown_target_brand'] = first_car.brand
                    log.info(f"Search successful. Stored similarity context.")
                else:
                    response = self.RESPONSE_TEMPLATES["no_results"].format(criteria_summary=criteria_summary, alternative_suggestion_onerror=alt_suggestion)
                    self.current_context['results_shown'] = False

        if action == "ask": # Handle if action is 'ask' or changed to 'ask'
            next_question = self._get_next_question()
            if next_question:
                 # Mark the question as asked *when it is generated*
                 if self.current_context['last_question_key'] in self.FILTER_QUESTIONS:
                       _, asked_flag, _ = self.FILTER_QUESTIONS[self.current_context['last_question_key']]
                       self.current_context['asked_questions'].add(asked_flag); log.debug(f"Marked '{asked_flag}' as asked.")
                 current_ack = self.current_context.get("last_acknowledged_info")
                 if current_ack: response = self.RESPONSE_TEMPLATES["acknowledge_and_ask"].format(acknowledged_info=current_ack, question=next_question); self.current_context["last_acknowledged_info"] = None
                 else: response = self.RESPONSE_TEMPLATES["ask_next_question"].format(question=next_question)
            else: # No more questions
                 log.warning("Action 'ask', but no more questions.")
                 if self._should_search() and not self.current_context.get('search_performed'):
                     criteria_summary = self._get_criteria_summary()
                     response = f"Anladım ({criteria_summary}). Bu kriterlere uygun araçları listeleyebilirim ('listele') veya aramayı sıfırlayabiliriz ('reset')."
                 else: response = self.RESPONSE_TEMPLATES["generic_fallback"] + " Başka nasıl yardımcı olabilirim? ('reset' ile sıfırlayabilirsiniz)"

        elif action == "list_all":
             log.info("Executing list all.")
             found_cars = find_cars_by_criteria(self.db, filters={}, limit=5)
             self.current_context['search_performed'] = True
             alt_suggestion = self._get_alternative_model_suggestion(None, None)
             if found_cars:
                 car_details_str = self._format_car_details(found_cars); self.current_context['results_shown'] = True
                 response = f"İşte envanterimizdeki araçlardan bazıları:\n{car_details_str}\n\n{alt_suggestion}Filtreleme yapmak isterseniz kriter belirtebilirsiniz."
             else: response = "Üzgünüm, envanterde listelenecek araç bulunmuyor."; self.current_context['results_shown'] = False

        elif action == "find_similar":
             log.info("Executing find_similar.")
             target_price = self.current_context.get('last_shown_target_price'); exclude_model = self.current_context.get('last_shown_target_model'); exclude_brand = self.current_context.get('last_shown_target_brand')
             if target_price is not None and exclude_model and exclude_brand:
                 target_car_name = f"{exclude_brand} {exclude_model}"; target_car_price_str = f"{target_price:,.0f} TL"
                 similar_cars = find_similar_priced_cars(self.db, target_price, exclude_brand, exclude_model, 0.15, 5)
                 self.current_context['search_performed'] = True
                 if similar_cars:
                     similar_details_str = self._format_car_details(similar_cars); self.current_context['results_shown'] = True
                     response = self.RESPONSE_TEMPLATES["show_similar_results"].format(target_car_name=target_car_name, target_car_price=target_car_price_str, similar_car_details=similar_details_str)
                 else: response = self.RESPONSE_TEMPLATES["no_similar_results"].format(target_car_name=target_car_name, target_car_price=target_car_price_str); self.current_context['results_shown'] = False
             else: log.error("find_similar failed: context missing."); response = self.RESPONSE_TEMPLATES["similarity_context_missing"]; self.current_context['results_shown'] = False

        if action == "clarify_model": # Handle if action is 'clarify_model' or changed to it
            model_name = self.current_context['filters'].get('model')
            log.info(f"Executing clarify_model for: {model_name}")
            if not model_name: response = self.RESPONSE_TEMPLATES["generic_fallback"] # Fallback if no model
            else:
                clarification_filters = {k: v for k, v in self.current_context['filters'].items() if v is not None and k != 'brand'}
                clarification_filters['model'] = model_name
                log.debug(f"Clarification search filters: {clarification_filters}")
                found_cars = find_cars_by_criteria(self.db, filters=clarification_filters, limit=3)
                if found_cars:
                    self.current_context['potential_model_matches'] = found_cars; self.current_context['awaiting_model_confirmation'] = True
                    if len(found_cars) == 1: car_details_str = self._format_single_car_detail(found_cars[0]); response = self.RESPONSE_TEMPLATES["confirm_model_match"].format(model_name=model_name.title(), car_details=car_details_str)
                    else: car_details_str = self._format_car_details(found_cars); response = self.RESPONSE_TEMPLATES["confirm_multiple_model_match"].format(model_name=model_name.title(), car_details=car_details_str)
                    log.info(f"Found {len(found_cars)} potential matches. Asking confirmation.")
                else:
                    response = self.RESPONSE_TEMPLATES["model_not_found_ask_brand"].format(model_name=model_name.title())
                    if hasattr(Car, 'model'): self.current_context['filters']['model'] = None # Clear ambiguous model
                    self.current_context['awaiting_model_confirmation'] = False; self.current_context['potential_model_matches'] = None # Reset state

        elif action == "handle_model_confirmation":
             confirmation = entities.get('confirmation'); potential_matches = self.current_context.get('potential_model_matches')
             log.info(f"Executing handle_model_confirmation. Confirmation: {confirmation}")
             if confirmation == 'yes' and potential_matches:
                 # Assume first match for simplicity
                 confirmed_car = potential_matches[0]
                 confirmed_brand = confirmed_car.brand; confirmed_model = confirmed_car.model
                 log.info(f"User confirmed model: {confirmed_brand} {confirmed_model}")

                 # Update context filters
                 self.current_context['filters']['brand'] = confirmed_brand
                 self.current_context['filters']['model'] = confirmed_model

                 # Correctly mark brand and model questions as implicitly answered
                 if 'brand' in self.FILTER_QUESTIONS: # Check key exists
                     _, asked_flag_brand, _ = self.FILTER_QUESTIONS['brand']
                     self.current_context['asked_questions'].add(asked_flag_brand)
                     log.debug(f"Marked '{asked_flag_brand}' as implicitly answered.")
                 if 'model' in self.FILTER_QUESTIONS: # Check key exists
                     _, asked_flag_model, _ = self.FILTER_QUESTIONS['model']
                     self.current_context['asked_questions'].add(asked_flag_model)
                     log.debug(f"Marked '{asked_flag_model}' as implicitly answered.")

                 # Determine next step
                 next_q = self._get_next_question()
                 search_prompt = ""
                 if self._should_search() and not self.current_context.get('search_performed'):
                     search_prompt = " İsterseniz bu kritere uygun araçları şimdi listeleyebilirim veya başka özellik ekleyebilirsiniz."

                 question_or_prompt = next_q or search_prompt or "Başka nasıl yardımcı olabilirim?"

                 response = self.RESPONSE_TEMPLATES["confirmation_acknowledge_ask_next"].format(
                     confirmed_brand=confirmed_brand,
                     confirmed_model=confirmed_model,
                     next_question_or_search_prompt=question_or_prompt
                 )
                 # Note: next_q is not marked asked here; the 'ask' action handles that.

             elif confirmation == 'no':
                 log.info("User denied model match.")
                 if hasattr(Car, 'model'): self.current_context['filters']['model'] = None; # Clear ambiguous model
                 response = self.RESPONSE_TEMPLATES["clarification_needed_after_no"]
             else: # Ambiguous response
                 log.warning("Ambiguous response during confirmation.")
                 if hasattr(Car, 'model'): self.current_context['filters']['model'] = None; # Clear ambiguous model
                 response = self.RESPONSE_TEMPLATES["clarification_needed_after_no"] + " Lütfen 'evet'/'hayır' ile yanıtlayın veya yeni marka/model belirtin."

             # Reset confirmation state after handling
             self.current_context['awaiting_model_confirmation'] = False
             self.current_context['potential_model_matches'] = None

        elif action == "wait":
             if 'last_response' not in self.current_context or not self.current_context['last_response']: log.warning("Action 'wait' but no response set. Using fallback."); response = self.RESPONSE_TEMPLATES["generic_fallback"]
             else: response = self.current_context['last_response']
             log.debug("Action: Wait. Using pre-set response.")

        # Store the final determined response in the context if the action wasn't 'wait'
        # and wasn't handled by an immediate action function that already set it.
        if action not in ['wait', 'reset', 'farewell', 'greeting', 'list_all']:
             self.current_context['last_response'] = response
        # If action was immediate or wait, the response should already be in context or set directly
        elif action == 'wait': pass # Already has the correct response
        elif self.current_context.get('last_response'): pass # Immediate actions already set it
        else: self.current_context['last_response'] = response # Fallback if something unexpected happened

    # --- End Helper Methods ---

# --- END OF FILE agent.py ---