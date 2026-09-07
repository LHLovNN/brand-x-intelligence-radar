from __future__ import annotations

import re
import unicodedata
from typing import Any


BLOCKED_BRAND_AUTHOR_HANDLES = {
    "ctsurvivor17",
}

BRAND_SENSITIVE_OFF_TOPIC_PATTERNS = {
    "political_conspiracy": re.compile(
        r"\b(?:antifa|maga|qteam|stolenvalor|stoicpredo|team trump|president trump)\b",
        re.IGNORECASE,
    ),
    "child_exploitation_claims": re.compile(
        r"\b(?:epstein island|lolita express|child trafficking|trafficked children)\b",
        re.IGNORECASE,
    ),
    "political_violence_claims": re.compile(
        r"\b(?:assassination attempts?|terrorist|cultists?)\b",
        re.IGNORECASE,
    ),
}

CONTEXT_LOW_QUALITY_PATTERNS = [
    re.compile(r"应该没人比我玩[的得]开了吧", re.IGNORECASE),
    re.compile(r"我[福肤]不黑不信你看", re.IGNORECASE),
    re.compile(
        r"比(?:我|你|他|她|ta).{0,4}好看的没(?:我|你|他|她|ta).{0,4}骚.{0,20}"
        r"比(?:我|你|他|她|ta).{0,4}骚的没(?:我|你|他|她|ta).{0,4}好看",
        re.IGNORECASE,
    ),
    re.compile(
        r"比(?:我|你|他|她|ta).{0,4}好看的没.{0,10}骚.{0,24}"
        r"比(?:我|你|他|她|ta).{0,4}骚的没.{0,10}好看",
        re.IGNORECASE,
    ),
    re.compile(r"只入身体.{0,20}不入生活", re.IGNORECASE),
    re.compile(r"我果然太[涩色瑟]了.{0,16}有人想锐评一下我的[福肤]嘛", re.IGNORECASE),
    re.compile(r"sao.{0,8}货.{0,16}没人比(?:她|他|ta)sao", re.IGNORECASE),
    re.compile(r"(?:\d+\+)?(?:果然)?太[涩色瑟]了.{0,16}我真顶不住", re.IGNORECASE),
    re.compile(r"她太[涩色瑟]了.{0,16}我真顶不住", re.IGNORECASE),
    re.compile(r"主页.{0,16}能打(?:✈|🛩️?|飞机)", re.IGNORECASE),
    re.compile(r"玩归玩闹归闹.{0,24}给(?:你|妳)?看[福肤].{0,24}不开玩笑", re.IGNORECASE),
    re.compile(
        r"(?:小红书|快手|抖音).{0,12}(?:违规|发不出).{0,24}(?:推特|twitter|x).{0,80}"
        r"(?:开脱|上供|luo照|裸照|锐评一下不许说我|🐻黑|粉嫩的[福肤])",
        re.IGNORECASE,
    ),
    re.compile(r"(?:开脱|上供).{0,30}(?:luo照|裸照|锐评一下不许说我|🐻黑|粉嫩的[福肤])", re.IGNORECASE),
    re.compile(r"玩的就是反差.{0,30}身体已经软.{0,30}想被狠狠欺负", re.IGNORECASE),
]

CONTEXT_LOW_QUALITY_PROFILE_PATTERNS = [
    re.compile(
        r"找炮友|约炮|约p|曰炮|固炮|入驻.{0,12}(?:炮|约p)平台|真人认证.{0,30}隐私|"
        r"附近的可加v|小号已禁言|涩播|涩涩|寻欢必备|远程指挥直播控制玩具|同城.{0,8}线下|绿泡泡",
        re.IGNORECASE,
    ),
]

PLATFORM_HARD_NOISE_TERMS = [
    "@abuincrease",
    "@pichai666",
    "51平台",
    "约炮",
    "约p",
    "固炮",
    "炮友",
    "涩播",
    "约会软件",
    "成人交友",
    "小黄书",
    "删帖",
    "删除微信公众号文章",
    "删除微博",
    "删除推特",
    "负面信息",
    "负面内容",
    "清除负面",
    "消除差评",
    "差评处理",
    "账号解封",
    "微信解封",
    "电报号解封",
    "封号处理",
    "封禁解除",
    "店铺封禁",
    "视频下架",
    "笔记下架",
    "商品屏蔽",
    "代举报",
    "投诉链接",
    "聊天记录查询",
    "酒店入住记录",
    "手机定位",
    "定位追踪",
    "老牌服务商",
    "老字号服务",
    "专业品牌客服",
    "上市失败",
    "涉企网络谣言",
    "行政拘留",
    "警方披露",
    "不给我流量",
    "没招了",
    "摸鱼真开心",
    "小游戏功能",
    "日入 1 元",
    "金融市场",
    "bnbchain",
    "苏丹的游戏",
    "金属书签",
    "手账本",
    "开放权重多模态模型",
    "tutti",
    "x创作者收益",
    "生日快乐",
    "阴阳怪气",
    "虐待动物",
    "虐杀动物",
    "虐猫",
    "动物保护组织",
    "通报执法",
    "feline guardians",
    "lady freethinker",
    "stop animal cruelty",
    "stop cat torture",
    "justice for animals",
    "justiceforanimals",
    "justiceforwangwang",
]

PLATFORM_HARD_NOISE_PATTERNS = [
    *CONTEXT_LOW_QUALITY_PATTERNS[-3:],
]

TG_LOW_VALUE_ADULT_PATTERNS = [
    re.compile(r"打飞机|撸管|约炮|找炮友|炮友|曰炮", re.IGNORECASE),
    re.compile(r"解决性欲|性欲成本|全民打飞机", re.IGNORECASE),
    re.compile(r"只入身体.{0,30}不入生活", re.IGNORECASE),
    re.compile(r"(?:被操|操到).{0,40}(?:失禁|喷水|骚穴|流水不停)", re.IGNORECASE),
    re.compile(r"(?:骚穴|失禁喷水)", re.IGNORECASE),
]

TG_REPLY_BLOCK_PATTERNS = [
    re.compile(r"打飞机|撸管|约炮|找炮友|炮友|裸聊|色情网|成人视频|情色|援交|招嫖|嫖娼|外围", re.IGNORECASE),
    re.compile(r"加(?:微信|薇|v|qq)|私聊.{0,12}(?:资源|福利|群)|点击.{0,10}(?:领取|下载)|博彩|网赌|现金网|返佣", re.IGNORECASE),
    re.compile(r"傻逼|脑残|滚蛋|去死|死全家", re.IGNORECASE),
    re.compile(r"几把|鸡巴|鸡掰|操你|草泥马|妈的|日你|艹|cnm|nmsl", re.IGNORECASE),
    re.compile(r"(?:没|吃|拉|满嘴|一坨).{0,3}屎", re.IGNORECASE),
    re.compile(r"阿三|印度蚊子|黑鬼|支那|nigger|chink|印度人.{0,16}(?:不如|可怕|滚|狗|灾难|不敢想)", re.IGNORECASE),
    re.compile(r"买枪|卖枪|毒品|冰毒|K粉|代办身份证|洗钱", re.IGNORECASE),
]

TG_SHORT_STATUS_CHATTER_RE = re.compile(
    r"(?:挂了|又挂|崩了|炸了|宕机|不能用|用不了|不可用|打不开)",
    re.IGNORECASE,
)
TG_SHORT_CHATTER_RE = re.compile(r"什么情况|真的假的|咋回事|有人知道|笑死|离谱|绷不住", re.IGNORECASE)
TG_REPLY_LOW_SIGNAL_RE = re.compile(r"^(哈+|哈哈哈+|笑死|666+|顶|蹲|mark|收藏|学习了|\+1|牛+|牛逼|nb|ok|好)$", re.IGNORECASE)


def compact_policy_text(value: Any) -> str:
    visible = "".join(char for char in str(value or "") if unicodedata.category(char) != "Cf")
    return re.sub(r"\s+", "", visible)


def brand_post_policy_reasons(post: dict[str, Any], matching_text: str) -> list[str]:
    reasons: list[str] = []
    handle = str(post.get("author_handle") or "").strip().lstrip("@").lower()
    if handle in BLOCKED_BRAND_AUTHOR_HANDLES:
        reasons.append("blocked_author")
    sensitive_hits = [
        label
        for label, pattern in BRAND_SENSITIVE_OFF_TOPIC_PATTERNS.items()
        if pattern.search(matching_text)
    ]
    if len(sensitive_hits) >= 2:
        reasons.append("off_topic_sensitive_thread")
    return reasons


def context_noise_reason(row: dict[str, Any]) -> str | None:
    text = " ".join(
        str(value or "")
        for value in (row.get("translation_zh"), row.get("clean_text"), row.get("text"))
        if value
    )
    compact = compact_policy_text(text)
    if any(pattern.search(compact) for pattern in CONTEXT_LOW_QUALITY_PATTERNS):
        return "low_quality_text"
    profile = " ".join(
        str(value or "")
        for value in (row.get("author_name"), row.get("author_handle"), row.get("author_bio"))
        if value
    )
    compact_profile = compact_policy_text(profile)
    if any(pattern.search(compact_profile) for pattern in CONTEXT_LOW_QUALITY_PROFILE_PATTERNS):
        return "low_quality_profile"
    return None


def platform_noise_reason(text: str) -> str | None:
    lower = str(text or "").lower()
    if any(term.lower() in lower for term in PLATFORM_HARD_NOISE_TERMS):
        return "hard_noise_term"
    compact = compact_policy_text(lower)
    if any(pattern.search(compact) for pattern in PLATFORM_HARD_NOISE_PATTERNS):
        return "hard_noise_pattern"
    return None


def tg_item_policy_reason(title: str, summary: str, extra_text: str = "") -> str | None:
    full_text = " ".join(value for value in (title, summary, extra_text) if value)
    compact_full_text = compact_policy_text(full_text)
    if any(pattern.search(compact_full_text) for pattern in TG_LOW_VALUE_ADULT_PATTERNS):
        return "low_value_adult"

    clean_title = re.sub(r"\s+", " ", str(title or "")).strip()
    clean_summary = re.sub(r"\s+", " ", str(summary or "")).strip()
    summary_adds_signal = bool(clean_summary) and compact_policy_text(clean_summary) != compact_policy_text(clean_title)
    short_text = clean_title or clean_summary
    short_signal_length = signal_char_count(short_text)
    if not summary_adds_signal and short_signal_length <= 18 and TG_SHORT_STATUS_CHATTER_RE.search(short_text):
        return "short_status_chatter"
    if not summary_adds_signal and short_signal_length <= 12 and (
        short_text.rstrip().endswith(("?", "？")) or TG_SHORT_CHATTER_RE.search(short_text)
    ):
        return "short_status_chatter"
    return None


def tg_reply_policy_reason(text: str, sender: str = "", has_media: bool = False) -> str | None:
    if not str(text or "").strip() and not has_media:
        return "empty"
    compact = compact_policy_text(f"{sender} {text}")
    if any(pattern.search(compact) for pattern in TG_REPLY_BLOCK_PATTERNS):
        return "blocked"
    if not has_media:
        signal_length = signal_char_count(text)
        if signal_length <= 1:
            return "low_signal"
        if signal_length <= 8 and TG_REPLY_LOW_SIGNAL_RE.search(compact):
            return "low_signal"
    return None


def signal_char_count(value: str) -> int:
    without_urls = re.sub(r"https?://\S+", "", str(value or ""), flags=re.IGNORECASE)
    return len(re.findall(r"[A-Za-z0-9\u3400-\u9fff]", without_urls))
