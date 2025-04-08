# --- START OF FILE chatbot_logic.py ---

from sqlalchemy.orm import Session, joinedload # joinedload'u import et
from models import Brand, Model, Variant, UserQuery # Güncellenmiş modelleri import et
from sqlalchemy import func, and_, DECIMAL
from datetime import datetime
import re
from typing import List, Optional
import decimal # Python'un decimal tipi için gerekebilir

# --- Database Interaction Functions (Updated Queries) ---

def db_list_brands(db: Session) -> List[str]:
    """Fetches available car brands from the database."""
    try:
        brands = db.query(Brand.Name).order_by(Brand.Name).all()
        return [brand[0] for brand in brands]
    except Exception as e:
        print(f"DB HATA (list_brands): {e}")
        return []

def db_list_models(db: Session, brand_name: str) -> List[str]:
    """Fetches models for a specific brand from the database."""
    try:
        brand_name_cap = brand_name.title()
        models = db.query(Model.Name)\
                 .join(Brand, Model.BrandID == Brand.BrandID)\
                 .filter(Brand.Name == brand_name_cap)\
                 .order_by(Model.Name)\
                 .all()
        return [model[0] for model in models]
    except Exception as e:
        print(f"DB HATA (list_models for {brand_name}): {e}")
        return []

def db_get_model_variants(db: Session, brand_name: str, model_name: str) -> List[Variant]:
    """Fetches variants for a specific model from the database."""
    try:
        brand_name_cap = brand_name.title()
        model_name_cap = model_name.title()
        # İlişkileri önceden yükleyerek N+1 sorgu sorununu önle
        variants = db.query(Variant)\
                     .join(Model, Variant.ModelID == Model.ModelID)\
                     .join(Brand, Model.BrandID == Brand.BrandID)\
                     .filter(and_(Brand.Name == brand_name_cap, Model.Name == model_name_cap))\
                     .options(joinedload(Variant.Model).joinedload(Model.Brand))\
                     .order_by(Variant.Year.desc(), Variant.Price)\
                     .all()
        return variants
    except Exception as e:
        print(f"DB HATA (get_model_variants for {brand_name} {model_name}): {e}")
        return []

def db_get_average_price(db: Session, brand_name: str, model_name: str) -> Optional[float]:
    """Calculates the average price for variants of a specific model."""
    try:
        brand_name_cap = brand_name.title()
        model_name_cap = model_name.title()
        avg_price_decimal = db.query(func.avg(Variant.Price))\
                      .join(Model, Variant.ModelID == Model.ModelID)\
                      .join(Brand, Model.BrandID == Brand.BrandID)\
                      .filter(and_(Brand.Name == brand_name_cap, Model.Name == model_name_cap))\
                      .scalar()
        # avg_price_decimal None veya Decimal tipinde olabilir, float'a çevir
        return float(avg_price_decimal) if avg_price_decimal is not None else None
    except Exception as e:
        print(f"DB HATA (get_average_price for {brand_name} {model_name}): {e}")
        return None

def db_get_similar_priced_variants(db: Session, target_price: float, tolerance: float = 0.2, limit: int = 5, exclude_model_id: Optional[int] = None) -> List[Variant]:
    """Finds variants in a similar price range, excluding a specific model if needed."""
    if target_price is None:
        return []
    try:
        # target_price'ı Decimal'e çevirerek veritabanı tipiyle eşleşmesini sağla
        # Bu, özellikle SQL Server gibi hassas ondalık tipleri kullanan DB'lerde önemlidir.
        target_price_decimal = decimal.Decimal(target_price)
        min_price = target_price_decimal * decimal.Decimal(1 - tolerance)
        max_price = target_price_decimal * decimal.Decimal(1 + tolerance)

        query = db.query(Variant)\
                  .join(Model, Variant.ModelID == Model.ModelID)\
                  .join(Brand, Model.BrandID == Brand.BrandID)
        # Eager load relationships
        query = query.options(
                    joinedload(Variant.Model).joinedload(Model.Brand)
                )

        # Filtrelemede Variant.Price (DECIMAL) kullan
        query = query.filter(Variant.Price >= min_price, Variant.Price <= max_price)

        if exclude_model_id:
             query = query.filter(Variant.ModelID != exclude_model_id)

        # Sıralamada Variant.Price (DECIMAL) kullan
        # func.abs'ın Decimal ile çalıştığından emin olalım (genellikle çalışır)
        query = query.order_by(func.abs(Variant.Price - target_price_decimal))

        similar_variants = query.limit(limit).all()
        return similar_variants
    except Exception as e:
        print(f"DB HATA (get_similar_priced_variants target: {target_price}): {e}")
        return []

def log_query(db: Session, query: str, response: str):
    """Logs the user query and the generated response to the database."""
    try:
        timestamp = datetime.utcnow()
        user_query_log = UserQuery(query=query, result=response, timestamp=timestamp)
        db.add(user_query_log)
        db.commit()
    except Exception as e:
        print(f"DB HATA (log_query): {e}")
        db.rollback()

# --- Chatbot State & Logic (No changes needed here) ---
conversation_history = []
current_context = {"brand": None, "model": None, "price": None, "last_model_id": None}

def reset_conversation():
    """Resets the conversation history and context."""
    global conversation_history, current_context
    conversation_history = [
        {
            "role": "system",
            "content": """Sen profesyonel bir araba satış danışmanısın. Veritabanındaki bilgilere göre müşterilere yardımcı ol.
            Adımlar:
            1. Başlangıçta "başlangıç" mesajı  ver sonrasında al.
            2. müşterinin istediği araç tip ve özelliklerini sor
            3. müşterinin istediği özelliklere göre veritabanından araçları listele.
            4. müşteriye veritabanından araç seçtir ve o araç hakkında bilgi ver. 
            5. Nazik ve yardımcı ol. Sadece veritabanında olan bilgilerle yanıt ver."""
        }
    ]
    current_context = {"brand": None, "model": None, "price": None, "last_model_id": None}

# --- process_chat_message (Minor formatting refinement) ---
def process_chat_message(db: Session, user_message: str) -> str:
    """Processes the user message based on conversation state and database info."""
    global conversation_history, current_context
    user_message_lower = user_message.lower().strip()

    if user_message == "başlangıç":
        available_brands = db_list_brands(db)
        if available_brands:
             assistant_response = (
                 "Merhaba! Araba Bilgi Merkezi'ne hoş geldiniz. Size nasıl yardımcı olabilirim? "
                 f"Elimizdeki markalar: {', '.join(available_brands)}. Hangi markayla ilgileniyorsunuz?"
             )
        else:
             assistant_response = "Merhaba! Araba Bilgi Merkezi'ne hoş geldiniz. Şu anda veritabanında kayıtlı marka bulunmuyor."
        conversation_history.append({"role": "assistant", "content": assistant_response})
        return assistant_response

    conversation_history.append({"role": "user", "content": user_message})

    assistant_response = "Üzgünüm, isteğinizi tam olarak anlayamadım. Lütfen tekrar deneyin veya hangi marka ile ilgilendiğinizi belirtin."

    # 1. Check for Reset Command
    if user_message_lower in ["reset", "baştan başla", "sıfırla"]:
        reset_conversation()
        assistant_response = process_chat_message(db, "başlangıç")
        log_query(db, user_message, "Konuşma Sıfırlandı -> " + assistant_response)
        return assistant_response

    # 2. Check for Model selection (if brand is known)
    if current_context["brand"] and not current_context["model"]:
        models_in_brand = db_list_models(db, current_context["brand"])
        found_model = None
        for model_name in models_in_brand:
            if model_name.lower() == user_message_lower:
                found_model = model_name
                break
        if not found_model:
            for model_name in models_in_brand:
                if re.search(r'\b' + re.escape(model_name.lower()) + r'\b', user_message_lower):
                    found_model = model_name
                    break

        if found_model:
            current_context["model"] = found_model
            # Modelleri alırken eager loading yapıldığından emin olalım (db_get_model_variants güncellendi)
            variants = db_get_model_variants(db, current_context["brand"], current_context["model"])
            avg_price = db_get_average_price(db, current_context["brand"], current_context["model"])
            current_context["price"] = avg_price
            # ModelID'yi güvenli bir şekilde al
            current_context["last_model_id"] = variants[0].ModelID if variants else None

            if variants:
                response_lines = [f"Harika seçim! {current_context['brand']} {current_context['model']} modeline ait bilgiler:"]
                if avg_price:
                    response_lines.append(f"  Ortalama Fiyatı: {avg_price:,.2f} TL") # .2f formatı
                response_lines.append("  Bulunan Varyantlar:")
                for variant in variants:
                    # Fiyatı formatlarken None kontrolü yapmaya gerek yok çünkü DB'de nullable=False
                    details = f"  - {variant.Year} / {variant.Engine or 'N/A'} / {variant.FuelType or 'N/A'} / {variant.Transmission or 'N/A'} - Fiyat: {variant.Price:,.2f} TL"
                    response_lines.append(details)
                response_lines.append("\nBu araçla ilgili başka sorunuz var mı, yoksa benzer fiyatlı alternatifleri mi görmek istersiniz?")
                assistant_response = "\n".join(response_lines)
            else:
                assistant_response = f"Üzgünüm, {current_context['brand']} {current_context['model']} için veritabanında detaylı varyant bilgisi bulamadım. Bu marka için diğer modeller şunlar: {', '.join(models_in_brand)}. Başka bir model denemek ister misiniz?"
                current_context["model"] = None
                current_context["price"] = None
                current_context["last_model_id"] = None

    # 3. Check for Brand selection
    elif not current_context["brand"]:
        available_brands = db_list_brands(db)
        found_brand = None
        for brand_name in available_brands:
            if brand_name.lower() == user_message_lower:
                found_brand = brand_name
                break
        if not found_brand:
            for brand_name in available_brands:
                # Renault için özel durumu koru
                if re.search(r'\b' + re.escape(brand_name.lower()) + r'\b', user_message_lower) or \
                   (brand_name.lower() == "renault" and "reno" in user_message_lower):
                    found_brand = brand_name
                    break

        if found_brand:
            current_context["brand"] = found_brand
            models = db_list_models(db, current_context["brand"])
            if models:
                assistant_response = (
                    f"Tamam, {current_context['brand']} markasını seçtiniz. Bu markadaki modellerimiz şunlardır:\n" +
                    "\n".join(f"- {model}" for model in models) +
                    "\n\nHangi model hakkında bilgi almak istersiniz?"
                )
            else:
                assistant_response = f"Üzgünüm, {current_context['brand']} markası için veritabanında model bulunamadı. Lütfen şu markalardan birini seçin: {', '.join(available_brands)}"
                current_context["brand"] = None

    # 4. Check for "Similar Cars" request
    elif "benzer" in user_message_lower or "alternatif" in user_message_lower:
        # Hem avg_price hem de model bağlamının olduğundan emin ol
        if current_context["price"] and current_context["model"] and current_context["last_model_id"] is not None:
            similar_variants = db_get_similar_priced_variants(
                db,
                current_context["price"], # float olarak gönderiyoruz
                exclude_model_id=current_context["last_model_id"]
            )
            if similar_variants:
                avg_price_formatted = f"{current_context['price']:,.2f}" # format avg price
                response_lines = [f"{current_context['brand']} {current_context['model']} (~{avg_price_formatted} TL) modeline benzer fiyattaki araç önerilerimiz:"]
                for variant in similar_variants:
                    # Eager loading sayesinde ilişkili verilere erişim daha güvenli olmalı
                    brand_name = variant.Model.Brand.Name if variant.Model and variant.Model.Brand else "Bilinmeyen Marka"
                    model_name = variant.Model.Name if variant.Model else "Bilinmeyen Model"
                    response_lines.append(
                        f"- {brand_name} {model_name} ({variant.Year}) - Yaklaşık Fiyat: {variant.Price:,.2f} TL"
                    )
                response_lines.append("\nBu araçlardan biri hakkında detaylı bilgi ister misiniz? (Marka ve modelini yazmanız yeterli)")
                assistant_response = "\n".join(response_lines)
                # Reset context after showing alternatives
                current_context["brand"] = None
                current_context["model"] = None
                current_context["price"] = None
                current_context["last_model_id"] = None
            else:
                avg_price_formatted = f"{current_context['price']:,.2f}"
                assistant_response = f"Üzgünüm, {avg_price_formatted} TL civarında {current_context['brand']} {current_context['model']} dışında başka uygun alternatif bulunamadı."
        elif current_context["brand"] and not current_context["model"]:
             assistant_response = "Lütfen önce hangi modelle ilgilendiğinizi belirtin, sonra benzerlerini bulabilirim."
        else:
            assistant_response = "Hangi araca benzer alternatifler aradığınızı anlayabilmem için lütfen önce bir marka ve model hakkında bilgi isteyin."

    # 5. Fallback
    elif not current_context["brand"]:
         available_brands = db_list_brands(db)
         if available_brands:
             assistant_response = (
                 f"Size nasıl yardımcı olabilirim? Elimdeki markalar: {', '.join(available_brands)}. Hangi markayla ilgileniyorsunuz?"
             )
         else:
             assistant_response = "Şu anda veritabanında kayıtlı marka bulunmuyor. Daha sonra tekrar kontrol edebilirsiniz."

    conversation_history.append({"role": "assistant", "content": assistant_response})
    log_query(db, user_message, assistant_response)
    return assistant_response

# --- END OF FILE chatbot_logic.py ---