import pytest
from fastapi.testclient import TestClient

from rssapi.main import app


@pytest.fixture(scope='module')
def client():
    with TestClient(app) as client:
        yield client


def test_1024_day(client: TestClient):
    response = client.get('/api/rss/1024.day/newest')
    assert response.status_code == 200
    assert response.json()['items']


def test_jsonfeed_example(client: TestClient):
    response = client.get('/api/rss/jsonfeed/example')
    assert response.status_code == 200
    assert response.json()['items']


def test_go_fans(client: TestClient):
    response = client.get('/api/rss/gofans/iOS')
    assert response.status_code == 200
    assert response.json()['items']

    response = client.get('/api/rss/gofans/macOS')
    assert response.status_code == 200
    assert response.json()['items']


def test_loon(client: TestClient):
    response = client.get(
        '/api/rss/loon/ipx', params={'url_list': ['https://kelee.one/Tool/Loon/Lpx/YouTube_remove_ads.lpx']}
    )
    assert response.status_code == 200
    assert response.json()['items']


def test_nodeseek_category(client: TestClient):
    response = client.get('/api/rss/nodeseek/category/tech')
    assert response.status_code == 200
    assert response.json()['items']


def test_readhub(client: TestClient):
    response = client.get('/api/rss/readhub/daily')
    assert response.status_code == 200
    assert response.json()['items']


def test_telegram_channel(client: TestClient):
    response = client.get('/api/rss/telegram/channel', params={'channels': ['JISFW']})
    assert response.status_code == 200
    assert response.json()['items']
