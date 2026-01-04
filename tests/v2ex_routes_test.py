import pytest
from fastapi.testclient import TestClient

from rssapi.main import app


@pytest.fixture(scope='module')
def client():
    with TestClient(app) as client:
        yield client


def test_v2ex_aggregation(client: TestClient):
    response = client.get('/api/rss/jsonfeed/v2ex/aggregation', params={'topics': ['dns']})
    assert response.status_code == 200
    assert response.json()['items']
    assert response.json()['home_page_url'] == 'https://v2ex.com/go/dns'
