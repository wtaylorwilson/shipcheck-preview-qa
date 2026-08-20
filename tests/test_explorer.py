"""Explorer v0: synthesize stories, refuse submit/pay, pick visible CTAs."""

from __future__ import annotations

import pytest

from datetime import date

from shipcheck.explorer import (
    choose_cta,
    choose_followup_cta,
    extract_prices,
    extract_totals,
    find_hidden_only_target,
    goal_asks_week,
    goal_wants_deeper_walk,
    is_explore_step,
    is_forbidden_submit,
    is_payment_field,
    is_primary_cta,
    run_explorer,
    sat_sat_iso,
    score_cta,
    synthesize_stories,
)


GOAL = "Walk booking and check a Sat-Sat week uses the weekly rate"


def test_synthesize_stories_from_goal() -> None:
    stories = synthesize_stories(GOAL)
    assert len(stories) == 1
    assert stories[0].id == "charter"
    assert stories[0].steps == ["explore"]
    assert is_explore_step("explore")
    assert is_explore_step("explore:book a stay")
    assert not is_explore_step("click:text=Book")


def test_explorer_refuses_submit_pay() -> None:
    for label in (
        "Pay",
        "Pay now",
        "Place order",
        "Send",
        "Send request",
        "Submit request",
        "Submit",
        "Complete payment",
    ):
        assert is_forbidden_submit(label), label
    for label in ("Book now", "Continue", "Add to cart", "Checkout", "Rent"):
        assert not is_forbidden_submit(label), label


def test_choose_cta_skips_pay_and_prefers_goal() -> None:
    ctas = [
        {"text": "Place order", "visible": True, "href": "/pay"},
        {"text": "Continue", "visible": True, "href": "/next"},
        {"text": "Book now", "visible": True, "href": "/book"},
        {"text": "Pay", "visible": True, "href": "/card"},
    ]
    chosen = choose_cta(ctas, GOAL)
    assert chosen is not None
    assert chosen["text"] == "Book now"
    assert score_cta("Book now", GOAL) > score_cta("Continue", GOAL)

    pay_only = [
        {"text": "Pay now", "visible": True, "href": "/pay"},
        {"text": "Place order", "visible": True, "href": "/order"},
    ]
    assert choose_cta(pay_only, GOAL) is None


def test_hidden_only_target() -> None:
    ctas = [
        {"text": "Book now", "visible": False, "href": "/book"},
        {"text": "Continue", "visible": True, "href": "/next"},
    ]
    hidden = find_hidden_only_target(ctas, GOAL)
    assert hidden == "Book now"


def test_payment_fields_detected() -> None:
    assert is_payment_field("#card-number")
    assert is_payment_field("input[name=cvc]")
    assert is_payment_field("#cc-exp")
    assert not is_payment_field("#email")
    assert not is_payment_field("input[name=checkin]")


def test_primary_cta_words() -> None:
    assert is_primary_cta("Book a stay")
    assert is_primary_cta("Add to cart")
    assert not is_primary_cta("Learn more")


def test_extract_prices() -> None:
    text = "Cabin is $100 / day or $800 / week. Delivery $40."
    prices = extract_prices(text)
    assert any("100" in p and "day" in p.lower() for p in prices)
    assert any("800" in p and "week" in p.lower() for p in prices)


def test_sat_sat_iso_and_followup() -> None:
    start, end = sat_sat_iso(date(2026, 8, 20))  # Thursday
    assert start == "2026-08-22"
    assert end == "2026-08-29"
    start, end = sat_sat_iso(date(2026, 8, 22))  # already Saturday
    assert start == "2026-08-22"
    assert end == "2026-08-29"
    assert goal_asks_week(GOAL)
    assert goal_wants_deeper_walk(GOAL)
    assert not goal_asks_week("Click the hero and read the headline")
    ctas = [
        {"text": "Place order", "visible": True, "href": "/pay"},
        {"text": "Cart", "visible": True, "href": "/cart"},
        {"text": "Setup", "visible": True, "href": "/setup"},
        {"text": "Add", "visible": True, "href": "/add"},
    ]
    follow = choose_followup_cta(ctas, already_clicked="Add")
    assert follow is not None
    assert follow["text"] == "Cart"
    assert choose_followup_cta(
        [{"text": "Place order", "visible": True}], already_clicked="Add"
    ) is None
    totals = extract_totals("Subtotal $75  Cart total $75")
    assert "$75" in totals


def test_explorer_playwright_refuses_place_order() -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright not installed")
    html = """<!doctype html>
<html><body>
  <a id="book" href="#booked">Book now</a>
  <button id="pay">Place order</button>
  <p>$100 / day</p>
  <p>$700 / week</p>
  <input type="date" name="checkin">
  <script>
    document.getElementById('pay').onclick = () => { window.__clicked = 'pay'; };
    document.getElementById('book').onclick = () => { window.__clicked = 'book'; };
  </script>
</body></html>"""
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            try:
                page = browser.new_page()
                page.set_content(html)
                obs, action, err = run_explorer(
                    page,
                    goal=GOAL,
                    job_id="sc_testexplore",
                    story_id="charter",
                    vp_name="desktop",
                    shot_root=None,  # screenshots optional; path join will fail-soft
                )
                assert err is None, err
                assert action and action.startswith("clicked Book now")
                assert page.evaluate("window.__clicked") == "book"
                assert "filled checkin=" in (action or "")
                assert obs["clicked"]["text"] == "Book now"
                assert any(r["text"] == "Place order" for r in obs.get("refused") or [])
                assert any("100" in p for p in obs.get("prices") or [])
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001
        if "chromium" in str(exc).lower() or "executable" in str(exc).lower():
            pytest.skip(f"chromium unavailable: {exc}")
        raise


def test_explorer_playwright_does_not_click_pay_only() -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright not installed")
    html = """<!doctype html>
<html><body>
  <button id="pay">Place order</button>
  <script>
    document.getElementById('pay').onclick = () => { window.__clicked = 'pay'; };
  </script>
</body></html>"""
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            try:
                page = browser.new_page()
                page.set_content(html)
                obs, action, err = run_explorer(
                    page,
                    goal="Check out and pay",
                    job_id="sc_testpay",
                    story_id="charter",
                    vp_name="desktop",
                    shot_root=None,
                )
                assert err is None, err
                assert obs.get("clicked") is None
                assert action == "refused submit/pay"
                assert page.evaluate("window.__clicked") is None
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001
        if "chromium" in str(exc).lower() or "executable" in str(exc).lower():
            pytest.skip(f"chromium unavailable: {exc}")
        raise


def test_explorer_playwright_opens_cart_and_fills_sat_sat() -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright not installed")
    html = """<!doctype html>
<html><body>
  <p>$24 / day</p>
  <p>$75 / week</p>
  <button id="add">Add</button>
  <a id="cart" href="#cart" style="display:none">Cart</a>
  <div id="panel" style="display:none">
    <label>Delivery <input type="date" name="delivery"></label>
    <label>Pickup <input type="date" name="pickup"></label>
    <p id="dur"></p>
    <p id="tot"></p>
    <button id="pay">Place order</button>
  </div>
  <script>
    window.__seq = [];
    document.getElementById('add').onclick = () => {
      window.__seq.push('add');
      document.getElementById('cart').style.display = 'inline';
    };
    document.getElementById('cart').onclick = () => {
      window.__seq.push('cart');
      document.getElementById('panel').style.display = 'block';
    };
    document.getElementById('pay').onclick = () => { window.__seq.push('pay'); };
    function refresh() {
      const a = document.querySelector('[name=delivery]').value;
      const b = document.querySelector('[name=pickup]').value;
      if (a && b) {
        const days = (new Date(b) - new Date(a)) / 86400000;
        document.getElementById('dur').textContent = days + ' nights';
        document.getElementById('tot').textContent = 'Total $75';
      }
    }
    document.querySelector('[name=delivery]').addEventListener('change', refresh);
    document.querySelector('[name=pickup]').addEventListener('change', refresh);
  </script>
</body></html>"""
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            try:
                page = browser.new_page()
                page.set_content(html)
                obs, action, err = run_explorer(
                    page,
                    goal=GOAL,
                    job_id="sc_testweek",
                    story_id="charter",
                    vp_name="desktop",
                    shot_root=None,
                )
                assert err is None, err
                seq = page.evaluate("window.__seq")
                assert "add" in seq
                assert "cart" in seq
                assert "pay" not in seq
                assert action and "clicked Add" in action
                assert "clicked Cart" in action
                assert any(d.get("name") == "delivery" and d.get("value") for d in (obs.get("dates_filled") or []))
                delivery = page.input_value('input[name="delivery"]')
                pickup = page.input_value('input[name="pickup"]')
                assert delivery  # ISO date filled
                assert pickup
                assert delivery < pickup
                assert any(r["text"] == "Place order" for r in obs.get("refused") or [])
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001
        if "chromium" in str(exc).lower() or "executable" in str(exc).lower():
            pytest.skip(f"chromium unavailable: {exc}")
        raise

