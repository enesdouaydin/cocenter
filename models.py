# --- START OF FILE models.py ---

from sqlalchemy import Column, Integer, String, DateTime, DECIMAL, TIMESTAMP, text, Index, UniqueConstraint # UniqueConstraint eklendi
from sqlalchemy.orm import declarative_base
from datetime import datetime
import logging

Base = declarative_base()
log = logging.getLogger(__name__) # Logging eklendi

# Loglama tablosu
class UserQuery(Base):
    __tablename__ = "user_queries"

    id = Column(Integer, primary_key=True, index=True)
    query = Column(String(1000), index=True)
    result = Column(String(4000))
    timestamp = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<UserQuery(id={self.id}, query='{self.query[:50]}...', timestamp='{self.timestamp}')>"

# Ana araba verisi tablosu
class Car(Base):
    __tablename__ = "cars"

    id = Column(Integer, primary_key=True)
    brand = Column(String(255), nullable=False, index=True)
    model = Column(String(255), nullable=False, index=True)
    engine_type = Column(String(100)) # Örn: 'Elektrik', 'Dizel', 'Benzin', 'Hibrit'
    horsepower = Column(Integer) # Örn: 110, 150
    capacity = Column(DECIMAL(4, 1)) # Örn: 1.6, 2.0L motor için DECIMAL(4, 1) veya başka bir sayısal kapasite
    price = Column(DECIMAL(18, 2), nullable=False, index=True)
    currency = Column(String(10), default='TL')
    year = Column(Integer, index=True)
    body_type = Column(String(100), index=True)
    transmission = Column(String(100), index=True)
    created_at = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (Index('ix_cars_brand_model', "brand", "model"), )

    def __repr__(self):
        price_str = f"{self.price:,.2f} {self.currency}" if self.price is not None else "N/A"
        year_str = f" ({self.year})" if self.year else ""
        return f"<Car(id={self.id}, brand='{self.brand}', model='{self.model}'{year_str}, price={price_str})>"

# --- YENİ Müşteri Adayı Tablosu ---
class CustomerLead(Base):
    __tablename__ = "customer_leads"

    id = Column(Integer, primary_key=True, index=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100)) # Soyisim opsiyonel olabilir
    phone = Column(String(20), nullable=False, index=True) # Telefon numarası indexlenmeli
    desired_car_info = Column(String(500)) # Kullanıcının ilk belirttiği araç tipi/özellikleri
    timestamp = Column(DateTime, default=datetime.utcnow, index=True) # Ne zaman eklendiği

    # Telefon numarasının unique olmasını sağlayabiliriz (opsiyonel)
    __table_args__ = (UniqueConstraint('phone', name='uq_customer_leads_phone'), )

    def __repr__(self):
        return f"<CustomerLead(id={self.id}, name='{self.first_name} {self.last_name}', phone='{self.phone}', desired='{self.desired_car_info[:50]}...')>"

# --- END OF FILE models.py ---