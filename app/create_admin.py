from typing import Optional
from flask import Flask
from models import db, User

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

def create_admin_user() -> None:
    """Create admin user if it doesn't exist."""
    with app.app_context():
        # Remover usuário admin existente
        admin: Optional[User] = User.query.filter_by(username='admin').first()
        if admin:
            db.session.delete(admin)
            db.session.commit()
        
        # Criar novo usuário admin
        new_admin = User(username='admin', role='admin')
        new_admin.set_password('admin123')
        db.session.add(new_admin)
        db.session.commit()
        print("Admin user created successfully!")

if __name__ == '__main__':
    create_admin_user() 