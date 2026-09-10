#!/usr/bin/env python3
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.adapters.x_source_base import ProviderBudgetExceeded
from src.pipeline.platform_trends import (
    apply_platform_semantic_review,
    build_platform_queries,
    canonical_platform_tag,
    clean_post_text,
    collection_status,
    effective_platform_intent_terms,
    platform_query_candidate_limit,
    platform_query_request_allowance,
    platform_acceptance_path,
    platform_rejection_detail,
    platform_review_evidence_candidate,
    platform_semantic_review_input,
    platform_specific_hard_risk_reason,
    public_platform_collection_status,
    prune_platform_rejection_audits,
    score_platform_post,
    semantic_decision_accepts,
    search_platform_query_with_budget,
    strict_platform_relevance,
    unique_platform_query_rows,
    write_platform_rejection_audit,
)


def main() -> None:
    assert canonical_platform_tag("变现路径") == "变现"
    assert canonical_platform_tag("商单") == "变现"
    assert canonical_platform_tag("带货") == "变现"
    assert canonical_platform_tag("笔记") == "爆文与内容结构"
    assert canonical_platform_tag("涨粉") == "账号冷启动"
    assert canonical_platform_tag("限流") == "风控对抗"
    assert canonical_platform_tag("平台规则") == "平台规则"
    assert canonical_platform_tag("账号矩阵") == "矩阵"
    assert canonical_platform_tag("设备指纹") == "逆向与改机"

    media_text = clean_post_text(
        {
            "text": "图片用 Image2 等模型生成， https://t.co/yqRoyVQuOY",
            "media": [{"url": "https://t.co/yqRoyVQuOY", "type": "photo"}],
        }
    )
    assert media_text == "图片用 Image2 等模型生成，", "media placeholder URLs should not appear in XHS card text"

    platform = {
        "aliases": ["小红书"],
        "intent_terms": ["变现", "商单", "带货", "流量", "引流", "涨粉", "风控", "平台规则", "账号获取", "矩阵"],
        "exclude_terms": [],
    }
    item = {
        "clean_text": "小红书起号后怎么做流量和变现？1. 先用笔记测选题；2. 再用商单和带货验证收入；3. 最后引流到私域复购。",
        "links": [],
        "metrics": {"likes": 80, "views": 8000},
        "author_followers": 2000,
    }
    decision = score_platform_post(item, platform)
    assert decision["accepted"], "strong platform trend methods should be accepted"
    tags = decision["item"]["tags"]
    assert "变现" in tags
    assert "变现路径" not in tags
    assert "商单" not in tags
    assert "带货" not in tags
    assert "涨粉" not in tags
    assert len(tags) == len(set(tags)), "canonical tags should be deduped"

    risk_control_item = {
        "clean_text": "小红书账号矩阵起号时，先准备老号和白号池，按平台规则控制发布节奏，避免审核限流。这里是完整风控对抗流程：1. 分层养号；2. 批量测试笔记；3. 复盘违规原因。",
        "links": [],
        "metrics": {"likes": 24, "views": 1200},
        "author_followers": 1800,
    }
    risk_control_decision = score_platform_post(risk_control_item, platform)
    assert risk_control_decision["accepted"], "risk-control and matrix playbooks should enter platform trend collection"
    risk_tags = risk_control_decision["item"]["tags"]
    assert "风控对抗" in risk_tags
    assert "平台规则" in risk_tags
    assert "矩阵" in risk_tags

    adult_noise = {
        "clean_text": "冷知识：中国约炮平台流量最高：Boss直聘 > 小红书 > 58同城",
        "links": [],
        "metrics": {"likes": 17, "views": 1478},
        "author_followers": 1000,
    }
    adult_noise_decision = score_platform_post(adult_noise, platform)
    assert not adult_noise_decision["accepted"], "low-value adult jokes should not enter platform trend collection"

    adult_rule_evasion = {
        "clean_text": "玩的就是反差，身体已经软成一滩水。小红书两次违规真发不出，只能推特发了，开脱上供 Luo照 锐评一下不许说我黑。",
        "links": [],
        "metrics": {"likes": 28, "views": 1800},
        "author_followers": 1000,
    }
    adult_rule_evasion_decision = score_platform_post(adult_rule_evasion, platform)
    assert not adult_rule_evasion_decision["accepted"], "adult rule-evasion spam should not enter platform trend collection"

    adult_platform_joke = {
        "clean_text": "小红书是不是拖延审核员工资了，我还以为打开了小黄书。",
        "links": [],
        "metrics": {"likes": 32, "views": 2200},
        "author_followers": 1000,
    }
    adult_platform_joke_decision = score_platform_post(adult_platform_joke, platform)
    assert not adult_platform_joke_decision["accepted"], "adult platform jokes should not enter platform trend collection"

    short_reaction_link = {
        "clean_text": "卧槽，小红书变现能力这么强的嘛！！ https://t.co/example",
        "links": ["https://example.com"],
        "metrics": {"likes": 61, "views": 43322, "replies": 116},
        "author_followers": 1000,
    }
    short_reaction_decision = score_platform_post(short_reaction_link, platform)
    assert not short_reaction_decision["accepted"], "short reaction links should not enter platform trend collection"

    unresolved_article = {
        "clean_text": "https://t.co/article-only",
        "links": [],
        "media": [{"url": "https://example.com/cover.jpg", "type": "photo", "source": "card"}],
        "metrics": {"likes": 61, "views": 43322, "replies": 116},
        "author_followers": 1000,
    }
    unresolved_decision = score_platform_post(unresolved_article, platform)
    assert unresolved_decision["reason_code"] == "article_content_unavailable", (
        "an article shell should be marked unresolved instead of classified as off-topic"
    )

    platform_news = {
        "clean_text": "杜撰“小红书上市失败”贴文，被警方行拘。涉企网络谣言案件通报。",
        "links": [],
        "metrics": {"likes": 74, "views": 21787, "replies": 16},
        "author_followers": 1000,
    }
    assert not score_platform_post(platform_news, platform)["accepted"], "platform news should not enter method collection"

    off_topic_namedrop = {
        "clean_text": "我简单讲讲这个人和特斯拉中国的恩怨：他借着小红书上一个账号的所谓人去楼空来黑特斯拉，最后把FSD相关谣言热点引爆。",
        "links": [],
        "metrics": {"likes": 52, "views": 21323, "replies": 22},
        "author_followers": 1000,
    }
    assert not score_platform_post(off_topic_namedrop, platform)["accepted"], "keyword-only namedrops should not enter method collection"

    off_topic_comparison = {
        "clean_text": "Tutti 商单收益比做闲鱼和小红书投入产出自由，赶紧来注册加入。",
        "links": [],
        "metrics": {"likes": 57, "views": 5543, "replies": 2},
        "author_followers": 1000,
    }
    assert not score_platform_post(off_topic_comparison, platform)["accepted"], "off-topic platform comparisons should not enter collection"

    animal_cruelty_report = {
        "clean_text": "如果你在网络上发现虐待动物的视频，请不要沉默。保存证据后向微博、小红书、QQ、抖音等平台按平台规则举报，再通报执法部门和动物保护组织。STOP ANIMAL CRUELTY.",
        "links": [],
        "metrics": {"likes": 116, "views": 1962, "replies": 0},
        "author_followers": 1000,
    }
    assert not score_platform_post(animal_cruelty_report, platform)["accepted"], "animal-cruelty reporting advocacy is not XHS growth methodology"

    reverse_engineering = {
        "clean_text": "小红书逆向工程实测：通过抓包分析接口签名和设备指纹，整理了改机环境的账号风控检查步骤。",
        "links": [],
        "metrics": {"likes": 18, "views": 900},
        "author_followers": 1200,
    }
    reverse_decision = score_platform_post(
        reverse_engineering,
        {**platform, "intent_terms": [*platform["intent_terms"], "逆向工程", "抓包", "设备指纹", "改机"]},
    )
    assert reverse_decision["accepted"], "XHS reverse-engineering and device-environment research should be collected"
    assert "逆向与改机" in reverse_decision["item"]["tags"]
    assert strict_platform_relevance({**reverse_engineering, **reverse_decision["item"]})

    workflow_platform = {
        **platform,
        "query_groups": [
            {"name": "content", "intent_terms": ["选题", "复盘", "工作流"]},
        ],
    }
    assert "复盘" in effective_platform_intent_terms(workflow_platform)
    workflow_case = {
        "clean_text": (
            "这个社媒运营工作流把热点发现、选题、内容生产、发布和数据复盘串起来，"
            "发布支持小红书，并提醒小红书自动化操作应当预览后手动发布。"
        ),
        "links": [],
        "metrics": {"likes": 197, "reposts": 41, "replies": 31, "views": 12525},
        "author_followers": 0,
    }
    assert score_platform_post(workflow_case, workflow_platform)["accepted"], (
        "actionable multi-platform workflows with explicit Xiaohongshu support should enter review"
    )

    prompt_template_case = {
        "clean_text": (
            "萌宠类 AI 账号在抖音和小红书的流量表现都不错。下面给出可直接复用的提示词、"
            "竖屏分镜、角色一致性和镜头脚本，并说明如何按十秒视频模板生成内容。"
        ),
        "links": [],
        "metrics": {"likes": 25, "reposts": 2, "replies": 21, "views": 2409},
        "author_followers": 0,
    }
    assert score_platform_post(prompt_template_case, workflow_platform)["accepted"], (
        "reusable content templates with explicit Xiaohongshu applicability should enter review"
    )

    live_dictionary_template = {
        "clean_text": (
            "handraw-style 把 216 种手绘风格做成编号和中英文提示词，先选风格再替换主题，"
            "做公众号、小红书配图时可以让系列图片长期保持一致。"
        ),
        "links": ["https://github.com/example/handraw-style"],
        "metrics": {"likes": 116, "reposts": 23, "replies": 22, "views": 7398},
        "author_followers": 0,
    }
    assert score_platform_post(live_dictionary_template, platform)["accepted"], (
        "explicit Xiaohongshu prompt and image workflows must reach semantic review"
    )

    live_result_case = {
        "clean_text": (
            "我用 AI 三天做出一个游戏，发到小红书一发就火了：4 万阅读、2000 个赞，"
            "随后把评论里的玩家反馈整理成需求池继续迭代。"
        ),
        "links": [],
        "metrics": {"likes": 19, "reposts": 3, "replies": 7, "views": 2254},
        "author_followers": 0,
    }
    live_result_decision = score_platform_post(live_result_case, platform)
    assert live_result_decision["accepted"], (
        "a concrete Xiaohongshu result and feedback loop must not require a legacy intent keyword"
    )
    assert "案例复盘" in live_result_decision["item"]["tags"]

    platform_scam_chain = {
        "clean_text": (
            "小红书有人用高价回收名表获客，随后发外部地址让你填写手机号。千万不要填，"
            "他们会把个人信息和个人数据再卖给别人，这是完整的钓鱼链路。"
        ),
        "links": [],
        "metrics": {"likes": 5, "replies": 1, "views": 221},
        "author_followers": 0,
    }
    scam_decision = score_platform_post(platform_scam_chain, platform)
    assert scam_decision["accepted"], "a concrete Xiaohongshu data-risk chain should reach semantic review"
    assert "风控对抗" in scam_decision["item"]["tags"]

    normal_delete_word_case = {
        "clean_text": (
            "品牌没有删帖公关，而是 48 小时把误译做成限定产品并售罄，随后借助小红书、"
            "抖音持续发布这个梗，引发一轮流量。"
        ),
        "links": [],
        "metrics": {"likes": 127, "reposts": 10, "replies": 24, "views": 53521},
        "author_followers": 0,
    }
    assert score_platform_post(normal_delete_word_case, platform)["accepted"], (
        "ordinary discussion of deleting a post should not trip the takedown-service policy"
    )
    delete_service_ad = {
        **normal_delete_word_case,
        "clean_text": "小红书专业删帖服务，可处理负面笔记，联系客服报价下单。",
    }
    assert not score_platform_post(delete_service_ad, platform)["accepted"]

    result_case = {
        "clean_text": (
            "这个小红书账号每天两更，一篇垂直内容、一篇跨平台内容截图。停更半个月后后台仍有"
            "99+ 点赞收藏、99+ 涨粉，并收到两个商单机会，这是一次低成本内容复用案例复盘。"
        ),
        "links": [],
        "metrics": {"likes": 20, "reposts": 1, "replies": 34, "views": 5720},
        "author_followers": 0,
    }
    result_rule_decision = score_platform_post(result_case, workflow_platform)
    assert result_rule_decision["accepted"]
    low_confidence_rejection = {
        "central_subject": True,
        "actionable_for_platform": True,
        "relevant_domain": True,
        "substantive": False,
        "low_value": True,
        "confidence": 0.68,
    }
    reviewed_result_case = {**result_case, **result_rule_decision["item"]}
    assert semantic_decision_accepts(low_confidence_rejection, reviewed_result_case), (
        "a low-confidence model rejection should defer to strong deterministic case evidence"
    )
    assert not semantic_decision_accepts(
        {**low_confidence_rejection, "confidence": 0.90},
        reviewed_result_case,
    ), "a high-confidence low-value decision should remain a veto"

    multi_platform_playbook = {
        "clean_text": (
            "公众号、小红书和 X 都适合图文分享。\n1. 新手先用轻量图文验证内容；"
            "\n2. 以流量为目标选题并对标账号；\n3. 选择最简单的形式，再根据真实数据持续调整。"
        ),
        "links": [],
        "metrics": {"likes": 100, "reposts": 10, "replies": 20, "views": 9000},
        "author_followers": 0,
    }
    playbook_rule_decision = score_platform_post(multi_platform_playbook, workflow_platform)
    assert playbook_rule_decision["accepted"]
    assert semantic_decision_accepts(
        {
            "central_subject": False,
            "actionable_for_platform": False,
            "relevant_domain": True,
            "substantive": True,
            "low_value": False,
            "confidence": 0.86,
        },
        {**multi_platform_playbook, **playbook_rule_decision["item"]},
    ), "strong explicit platform application should override a model centrality false negative"

    platform_observation = {
        "clean_text": (
            "小红书上有个讲 AI 课程的博主，手写笔记基本篇篇爆款，"
            "但是一旦改成电脑码字或者露脸，流量就断崖式下跌，这是何原因？"
        ),
        "links": [],
        "metrics": {"likes": 71, "reposts": 3, "replies": 16, "views": 17330},
        "author_followers": 0,
    }
    observation_rule_decision = score_platform_post(platform_observation, platform)
    assert observation_rule_decision["accepted"]
    rejected_observation_decision = {
        "central_subject": True,
        "actionable_for_platform": False,
        "relevant_domain": True,
        "substantive": False,
        "low_value": True,
        "confidence": 0.82,
    }
    assert semantic_decision_accepts(
        rejected_observation_decision,
        {**platform_observation, **observation_rule_decision["item"]},
    ), "a concrete platform observation should survive a generic low-value model verdict"
    assert semantic_decision_accepts(
        {
            "central_subject": False,
            "actionable_for_platform": False,
            "relevant_domain": True,
            "substantive": True,
            "low_value": False,
            "confidence": 0.92,
        },
        {**platform_observation, **observation_rule_decision["item"]},
    ), "a substantive no-link format comparison can recover from a centrality false negative"

    paid_growth_comparison = {
        **platform_observation,
        "clean_text": (
            "小红书图文刷赞后流量更高，但是一旦改发视频流量就下降。提供刷量、付费涨粉服务，"
            "需要的请私信下单。"
        ),
        "quality_score": 90,
    }
    assert not semantic_decision_accepts(
        {**rejected_observation_decision, "confidence": 0.99},
        paid_growth_comparison,
    ), "a format comparison must never bypass a high-confidence low-value veto"

    platform_update = {
        "clean_text": (
            "据业内人士爆料：小红书预计在年底完成沙盒隔离运作，海外身份账号与内地账号不互通，"
            "大陆账号将无法与海外账号点赞、评论或私信。"
        ),
        "links": [],
        "metrics": {"likes": 36, "replies": 26, "views": 4355},
        "author_followers": 0,
    }
    update_decision = score_platform_post(platform_update, platform)
    assert update_decision["accepted"]
    assert update_decision["item"]["acceptance_path"] == "platform_update"
    assert update_decision["item"]["source_status"] == "rumor"
    assert semantic_decision_accepts(
        {
            "platform_relation": "central",
            "content_type": "platform_update",
            "specific_signal": True,
            "hard_risk": False,
            "central_subject": True,
            "actionable_for_platform": False,
            "relevant_domain": True,
            "substantive": False,
            "low_value": True,
            "confidence": 0.92,
        },
        {**platform_update, **update_decision["item"]},
    ), "typed platform updates should not require a tutorial structure"

    tool_resource = {
        "clean_text": "AI 写公众号、小红书、头条号文章的真实写作经验分享和原创封面 AI 提示词 Skills。",
        "links": [],
        "media": [{"type": "video", "url": "https://example.com/demo.mp4"}],
        "metrics": {"likes": 10, "replies": 1, "views": 1452},
        "author_followers": 0,
    }
    tool_decision = score_platform_post(tool_resource, platform)
    assert tool_decision["accepted"]
    assert tool_decision["item"]["acceptance_path"] == "tool_resource"

    monetization_lead = {
        "clean_text": "2026 年的机会：小红书数字产品可以卖手账、模板、素材包；小红书单品带货只打一个爆品。",
        "links": [],
        "metrics": {"likes": 185, "replies": 4, "views": 13509},
        "author_followers": 0,
    }
    monetization_decision = score_platform_post(monetization_lead, platform)
    assert monetization_decision["accepted"]
    assert monetization_decision["item"]["acceptance_path"] == "monetization_opportunity"

    case_lead = {
        "clean_text": (
            "最近 X 来了很多在微信公众号、抖音、小红书拿到过结果的高手，推荐 @ExampleCreator，"
            "3 年运营 300 个账号日更，把内容生产做成了可复制的内容工厂。"
        ),
        "links": [],
        "media": [{"type": "photo", "url": "https://example.com/profile.jpg"}],
        "metrics": {"likes": 19, "replies": 11, "views": 5563},
        "author_followers": 0,
    }
    case_lead_decision = score_platform_post(case_lead, platform)
    assert case_lead_decision["accepted"]
    assert case_lead_decision["item"]["acceptance_path"] == "case_lead"

    for candidate, path_decision, expected_path in (
        (platform_observation, observation_rule_decision, "platform_observation"),
        (platform_update, update_decision, "platform_update"),
        (tool_resource, tool_decision, "tool_resource"),
        (monetization_lead, monetization_decision, "monetization_opportunity"),
        (case_lead, case_lead_decision, "case_lead"),
    ):
        reviewed_candidate = {**candidate, **path_decision["item"]}
        assert platform_acceptance_path(reviewed_candidate) == expected_path
        assert semantic_decision_accepts(
            {
                "central_subject": False,
                "actionable_for_platform": False,
                "relevant_domain": False,
                "substantive": False,
                "low_value": True,
                "hard_risk": False,
                "confidence": 0.99,
            },
            reviewed_candidate,
        ), f"{expected_path} should survive a generic false-negative verdict"

    assert platform_review_evidence_candidate({**platform_observation, **observation_rule_decision["item"]})
    evidence_input = platform_semantic_review_input(
        {
            "post_id": "observation",
            **platform_observation,
            **observation_rule_decision["item"],
            "media": [{"type": "photo", "url": "https://example.com/evidence.jpg"}],
            "conversation_context": {
                "summary_zh": "评论区讨论了手写形式带来的真实感。",
                "posts": [
                    {"post_id": "observation", "text": platform_observation["clean_text"]},
                    {"post_id": "reply-1", "text": "手写笔记更像真实经验，收藏意愿更高。"},
                ],
            },
        }
    )
    assert evidence_input["acceptance_path_hint"] == "platform_observation"
    assert evidence_input["evidence"]["media_count"] == 1
    assert evidence_input["evidence"]["comment_snippets"] == ["手写笔记更像真实经验，收藏意愿更高。"]

    generic_tutorial_namedrop = {
        "clean_text": (
            "通用短视频教程：\n1. 找选题；\n2. 写脚本和分镜；\n3. 发布后复盘。"
            "这套方法适合所有平台，最后做出的成片也可以发布到小红书。"
        ),
        "links": [],
        "metrics": {"likes": 120, "reposts": 20, "replies": 15, "views": 12000},
        "author_followers": 0,
    }
    generic_rule_decision = score_platform_post(generic_tutorial_namedrop, workflow_platform)
    assert generic_rule_decision["accepted"]
    assert not semantic_decision_accepts(
        {
            "central_subject": False,
            "actionable_for_platform": False,
            "relevant_domain": True,
            "substantive": True,
            "low_value": False,
            "confidence": 0.99,
        },
        {**generic_tutorial_namedrop, **generic_rule_decision["item"]},
    ), "a generic tutorial with an end-of-post Xiaohongshu namedrop must not be force-accepted"

    enumerated_platform_namedrop = {
        **generic_tutorial_namedrop,
        "clean_text": (
            "通用短视频教程：\n1. 找选题；\n2. 写脚本和分镜；\n3. 发布后复盘。"
            "这套图文模板适合公众号、抖音和小红书。"
        ),
    }
    enumerated_rule_decision = score_platform_post(enumerated_platform_namedrop, workflow_platform)
    assert enumerated_rule_decision["accepted"]
    assert not semantic_decision_accepts(
        {
            "central_subject": False,
            "actionable_for_platform": False,
            "relevant_domain": True,
            "substantive": True,
            "low_value": False,
            "confidence": 0.99,
        },
        {**enumerated_platform_namedrop, **enumerated_rule_decision["item"]},
    ), "an enumerated list of platforms must not be treated as Xiaohongshu-specific application evidence"

    bookmark_collector = {
        "clean_text": (
            "很多人存了微信、抖音、小红书收藏，最后全成了垃圾。这个 Webhook 教程可以把任何链接"
            "自动读完并存进通用知识库。"
        ),
        "links": [],
        "metrics": {"likes": 20, "replies": 5, "views": 3000},
    }
    assert platform_acceptance_path(bookmark_collector) == "", (
        "a tool that merely consumes Xiaohongshu bookmarks is not a Xiaohongshu operations resource"
    )

    generic_brand_campaign = {
        "clean_text": (
            "品牌把一次翻译错误做成限定产品并售罄，随后借助小红书、抖音等渠道传播，"
            "把营销翻车变成一次热点。"
        ),
        "links": [],
        "metrics": {"likes": 127, "replies": 24, "views": 53521},
    }
    assert platform_acceptance_path(generic_brand_campaign) == "", (
        "a generic brand campaign must not qualify when Xiaohongshu is only a distribution channel"
    )

    grey_growth_link = {
        "clean_text": "小红书网盘拉新项目，两种变现方式结合，当日收益 1034，详细拆解见链接。",
        "links": ["https://example.com/promo"],
        "metrics": {"likes": 25, "reposts": 5, "replies": 3, "views": 4000},
        "author_followers": 0,
        "quality_score": 99,
    }
    assert platform_specific_hard_risk_reason(grey_growth_link["clean_text"]) == "cloud_drive_referral"
    assert not semantic_decision_accepts(
        {
            "central_subject": True,
            "actionable_for_platform": False,
            "relevant_domain": True,
            "substantive": False,
            "low_value": True,
            "confidence": 0.90,
        },
        grey_growth_link,
    ), "link-led grey growth promotions must remain rejected"

    class FalseNegativeReviewService:
        configured = True
        classification_last_error = ""

        def classify_platform_batch(self, items):
            return {
                items[0]["id"]: {
                    "central_subject": False,
                    "actionable_for_platform": False,
                    "relevant_domain": True,
                    "substantive": True,
                    "low_value": False,
                    "domain": "爆文与内容结构",
                    "confidence": 0.86,
                    "reason": "误判为通用多平台方法",
                }
            }

    overridden_rows, overridden_status = apply_platform_semantic_review(
        [{"post_id": "playbook", "language": "zh", **multi_platform_playbook, **playbook_rule_decision["item"]}],
        FalseNegativeReviewService(),
    )
    assert [row["post_id"] for row in overridden_rows] == ["playbook"]
    assert overridden_status["accepted_count"] == 1
    assert overridden_status["overridden_count"] == 1
    assert overridden_status["override_reasons"] == {"explicit_platform_application": 1}

    class ReviewService:
        configured = True
        classification_last_error = ""

        def classify_platform_batch(self, items):
            return {
                items[0]["id"]: {
                    "central_subject": False,
                    "actionable_for_platform": True,
                    "relevant_domain": False,
                    "substantive": False,
                    "low_value": True,
                    "domain": "案例复盘",
                    "confidence": 0.98,
                    "reason": "小红书仅被顺带提及",
                },
                items[1]["id"]: {
                    "central_subject": True,
                    "relevant_domain": True,
                    "substantive": True,
                    "low_value": False,
                    "domain": "逆向与改机",
                    "confidence": 0.94,
                    "reason": "提供小红书客户端逆向方法",
                },
            }

    semantic_items = [
        {"post_id": "off-topic", "language": "zh", **item, **decision["item"]},
        {"post_id": "reverse", "language": "zh", **reverse_engineering, **reverse_decision["item"]},
    ]
    reviewed, review_status = apply_platform_semantic_review(semantic_items, ReviewService())
    assert [row["post_id"] for row in reviewed] == ["reverse"]
    assert reviewed[0]["topic"] == "逆向与改机"
    assert review_status["reviewed_count"] == 2
    assert review_status["rejected_count"] == 1

    rejection_details = {}
    reviewed, review_status = apply_platform_semantic_review(
        semantic_items,
        ReviewService(),
        rejection_details=rejection_details,
    )
    assert rejection_details["off-topic"]["stage"] == "semantic_review"
    assert rejection_details["off-topic"]["reason_code"] == "low_value"
    assert rejection_details["off-topic"]["model_decision"]["actionable_for_platform"] is True

    with tempfile.TemporaryDirectory() as temp_dir:
        audit_dir = Path(temp_dir)
        (audit_dir / "2026-09-01.json").write_text("{}\n", encoding="utf-8")
        (audit_dir / "2026-09-02.json").write_text("{}\n", encoding="utf-8")
        eligible = {
            f"post-{index}": {
                "post_id": f"post-{index}",
                "created_at": f"2026-09-08T01:{index:02d}:00Z",
                "clean_text": f"小红书候选内容 {index}",
                "metrics": {"views": 1000 + index, "likes": 50 + index},
                "_audit_query_group": "content_traffic",
            }
            for index in range(25)
        }
        audit_rejections = {
            f"post-{index}": {
                "stage": "rule_filter",
                "reason_code": "platform_not_central",
                "reason_label": "小红书不是正文核心对象",
            }
            for index in range(3, 18)
        }
        audit_rejections.update(
            {f"post-{index}": rejection_details["off-topic"] for index in range(18, 25)}
        )
        audit = write_platform_rejection_audit(
            audit_dir,
            "2026-09-08",
            "test window",
            eligible,
            [eligible[f"post-{index}"] for index in range(3)],
            audit_rejections,
        )
        assert audit["summary"]["metric_eligible_count"] == 25
        assert audit["summary"]["accepted_count"] == 3
        assert audit["summary"]["rejected_count"] == 22
        assert audit["summary"]["stage_counts"] == {"rule_filter": 15, "semantic_review": 7}
        assert audit["summary"]["count_matches"] is True
        assert len(audit["items"]) == 22
        assert not (audit_dir / "2026-09-01.json").exists(), "eighth calendar day should be pruned"
        assert (audit_dir / "2026-09-02.json").exists(), "seven-day retention should keep current day plus six days"
        parsed_audit = json.loads((audit_dir / "2026-09-08.json").read_text(encoding="utf-8"))
        assert parsed_audit["summary"]["rejected_count"] == 22

        assert prune_platform_rejection_audits(audit_dir, "2026-09-08") == []

        pending_audit = write_platform_rejection_audit(
            audit_dir,
            "2026-09-09",
            "test window",
            {
                "accepted": {"post_id": "accepted", "created_at": "2026-09-09T01:00:00Z"},
                "article": {"post_id": "article", "created_at": "2026-09-09T02:00:00Z"},
            },
            [{"post_id": "accepted"}],
            {
                "article": platform_rejection_detail(
                    "pending_content",
                    "article_content_unavailable",
                )
            },
        )
        assert pending_audit["summary"]["pending_count"] == 1
        assert pending_audit["summary"]["decided_rejected_count"] == 0

    status = collection_status(
        [item],
        candidates_seen=80,
        max_items=None,
        max_candidates=400,
        min_views=100,
        min_likes=5,
        warnings=[],
        source_request_limit_reached=True,
    )
    assert status["status"] == "complete"
    assert status["completion_reason"] == "source_request_limit_reached"
    public_status = public_platform_collection_status(status)
    assert public_status["warnings"] == []

    budget_status = collection_status(
        [item],
        candidates_seen=80,
        max_items=None,
        max_candidates=400,
        min_views=100,
        min_likes=5,
        warnings=["TwitterAPI.io request budget exhausted: 12/12 requests used."],
        source_request_limit_reached=True,
    )
    assert budget_status["status"] == "partial"
    budget_public_status = public_platform_collection_status(budget_status)
    assert budget_public_status["warnings"] == [], "planned source request limit should not create a public warning"

    split_platform = {
        "aliases": ["小红书", "rednote"],
        "query_aliases": ["小红书", "rednote", "#xhs"],
        "query_groups": [
            {"intent_terms": ["养号", "起号", "涨粉"]},
            {"intent_terms": ["变现", "商单", "带货"]},
        ],
        "exclude_terms": ["coupon code"],
    }
    queries = build_platform_queries(split_platform)
    assert len(queries) == 2, "platform trend queries should split into configured topic groups"
    assert all("#xhs" in query for query in queries)
    assert all(len(query) < 180 for query in queries), "split platform trend queries should stay short enough for stable Top search"
    assert platform_query_candidate_limit(400, len(queries)) == 200
    assert platform_query_candidate_limit(400, 5) == 80
    assert platform_query_candidate_limit(600, 6, 100) == 100

    live_config = json.loads((ROOT / "config" / "platform_trends.json").read_text(encoding="utf-8"))
    live_platform = live_config["platforms"]["xiaohongshu"]
    assert len(live_platform["query_groups"]) == 6
    assert "xhs" not in live_platform["query_aliases"]
    assert "#xhs" in live_platform["query_aliases"]
    assert live_platform["max_candidates_per_query"] == 100
    assert live_platform["max_candidates_per_day"] == 600
    assert live_platform["max_source_requests_per_run"] == 50

    globally_seen = {"cross-query"}
    unique_rows, uniqueness = unique_platform_query_rows(
        [
            {"post_id": "first"},
            {"post_id": "first"},
            {"post_id": "cross-query"},
            {"post_id": "second"},
            {},
        ],
        globally_seen,
    )
    assert [post_id for post_id, _ in unique_rows] == ["first", "second"]
    assert uniqueness == {
        "group_unique_candidates": 3,
        "within_query_duplicates": 1,
        "cross_query_duplicates": 1,
        "missing_identifier": 1,
    }

    class GreedyBudgetSource:
        def __init__(self) -> None:
            self.max_requests_per_run = 50
            self.requests_used = 0
            self.request_budget_exhausted = False

        def search_posts(self, query, start_time, end_time, limit, query_type="Latest"):
            rows = []
            while len(rows) < limit:
                if self.requests_used >= self.max_requests_per_run:
                    self.request_budget_exhausted = True
                    if rows:
                        return rows
                    raise ProviderBudgetExceeded("query request allowance exhausted")
                self.requests_used += 1
                rows.append({"post_id": f"{query}-{self.requests_used}"})
            return rows

    greedy_source = GreedyBudgetSource()
    per_group_requests = []
    for query_index in range(6):
        allowance = platform_query_request_allowance(greedy_source, 6 - query_index)
        _, request_stats = search_platform_query_with_budget(
            greedy_source,
            f"query-{query_index}",
            "2026-09-08T00:00:00Z",
            "2026-09-09T00:00:00Z",
            100,
            allowance,
        )
        per_group_requests.append(request_stats["requests_used"])
    assert per_group_requests == [8, 8, 8, 8, 9, 9]
    assert greedy_source.requests_used == 50
    assert greedy_source.max_requests_per_run == 50

    all_targets_status = collection_status(
        [item],
        candidates_seen=600,
        max_items=None,
        max_candidates=600,
        warnings=[],
        source_request_limit_reached=True,
        query_groups_completed=6,
        configured_query_groups=6,
        query_targets_met=6,
    )
    assert all_targets_status["completion_reason"] == "query_group_targets_reached"

    zero_status = collection_status([], candidates_seen=0, max_items=None, max_candidates=400, warnings=["Platform trend source returned no candidates for all configured queries."])
    zero_public_status = public_platform_collection_status(zero_status)
    assert zero_status["status"] == "partial"
    assert zero_public_status["warnings"] == ["平台流变未从数据源取到候选内容，请检查查询配置或稍后补跑。"]
    print("Platform trend tag tests passed.")


if __name__ == "__main__":
    main()
