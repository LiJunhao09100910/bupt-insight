import json

from core.database import identity
from core.pipeline import database
from core.web import create_app

HOST = "localhost"


def seed(cfg, notice):
    db = database(cfg)
    try:
        db.upsert(notice)
        return db.db.execute("SELECT hash FROM notices WHERE id=?", (identity(notice),)).fetchone()["hash"]
    finally:
        db.close()


def client(cfg):
    app = create_app(cfg, 8765)
    app.config["TESTING"] = True
    return app.test_client()


def test_home_renders(cfg):
    response = client(cfg).get("/", headers={"Host": HOST})
    assert response.status_code == 200
    assert "BUPT Insight" in response.get_data(as_text=True)


def test_untrusted_host_is_rejected(cfg):
    response = client(cfg).get("/", headers={"Host": "evil.example"})
    assert response.status_code == 403


def test_cross_site_request_is_rejected(cfg):
    response = client(cfg).get("/api/feed", headers={"Host": HOST, "Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 403


def test_feed_returns_byr_notice(cfg, notice):
    seed(cfg, notice)
    response = client(cfg).get("/api/feed?view=all", headers={"Host": HOST})
    payload = response.get_json()
    assert response.status_code == 200
    assert len(payload["items"]) == 1
    assert payload["items"][0]["title"] == notice.title
    assert payload["counts"]["all"] == 1


def test_blocked_title_is_excluded(cfg):
    from core.schema import Item

    item = Item(
        source="portal",
        channel="科研院",
        title="关于2026年度科研资金公示",
        url="http://my.bupt.edu.cn/view?id=9001",
        published="2026-10-30 09:00",
        body="公示内容",
        private=True,
        extra={},
    )
    seed(cfg, item)
    payload = client(cfg).get("/api/feed?view=all", headers={"Host": HOST}).get_json()
    assert payload["total"] == 0
    assert payload["counts"]["all"] == 0


def test_protected_academic_notice_is_not_blocked(cfg):
    from core.schema import Item

    item = Item(
        source="portal",
        channel="教务处",
        title="关于2026年秋季学期选课名单公示的通知",
        url="http://my.bupt.edu.cn/view?id=9003",
        published="2026-10-30 09:00",
        body="选课名单公示，请核对。",
        private=True,
        extra={},
    )
    seed(cfg, item)
    payload = client(cfg).get("/api/feed?view=all", headers={"Host": HOST}).get_json()
    assert payload["total"] == 1
    assert payload["items"][0]["category"] == "mandatory_academic"


def test_block_titles_can_be_disabled(cfg):
    from core.schema import Item

    cfg["filters"] = {"block_titles": []}
    item = Item(
        source="portal",
        channel="科研院",
        title="关于2026年度科研资金公示",
        url="http://my.bupt.edu.cn/view?id=9002",
        published="2026-10-30 09:00",
        body="公示内容",
        private=True,
        extra={},
    )
    seed(cfg, item)
    payload = client(cfg).get("/api/feed?view=all", headers={"Host": HOST}).get_json()
    assert payload["total"] == 1


def test_recommended_is_empty_for_an_empty_profile(cfg, notice):
    seed(cfg, notice)
    payload = client(cfg).get("/api/feed?view=recommended", headers={"Host": HOST}).get_json()
    assert payload["items"] == []


def test_detail_returns_body(cfg, notice):
    seed(cfg, notice)
    c = client(cfg)
    item_id = c.get("/api/feed?view=all", headers={"Host": HOST}).get_json()["items"][0]["id"]
    payload = c.get(f"/api/detail?id={item_id}", headers={"Host": HOST}).get_json()
    assert "科研助理" in payload["body"]
    assert payload["url"].startswith("https://bbs.byr.cn")


def test_detail_unknown_id_is_404(cfg, notice):
    seed(cfg, notice)
    response = client(cfg).get("/api/detail?id=nope", headers={"Host": HOST})
    assert response.status_code == 404


def test_state_requires_csrf(cfg, notice):
    seed(cfg, notice)
    c = client(cfg)
    item_id = c.get("/api/feed?view=all", headers={"Host": HOST}).get_json()["items"][0]["id"]
    response = c.post("/api/state", json={"id": item_id, "hash": "x", "action": "read", "value": True}, headers={"Host": HOST})
    assert response.status_code == 403


def test_state_marks_read(cfg, notice):
    content_hash = seed(cfg, notice)
    c = client(cfg)
    item_id = c.get("/api/feed?view=all", headers={"Host": HOST}).get_json()["items"][0]["id"]
    with c.session_transaction() as session:
        session["csrf"] = "token"
    response = c.post(
        "/api/state",
        json={"id": item_id, "hash": content_hash, "action": "read", "value": True},
        headers={"Host": HOST, "X-CSRF-Token": "token"},
    )
    assert response.status_code == 200
    assert c.get("/api/feed?view=all", headers={"Host": HOST}).get_json()["items"][0]["unread"] is False


def test_stale_hash_is_conflict(cfg, notice):
    seed(cfg, notice)
    c = client(cfg)
    item_id = c.get("/api/feed?view=all", headers={"Host": HOST}).get_json()["items"][0]["id"]
    with c.session_transaction() as session:
        session["csrf"] = "token"
    response = c.post(
        "/api/state",
        json={"id": item_id, "hash": "stale", "action": "read", "value": True},
        headers={"Host": HOST, "X-CSRF-Token": "token"},
    )
    assert response.status_code == 409


def test_healthz_has_no_side_effects(cfg, notice):
    seed(cfg, notice)
    response = client(cfg).get("/healthz", headers={"Host": HOST})
    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


def test_status_reports_byr(cfg, notice):
    seed(cfg, notice)
    payload = client(cfg).get("/api/status", headers={"Host": HOST}).get_json()
    assert list(payload["sources"]) == ["byr", "portal"]
    assert payload["privacy"] == "local"

from datetime import datetime, timedelta, timezone

from core.schema import Item


def topic_item(title, days_ago, channel="兼职实习信息", body="虚构正文，欢迎报名。"):
    day = datetime.now(timezone(timedelta(hours=8))).date() - timedelta(days=days_ago)
    return Item(
        source="byr",
        channel=channel,
        title=title,
        url=f"https://bbs.byr.cn/article/Paper/{abs(hash(title)) % 1000000}",
        published=day.isoformat() + " 10:00:00",
        body=body,
        extra={"body_status": "ok"},
    )


def feed(cfg, query):
    return client(cfg).get("/api/feed?" + query, headers={"Host": HOST}).get_json()


def test_latest_is_limited_to_recent_window(cfg):
    seed(cfg, topic_item("实习招聘", 5))
    seed(cfg, topic_item("实验室招募科研助理", 120, body="课题组招募本科生参与科研。"))
    payload = feed(cfg, "view=latest&sort=collected")
    assert payload["total"] == 1
    assert payload["items"][0]["title"] == "实习招聘"


def test_latest_keeps_topic_filter(cfg):
    seed(cfg, topic_item("实习招聘", 5))
    seed(cfg, topic_item("程序设计竞赛报名", 6))
    assert feed(cfg, "view=latest&sort=collected")["total"] == 2
    narrowed = feed(cfg, "view=latest&sort=collected&category=internship")
    assert narrowed["total"] == 1
    assert narrowed["items"][0]["category"] == "internship"


def test_category_view_has_no_time_limit(cfg):
    seed(cfg, topic_item("实习招聘", 200))
    seed(cfg, topic_item("实验室招募科研助理", 5, body="课题组招募本科生参与科研。"))
    payload = feed(cfg, "view=internship")
    assert payload["total"] == 1
    assert payload["items"][0]["title"] == "实习招聘"


def test_category_view_ignores_subcategory_parameter(cfg):
    seed(cfg, topic_item("实习招聘", 5))
    seed(cfg, topic_item("实验室招募科研助理", 5, body="课题组招募本科生参与科研。"))
    payload = feed(cfg, "view=internship&category=research")
    assert payload["total"] == 1
    assert payload["items"][0]["category"] == "internship"


def test_category_views_cover_the_six_topics(cfg):
    seed(cfg, topic_item("实验室招募科研助理", 3, body="课题组招募本科生参与科研。"))
    seed(cfg, topic_item("程序设计竞赛报名", 3))
    seed(cfg, topic_item("实习招聘", 3))
    seed(cfg, topic_item("嵌入式硬件开发招募", 3))
    seed(cfg, topic_item("学术讲座通知", 3))
    seed(cfg, topic_item("选课通知", 3, channel="北邮教务处"))
    expected = {
        "research": "实验室招募科研助理",
        "competition": "程序设计竞赛报名",
        "internship": "实习招聘",
        "electronics": "嵌入式硬件开发招募",
        "event": "学术讲座通知",
        "mandatory_academic": "选课通知",
    }
    for view, title in expected.items():
        payload = feed(cfg, f"view={view}")
        assert payload["total"] == 1, view
        assert payload["items"][0]["title"] == title
        assert payload["items"][0]["category"] == view
