from app.routes import app

if __name__ == "__main__":
    # In production on EC2, you'll use Gunicorn, but for now:
    app.run(host='0.0.0.0', port=5000)