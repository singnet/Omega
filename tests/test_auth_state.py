from concurrent.futures import ThreadPoolExecutor

from proxy.auth_state import handle


def test_concurrent_bindings_commit_one_owner(tmp_path):
    def bind(user):
        result = handle(tmp_path, "/auth/bind", {"channel_identifier": "IRC", "user_id": user},
                        "secret", "secret")
        return user, result["result"]

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(bind, ("one", "two", "three", "four")))

    state = handle(tmp_path, "/auth/state", {"channel_identifier": "IRC"}, "", "secret")
    assert [user for user, result in results if result == "auth_bound"] == [state["owner_id"]]
    assert sum(result == "ignore" for _, result in results) == 3


def test_group_binding_requires_matching_telegram_update(tmp_path, monkeypatch):
    from proxy import auth_state

    pending = []
    def publish(sender, chat, chat_type, text):
        update_id = len(pending) + 1
        pending.append({"update_id": update_id, "message": {
            "from": {"id": sender}, "chat": {"id": chat, "type": chat_type}, "text": text}})
        return update_id

    def telegram_api(method):
        if method == "getMe":
            return {"username": "OmegaBot"}
        assert method == "getUpdates"
        return pending

    monkeypatch.setattr(auth_state, "telegram_api", telegram_api)
    def request(route, **fields):
        return handle(tmp_path, "/auth/" + route, {"channel_identifier": "TELEGRAM", **fields},
                      "secret", "secret")["result"]

    publish(12, -20, "group", "auth secret")
    assert request("bind", user_id="12") == "ignore"
    publish(12, 12, "private", "auth secret")
    assert request("bind", user_id="12") == "auth_bound"

    fields = {"group_id": "-20", "requester_user_id": "12"}
    for sender, chat, command in [(13, -20, "/bind"), (12, -30, "/bind"), (12, -20, "/bind@OtherBot")]:
        update_id = publish(sender, chat, "group", command)
        assert request("group/authorize", update_id=update_id, **fields) == "ignore"

    bind_id = publish(12, -20, "supergroup", "/authorize_group@OmegaBot")
    assert request("group/authorize", update_id=bind_id, **fields) == "group_bound"
    revoke_id = publish(12, 12, "private", "/unbind -20")
    assert request("group/revoke", update_id=revoke_id, **fields) == "group_unbound"
    assert request("group/authorize", update_id=bind_id, **fields) == "ignore"
