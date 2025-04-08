# --- START OF FILE database.py ---

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from urllib.parse import quote_plus
# Güncellenmiş models dosyasından Base'i import et
from models import Base
import sys
import os # Ortam değişkenleri için
from dotenv import load_dotenv # .env dosyası için

# .env dosyasını yükle (varsa)
load_dotenv()

# --- !! DATABASE CONFIGURATION !! ---
# Ortam değişkenlerinden veya varsayılanlardan al
username = os.getenv("DB_USERNAME", "test")
# Parolayı URL encoding için hazırla
password = quote_plus(os.getenv("DB_PASSWORD", "4325431006")) # Parolayı .env'ye koyun!
server = os.getenv("DB_SERVER", "localhost\\SQLEXPRESS01") # veya sunucu adınız
database = os.getenv("DB_NAME", "araba") # Veritabanı adınız
driver = os.getenv("DB_DRIVER", "ODBC Driver 20 for SQL Server")
# --- !! END DATABASE CONFIGURATION !! ---

# Parola hala varsayılan değerdeyse veya boşsa uyarı ver
if password == quote_plus("YOUR_DB_PASSWORD") or not password:
     print("UYARI: Veritabanı parolası .env dosyasında (DB_PASSWORD) ayarlanmamış veya varsayılan değerde.", file=sys.stderr)
     # Gerekirse burada çıkış yapabilirsiniz: sys.exit(1)

SQLALCHEMY_DATABASE_URL = f"mssql+pyodbc://{username}:{password}@{server}/{database}?driver={driver.replace(' ', '+')}"

engine = None
SessionLocal = None

try:
    engine = create_engine(SQLALCHEMY_DATABASE_URL, fast_executemany=True, echo=False) # echo=True detaylı SQL logları için
    # Bağlantıyı test et
    with engine.connect() as connection:
        print(f"Veritabanı bağlantısı başarılı! ({server}/{database})")
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

except Exception as e:
    print(f"!!! VERİTABANI BAĞLANTI HATASI: {e}", file=sys.stderr)
    print(f"Kontrol edilen bağlantı dizesi (parola gizli): mssql+pyodbc://{username}:<PASSWORD>@{server}/{database}?driver={driver.replace(' ', '+')}", file=sys.stderr)
    print("Lütfen .env dosyasındaki veritabanı ayarlarını (DB_USERNAME, DB_PASSWORD, DB_SERVER, DB_NAME, DB_DRIVER) ve ODBC sürücüsünün kurulu olduğunu kontrol edin.", file=sys.stderr)
    sys.exit(1) # Bağlantı hatasında uygulamayı durdur

def create_db_tables():
    """Veritabanı tablolarını oluşturur (eğer yoksa)."""
    if not engine:
        print("HATA: Veritabanı engine başlatılamadığı için tablolar oluşturulamıyor.", file=sys.stderr)
        return
    print("Veritabanı tabloları kontrol ediliyor/oluşturuluyor (eğer yoksa)...")
    try:
        # Base metadata'sını kullanarak tabloları oluşturur
        Base.metadata.create_all(bind=engine)
        print("Veritabanı tabloları başarıyla kontrol edildi/oluşturuldu.")
    except Exception as e:
        print(f"HATA: Veritabanı tabloları oluşturulurken sorun oluştu: {e}", file=sys.stderr)
        # Burada da çıkış yapılabilir, çünkü tablosuz uygulama çalışmaz
        # sys.exit(1)

# --- END OF FILE database.py ---