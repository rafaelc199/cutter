from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from typing import Optional, Any
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    """User model for authentication."""
    
    __tablename__ = 'users'
    
    id: int = db.Column(db.Integer, primary_key=True)
    username: str = db.Column(db.String(80), unique=True, nullable=False)
    password_hash: str = db.Column(db.String(128))
    role: str = db.Column(db.String(20), nullable=False, default='user')
    created_at: datetime = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    last_login: Optional[datetime] = db.Column(db.DateTime)

    def __init__(self, username: str, role: str = 'user') -> None:
        """Initialize user."""
        self.username = username
        self.role = role

    def set_password(self, password: str) -> None:
        """Set password hash."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Check password against hash."""
        return check_password_hash(self.password_hash, password)

    def get_id(self) -> str:
        """Return user ID as string."""
        return str(self.id)

    def __repr__(self) -> str:
        """String representation."""
        return f'<User {self.username}>' 