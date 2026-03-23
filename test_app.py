import pytest
from app.routes import app

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_index_route(client):
    """Test that the home page loads."""
    rv = client.get('/')
    assert rv.status_code == 200
    assert b"Lecture" in rv.data # Assumes 'Lecture' is in your title

def test_status_poll_not_found(client):
    """Test polling a non-existent video ID."""
    # Using a valid-format but non-existent ObjectId
    rv = client.get('/status-poll/65f1a5b2e4b0a1a2b3c4d5e6')
    assert rv.status_code == 404