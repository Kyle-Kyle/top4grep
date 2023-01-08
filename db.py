from sqlalchemy import Column, String, Integer, Boolean, ForeignKey, Table, Enum
from sqlalchemy.orm import relation, relationship
from sqlalchemy.types import LargeBinary
from sqlalchemy.ext.declarative import declarative_base, declared_attr

class BaseTable:
    @declared_attr
    def __tablename__(cls):
        return cls.__name__.lower()
    id = Column(Integer, primary_key=True)

Base = declarative_base(cls=BaseTable)

class Paper(Base):
    conference = Column(String)
    year = Column(Integer)
    title = Column(String)
    authors = Column(String)
    abstract = Column(String)

    def __repr__(self):
        return f"{self.year}: {self.title}"
