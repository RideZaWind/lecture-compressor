from app.routes import app

if __name__ == "__main__":
    # In production on EC2, you'll use Gunicorn, but for now:
    app.run(debug=True, port=5000)