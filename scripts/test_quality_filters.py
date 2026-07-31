#!/usr/bin/env python3
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.pipeline.normalizer import normalize_posts
from src.pipeline.clusterer import cluster_posts
from src.utils.config import load_project_json


def post(post_id: str, text: str, brand_candidate: str = "joybuy", links: Optional[list[str]] = None) -> dict:
    return {
        "post_id": post_id,
        "url": f"https://x.com/test/status/{post_id}",
        "text": text,
        "author_id": "author-test",
        "author_name": "Test",
        "author_handle": "test",
        "author_followers": 10,
        "author_verified": False,
        "created_at": "2026-07-17T00:00:00Z",
        "collected_at": "2026-07-17T00:00:00Z",
        "language": "en",
        "like_count": 0,
        "repost_count": 0,
        "reply_count": 0,
        "quote_count": 0,
        "bookmark_count": None,
        "view_count": 1,
        "media": [],
        "links": links or [],
        "quoted_post_id": None,
        "reply_to_post_id": None,
        "source_provider": "test",
        "query": "test",
        "brand_candidate": brand_candidate,
    }


def main() -> None:
    config = load_project_json("keywords.local.json")
    rows = normalize_posts(
        [
            post("1", "JD Vance knows nothing about history and politics."),
            post("2", "JD.com order tracking for my Joybuy Germany parcel is delayed."),
            post("3", "提供京东E卡低价充值和代充服务"),
            post("4", "god forbid bts did something sto lat temu fake problematic things", "temu"),
            post("5", "Class action alleges Temu used deceptive spam emails to install tracking technology", "temu"),
            post("6", "Temu journalist is spreading fake news again", "temu"),
            post("7", "Cada vez que veo algo de Temu cierro la app por los premios gratis", "temu"),
            post(
                "8",
                "EU regulator sends charge sheet to https://t.co/brand over Ceconomy deal https://t.co/news",
                links=["http://JD.com", "https://www.reuters.com/business/eu-regulator-sends-charge-sheet-jdcom-over-ceconomy-deal/"],
            ),
            post("9", "JD.com total return beat several China internet stocks in the first half."),
            post("10", "Have you tried Joybuy? Asian products are often half the price and delivery is very fast."),
            post("11", "E-commerce : Joybuy launches subscription\n\nIci &gt;&gt; https://t.co/example", links=["https://example.com/joybuy-subscription"]),
            post(
                "12",
                "Malam ini pukul 20:00, join the JD.com live streaming. Jangan lupa datang ya.",
            ),
            post("13", "Joybuy app data privacy and security concerns need answers."),
        ],
        config,
    )

    by_id = {row["post_id"]: row for row in rows}
    assert not by_id["1"]["is_relevant"], "JD Vance political posts must be excluded"
    assert by_id["1"]["matched_irrelevant_terms"], "JD Vance post should record irrelevant terms"
    assert by_id["2"]["is_relevant"], "JD.com/Joybuy ecommerce context should remain relevant"
    assert not by_id["3"]["is_relevant"], "JD card recharge spam must be excluded"
    assert by_id["3"]["matched_spam_terms"], "JD card recharge spam should record spam terms"
    assert not by_id["4"]["is_relevant"], "Polish 'temu' false positive must be excluded"
    assert by_id["5"]["is_relevant"], "Temu tracking/privacy controversy should remain relevant"
    assert not by_id["6"]["is_relevant"], "Temu-as-insult false positive must be excluded"
    assert by_id["7"]["is_relevant"], "Temu app complaint should remain relevant"
    assert by_id["8"]["is_relevant"], "JD.com regulatory/acquisition news in expanded links must remain relevant"
    assert "JD.com" in by_id["8"]["clean_text"], "Expanded JD.com link should remain readable in clean text"
    assert "regulator" in by_id["8"]["risk_terms"], "Regulatory news should carry a regulatory risk signal"
    assert by_id["9"]["is_relevant"], "JD.com financial-market context can remain relevant"
    assert "return" not in by_id["9"]["risk_terms"], "financial total return must not become after-sales return risk"
    assert by_id["10"]["is_relevant"], "positive Joybuy shopping experience should remain relevant"
    assert "Ici >> example.com/joybuy-subscription" in by_id["11"]["clean_text"], "HTML entities should be decoded before public display"
    assert by_id["12"]["is_relevant"], "JD.com livestream fan update should remain relevant"
    assert by_id["13"]["is_relevant"], "real data privacy concerns should remain relevant"
    clusters = cluster_posts(rows, "joybuy")
    regulatory = [cluster for cluster in clusters if cluster["topic"] == "regulatory"]
    positive = [cluster for cluster in clusters if cluster["topic"] == "positive_experience"]
    company = [cluster for cluster in clusters if cluster["topic"] == "company_market"]
    channel = [cluster for cluster in clusters if cluster["topic"] == "channel_activity"]
    trust_safety = [cluster for cluster in clusters if cluster["topic"] == "trust_safety"]
    assert regulatory, "JD.com regulatory/acquisition news should be grouped under regulatory topic"
    assert positive, "positive price and delivery experience should be grouped under positive experience"
    assert company, "JD.com financial-market context should be grouped away from after-sales risk"
    assert any("12" in cluster["post_ids"] for cluster in channel), "Indonesian 'datang' must not be mistaken for data risk"
    assert any("13" in cluster["post_ids"] for cluster in trust_safety), "real data privacy concerns should remain trust safety"
    print("Quality filter tests passed.")


if __name__ == "__main__":
    main()
