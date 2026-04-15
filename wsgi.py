from app import app, create_tables

with app.app_context():
    create_tables()

if __name__ == "__main__":
    pass  # app.run removed; use WSGI server
