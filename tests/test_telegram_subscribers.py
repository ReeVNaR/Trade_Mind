import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from main import app
from app.database.session import SessionLocal, init_db
from app.database.models import TelegramSubscriber
from app.telegram.bot import TelegramService


@pytest.fixture(autouse=True)
def clean_subscribers_db():
    init_db()
    db = SessionLocal()
    db.query(TelegramSubscriber).delete()
    db.commit()
    db.close()


def test_register_and_toggle_subscriber():
    """Verify registration, retrieval, and deactivation of Telegram bot users."""
    tg = TelegramService()

    # 1. Register User 1
    res1 = tg.register_or_update_subscriber(
        chat_id="111222333",
        username="trader_bob",
        first_name="Bob",
        is_active=True
    )
    assert res1 is True

    # 2. Register User 2
    res2 = tg.register_or_update_subscriber(
        chat_id="444555666",
        username="alice_nifty",
        first_name="Alice",
        is_active=True
    )
    assert res2 is True

    # 3. Retrieve all active subscribers
    active_chat_ids = tg.get_active_chat_ids()
    assert "111222333" in active_chat_ids
    assert "444555666" in active_chat_ids

    # 4. User 1 sends /stop (unsubscribe)
    tg.register_or_update_subscriber(chat_id="111222333", is_active=False)
    updated_active = tg.get_active_chat_ids()
    assert "111222333" not in updated_active
    assert "444555666" in updated_active

    # 5. User 1 sends /start again (resubscribe)
    tg.register_or_update_subscriber(chat_id="111222333", is_active=True)
    resubscribed = tg.get_active_chat_ids()
    assert "111222333" in resubscribed


def test_broadcast_message_to_all_subscribers():
    """Verify that send_message broadcasts to all active subscribed users."""
    tg = TelegramService()
    tg.token = "mock_token_123"

    # Register 3 distinct subscribers
    tg.register_or_update_subscriber(chat_id="user_1", username="u1", is_active=True)
    tg.register_or_update_subscriber(chat_id="user_2", username="u2", is_active=True)
    tg.register_or_update_subscriber(chat_id="user_3", username="u3", is_active=False)  # Unsubscribed

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"ok": True}

    with patch("requests.post", return_value=mock_response) as mock_post:
        # Broadcast message (no specific chat_id provided)
        success = tg.send_message("⚡ NIFTY 50 Breakout Alert")
        assert success is True

        # Should be called for active subscribers (user_1, user_2)
        called_chat_ids = [call.kwargs["json"]["chat_id"] for call in mock_post.call_args_list]
        assert "user_1" in called_chat_ids
        assert "user_2" in called_chat_ids
        assert "user_3" not in called_chat_ids


def test_telegram_subscribers_api_endpoints():
    """Verify /api/telegram/subscribers and /api/telegram/broadcast REST endpoints."""
    tg = TelegramService()
    tg.register_or_update_subscriber(chat_id="user_api_1", username="testuser", is_active=True)

    client = TestClient(app)
    
    # 1. Test GET /api/telegram/subscribers
    res = client.get("/api/telegram/subscribers")
    assert res.status_code == 200
    data = res.json()
    assert data["total_subscribers"] >= 1
    assert data["active_subscribers"] >= 1
    assert any(s["chat_id"] == "user_api_1" for s in data["subscribers"])

    # 2. Test POST /api/telegram/broadcast
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = {"ok": True}

    with patch("requests.post", return_value=mock_res):
        broadcast_res = client.post("/api/telegram/broadcast", json={"message": "System Maintenance Notice"})
        assert broadcast_res.status_code == 200
        b_data = broadcast_res.json()
        assert b_data["success"] is True
        assert b_data["recipients_count"] >= 1


def test_subscribers_command_admin_only_access():
    """Verify /subscribers is accessible ONLY to CHAT_ID 8765494577 and denied for other users."""
    tg = TelegramService()
    tg.token = "mock_token_123"
    tg.chat_id = "8765494577"

    # Register subscribers
    tg.register_or_update_subscriber(chat_id="8765494577", username="admin_ranve", is_active=True)
    tg.register_or_update_subscriber(chat_id="999888777", username="regular_user", is_active=True)

    sent_messages = {}

    def fake_send(text, chat_id=None):
        sent_messages[chat_id] = text
        return True

    with patch.object(tg, "send_message", side_effect=fake_send):
        # 1. Non-admin executes /subscribers
        tg._process_user_command("999888777", "/subscribers", {"username": "regular_user"})
        assert "999888777" in sent_messages
        assert "Access Denied" in sent_messages["999888777"]
        assert "Subscribers Roster" not in sent_messages["999888777"]

        # 2. Admin (8765494577) executes /subscribers
        tg._process_user_command("8765494577", "/subscribers", {"username": "admin_ranve"})
        assert "8765494577" in sent_messages
        assert "Access Denied" not in sent_messages["8765494577"]
        assert "SUBSCRIBER MANAGEMENT (ADMIN)" in sent_messages["8765494577"]
        assert "8765494577" in sent_messages["8765494577"]
        assert "999888777" in sent_messages["8765494577"]

