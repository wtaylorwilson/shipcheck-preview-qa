"""Explorer v0: synthesize stories, refuse submit/pay, pick visible CTAs."""

from __future__ import annotations

import pytest

from shipcheck.explorer import (
    choose_cta,
    extract_prices,
    find_hidden_only_target,
    is_explore_step,
    is_forbidden_submit,
    is_payment_field,
    is_primary_cta,
    run_explorer,
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
                assert action == "clicked Book now"
                assert page.evaluate("window.__clicked") == "book"
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
