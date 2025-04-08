# --- START OF FILE db_utils.py ---

from sqlalchemy.orm import Session
from models import Car, CustomerLead # CustomerLead modelini import et
from sqlalchemy import func, distinct, and_, or_, DECIMAL, asc, desc, cast, String, Integer, text # text eklendi
from typing import List, Optional, Dict, Any
import decimal
import logging
import re # Regex for price extraction if needed later

log = logging.getLogger(__name__)

# --- Mevcut Fonksiyonlar ---
def get_distinct_brands(db: Session) -> List[str]:
    """Veritabanındaki farklı marka isimlerini alfabetik olarak çeker."""
    try:
        brands_query = db.query(distinct(Car.brand))\
                         .filter(Car.brand.isnot(None), Car.brand != '')\
                         .order_by(asc(Car.brand))\
                         .all()
        return [brand[0] for brand in brands_query]
    except Exception as e:
        log.error(f"DB HATA (get_distinct_brands): {e}", exc_info=True)
        return []

# --- YENİ ESNEK FİLTRELEME FONKSİYONU ---

def find_cars_by_criteria(db: Session, filters: Dict[str, Any],
                          sort_by: str = 'price', sort_order: str = 'asc',
                          limit: Optional[int] = 10) -> List[Car]:
    """
    Verilen kriterlere göre arabaları bulan genel fonksiyon.

    Args:
        db: SQLAlchemy Session.
        filters: Filtre kriterlerini içeren dictionary. Örnekler:
            {'brand': 'Toyota', 'model': 'Corolla'}
            {'engine_type': 'Elektrik'}
            {'min_price': 500000, 'max_price': 750000}
            {'body_type': ['SUV', 'Sedan']} # Liste olarak birden fazla değer
            {'min_year': 2020}
            {'transmission': 'Otomatik'}
            # ... Diğer Car model alanları ...
        sort_by: Sıralama yapılacak alan adı (varsayılan 'price').
        sort_order: Sıralama yönü ('asc' veya 'desc', varsayılan 'asc').
        limit: Döndürülecek maksimum kayıt sayısı.

    Returns:
        Filtrelenmiş Car nesnelerinin listesi.
    """
    try:
        query = db.query(Car)

        log.debug(f"find_cars_by_criteria called with filters: {filters}")

        for key, value in filters.items():
            # None, boş string veya boş liste ise filtreyi atla
            if value is None or value == '' or (isinstance(value, list) and not value):
                continue

            field_name = key
            operator = '=='

            # Handle range filters (min/max)
            if key.startswith('min_'):
                operator = '>='
                field_name = key[4:]
            elif key.startswith('max_'):
                operator = '<='
                field_name = key[4:]

            # Check if the base field exists in the Car model
            if not hasattr(Car, field_name):
                log.warning(f"find_cars_by_criteria: Invalid filter field '{field_name}' (key: {key}). Skipping.")
                continue

            column = getattr(Car, field_name)
            column_type = column.type

            # Apply filter based on operator and value type
            try:
                if isinstance(value, list): # Handle IN operator for lists
                    # Case-insensitive IN for strings
                    if isinstance(column_type, String):
                         query = query.filter(func.lower(column).in_([str(v).lower() for v in value]))
                    else: # Direct IN for other types
                         query = query.filter(column.in_(value))
                elif operator == '>=':
                    # Convert value to appropriate type for comparison
                    if isinstance(column_type, DECIMAL): value = decimal.Decimal(value)
                    elif isinstance(column_type, Integer): value = int(value)
                    query = query.filter(column >= value)
                elif operator == '<=':
                    # Convert value to appropriate type for comparison
                    if isinstance(column_type, DECIMAL): value = decimal.Decimal(value)
                    elif isinstance(column_type, Integer): value = int(value)
                    query = query.filter(column <= value)
                else: # operator == '==' (Exact match)
                    # Case-insensitive match for strings
                    if isinstance(column_type, String):
                        query = query.filter(func.lower(column) == str(value).lower())
                    else: # Direct match for other types
                         # Convert value if necessary
                         if isinstance(column_type, DECIMAL): value = decimal.Decimal(value)
                         elif isinstance(column_type, Integer): value = int(value)
                         query = query.filter(column == value)
            except (ValueError, TypeError, decimal.InvalidOperation) as conv_err:
                 # Log and skip filter if value conversion fails
                 log.warning(f"Filter value conversion error for key '{key}', value '{value}': {conv_err}. Skipping filter.")
                 continue # Skip this specific filter

        # Apply sorting
        if hasattr(Car, sort_by):
            sort_column = getattr(Car, sort_by)
            if sort_order.lower() == 'desc':
                query = query.order_by(desc(sort_column))
            else:
                query = query.order_by(asc(sort_column))
        else:
             # Warn and apply default sorting if sort_by field is invalid
             log.warning(f"find_cars_by_criteria: Invalid sort field '{sort_by}'. Defaulting to price asc.")
             query = query.order_by(asc(Car.price)) # Safe default sorting

        # Apply limit
        if limit:
            query = query.limit(limit)

        # Execute query and get results
        results = query.all()
        log.info(f"{len(results)} cars found matching criteria. Filters: {filters}, Sort: {sort_by} {sort_order}, Limit: {limit}")
        return results

    except Exception as e:
        log.error(f"DB ERROR (find_cars_by_criteria): {e}. Filters: {filters}", exc_info=True)
        return []


# --- Müşteri Adayı Fonksiyonları ---

def find_customer_lead_by_phone(db: Session, phone: str) -> Optional[CustomerLead]:
    """Verilen telefon numarasına sahip müşteri adayını bulur."""
    if not phone:
        return None
    try:
        # Clean the phone number (remove non-digits) - enhance as needed
        cleaned_phone = re.sub(r'\D', '', phone)
        # Further cleaning might be needed depending on DB format consistency
        log.debug(f"Searching for customer lead with cleaned phone: {cleaned_phone}")
        # Search using the cleaned phone number
        # Assumes 'phone' field in DB stores cleaned numbers or handles variations
        customer = db.query(CustomerLead).filter(CustomerLead.phone == cleaned_phone).first()
        if customer:
            log.info(f"Customer lead found for phone {cleaned_phone}: ID {customer.id}")
        else:
            log.info(f"No customer lead found for phone {cleaned_phone}")
        return customer
    except Exception as e:
        log.error(f"DB HATA (find_customer_lead_by_phone for {phone}): {e}", exc_info=True)
        return None

def add_customer_lead(db: Session, first_name: str, last_name: Optional[str], phone: str, desired_car_info: str) -> Optional[CustomerLead]:
    """Yeni bir müşteri adayı ekler veya telefon numarası zaten varsa None döndürür."""
    if not first_name or not phone:
        log.warning("Cannot add customer lead: first_name and phone are required.")
        return None
    try:
        cleaned_phone = re.sub(r'\D', '', phone)
        # Check if a customer with this phone number already exists
        existing = find_customer_lead_by_phone(db, cleaned_phone)
        if existing:
            log.warning(f"Customer lead with phone {cleaned_phone} already exists (ID: {existing.id}). Not adding.")
            # Optionally return the existing customer: return existing
            return None

        # Create and add the new customer lead
        new_lead = CustomerLead(
            first_name=first_name.title(),
            last_name=last_name.title() if last_name else None,
            phone=cleaned_phone, # Store the cleaned phone number
            desired_car_info=desired_car_info
        )
        db.add(new_lead)
        db.commit()
        db.refresh(new_lead) # Get the generated ID
        log.info(f"New customer lead added: ID {new_lead.id}, Name: {new_lead.first_name}, Phone: {new_lead.phone}")
        return new_lead
    except Exception as e:
        # Handle potential integrity errors (like unique constraint violation)
        log.error(f"DB HATA (add_customer_lead): {e}", exc_info=True)
        db.rollback() # Rollback transaction on error
        return None

def get_distinct_models(db: Session, brand: Optional[str] = None, exclude_model: Optional[List[str]] = None, limit: int = 5) -> List[str]:
    """
    Veritabanındaki farklı model isimlerini (isteğe bağlı olarak markaya göre filtrelenmiş
    ve belirli modeller hariç tutulmuş şekilde) çeker.

    Args:
        db: SQLAlchemy Session.
        brand: Filtrelenecek marka adı (opsiyonel).
        exclude_model: Sonuçlardan hariç tutulacak model adları listesi (opsiyonel).
        limit: Döndürülecek maksimum model sayısı.

    Returns:
        Farklı model isimlerinin listesi.
    """
    try:
        query = db.query(distinct(Car.model))\
                  .filter(Car.model.isnot(None), Car.model != '')

        # Filter by brand (case-insensitive) if provided
        if brand:
            query = query.filter(func.lower(Car.brand) == brand.lower())

        # Exclude specific models (case-insensitive) if provided
        if exclude_model:
            exclude_models_lower = [m.lower() for m in exclude_model if m] # Ensure lowercase and filter out None/empty
            if exclude_models_lower:
                 query = query.filter(func.lower(Car.model).notin_(exclude_models_lower))

        # Order alphabetically
        query = query.order_by(asc(Car.model))

        # Apply limit
        if limit:
            query = query.limit(limit)

        # Fetch results
        models_query = query.all()
        models = [model[0] for model in models_query]
        log.debug(f"Found distinct models (Brand: {brand}, Exclude: {exclude_model}, Limit: {limit}): {models}")
        return models
    except Exception as e:
        log.error(f"DB HATA (get_distinct_models): {e}", exc_info=True)
        return []


# --- Benzer Fiyatlı Araçları Bulma Fonksiyonu ---
def find_similar_priced_cars(db: Session, target_price: decimal.Decimal,
                             exclude_brand: Optional[str] = None,
                             exclude_model: Optional[str] = None,
                             tolerance: float = 0.15, # Fiyat toleransı (%15 daha az veya çok)
                             limit: int = 5) -> List[Car]:
    """
    Belirli bir fiyata yakın fiyattaki araçları bulur, istenirse belirli marka/model hariç tutulur.

    Args:
        db: SQLAlchemy Session.
        target_price: Hedef fiyat (Decimal olarak).
        exclude_brand: Hariç tutulacak marka (opsiyonel).
        exclude_model: Hariç tutulacak model (opsiyonel).
        tolerance: Fiyat aralığı toleransı (örn: 0.15 = %15).
        limit: Döndürülecek maksimum araç sayısı.

    Returns:
        Benzer fiyatlı Car nesnelerinin listesi.
    """
    if target_price is None:
        log.warning("find_similar_priced_cars called with target_price=None. Returning empty list.")
        return []

    try:
        # Fiyat aralığını hesapla
        min_price = target_price * (decimal.Decimal(1) - decimal.Decimal(tolerance))
        max_price = target_price * (decimal.Decimal(1) + decimal.Decimal(tolerance))
        log.info(f"Searching for similar priced cars. Target: {target_price:.2f}, Range: {min_price:.2f} - {max_price:.2f}, Tolerance: {tolerance*100}%")

        query = db.query(Car)

        # Fiyat aralığına göre filtrele
        query = query.filter(Car.price >= min_price, Car.price <= max_price)

        # Hariç tutulacak marka/model varsa filtrele (case-insensitive)
        if exclude_brand and exclude_model:
            log.debug(f"Excluding Brand: {exclude_brand}, Model: {exclude_model} from similarity search.")
            # Aynı anda hem marka hem model eşleşeni hariç tut
            query = query.filter(
                ~( (func.lower(Car.brand) == exclude_brand.lower()) & (func.lower(Car.model) == exclude_model.lower()) )
            )
        elif exclude_model: # Sadece model hariç tutuluyorsa (belki aynı markadan farklı model olabilir)
             log.debug(f"Excluding Model: {exclude_model} from similarity search (any brand).")
             query = query.filter(func.lower(Car.model) != exclude_model.lower())


        # Fiyat farkına göre sırala (hedefe en yakın olanlar önce)
        # func.abs'in DECIMAL ile çalıştığından emin olalım (genellikle çalışır)
        query = query.order_by(func.abs(Car.price - target_price))

        # Limit uygula
        query = query.limit(limit)

        # Sonuçları al
        results = query.all()
        log.info(f"{len(results)} similar priced cars found.")
        return results

    except Exception as e:
        log.error(f"DB ERROR (find_similar_priced_cars for target {target_price}): {e}", exc_info=True)
        return []

# --- Rastgele Müşteri Adayı Getirme Fonksiyonu ---
def get_random_customer_lead(db: Session) -> Optional[CustomerLead]:
    """Veritabanından rastgele bir müşteri adayı seçer."""
    random_customer = None # Initialize variable
    try:
        # Attempt using NEWID() for SQL Server (or other DB-specific random function)
        # Using text() for potentially DB-specific functions
        random_customer = db.query(CustomerLead).order_by(text('NEWID()')).first() # Adjust 'NEWID()' if using a different DB like PostgreSQL ('RANDOM()') or MySQL ('RAND()')
        if random_customer:
            log.info(f"Random customer lead selected (using DB specific function): ID {random_customer.id}, Name: {random_customer.first_name}")
        else:
            log.info("No customer leads found in the database to select randomly.")
        return random_customer
    except Exception as e:
        # Fallback for databases that might not support the specific function or if text() fails
        log.warning(f"DB HATA (get_random_customer_lead with DB specific function): {e}. Trying with generic func.random() as fallback.")
        try:
             random_customer = db.query(CustomerLead).order_by(func.random()).first() # Standard SQLAlchemy random
             if random_customer:
                 log.info(f"Random customer lead selected (using func.random()): ID {random_customer.id}, Name: {random_customer.first_name}")
             elif not random_customer: # Check if the first attempt didn't already log no customers
                  log.info("No customer leads found in the database to select randomly (fallback).")
             return random_customer
        except Exception as fallback_e:
             # If fallback also fails, log error and return None
             log.error(f"DB HATA (get_random_customer_lead fallback with func.random()): {fallback_e}", exc_info=True)
             return None


# --- END OF FILE db_utils.py ---