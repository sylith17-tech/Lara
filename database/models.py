import enum
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Text, Enum
from sqlalchemy.orm import relationship
from database.db import Base

class RoleEnum(str, enum.Enum):
    MEMBER = "MEMBER"
    ADMIN = "ADMIN"
    OWNER = "OWNER"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    is_admin = Column(Boolean, default=False)

class Group(Base):
    __tablename__ = "groups"
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    title = Column(String, nullable=False)
    is_premium = Column(Boolean, default=False)

class GroupMember(Base):
    __tablename__ = "group_members"
    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role = Column(Enum(RoleEnum), default=RoleEnum.MEMBER)

class CustomResponse(Base):
    __tablename__ = "custom_responses"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trigger = Column(String, unique=True, nullable=False)
    response = Column(Text, nullable=False)
