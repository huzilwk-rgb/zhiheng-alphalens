"""Build the public daily snapshot. Runs only in GitHub Actions."""
from __future__ import annotations

import json
import math
import time
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import akshare as ak
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "stocks.json"

BASE = [
    dict(m="A股", c="300308", yf="300308.SZ", n="中际旭创", s="AI硬件", sub="光模块", score=91.8, q=92, g=96, v=72, r=86, grade="S", t="高速光模块需求与产品迭代构成核心增长驱动，盈利质量较强。", risk="客户集中度与海外需求波动仍需持续跟踪。"),
    dict(m="美股", c="NVDA", yf="NVDA", n="NVIDIA", s="AI硬件", sub="AI芯片", score=90.4, q=97, g=94, v=59, r=84, grade="S", t="平台生态、软硬件协同和规模优势构成较深护城河。", risk="高预期定价与客户资本开支周期是主要风险。"),
    dict(m="美股", c="MSFT", yf="MSFT", n="Microsoft", s="AI软件", sub="企业AI平台", score=88.9, q=96, g=86, v=65, r=91, grade="S", t="云平台、企业分发和现金流形成AI商业化闭环。", risk="AI资本开支回报与云业务利润率需持续验证。"),
    dict(m="A股", c="002463", yf="002463.SZ", n="沪电股份", s="AI硬件", sub="PCB", score=87.6, q=90, g=91, v=75, r=82, grade="A", t="高端PCB结构升级与数据中心需求提升产品价值量。", risk="估值扩张后需要订单和盈利持续兑现。"),
    dict(m="港股", c="0700", yf="0700.HK", n="腾讯控股", s="AI软件", sub="AI应用", score=87.1, q=94, g=83, v=78, r=86, grade="A", t="高质量现金流、用户生态和AI工具提升广告与内容效率。", risk="新业务投入回报及监管变化仍是观察项。"),
    dict(m="美股", c="LLY", yf="LLY", n="Eli Lilly", s="创新药", sub="代谢疾病", score=86.3, q=94, g=93, v=50, r=83, grade="A", t="商业化能力、代谢管线与研发平台支撑长期成长。", risk="估值较高，产能兑现和竞品进展影响预期。"),
    dict(m="A股", c="300750", yf="300750.SZ", n="宁德时代", s="新能源", sub="动力电池", score=85.7, q=92, g=82, v=77, r=80, grade="A", t="技术、规模和客户结构构成全球电池产业链优势。", risk="行业价格竞争、资本开支与海外政策风险需跟踪。"),
    dict(m="港股", c="0981", yf="0981.HK", n="中芯国际", s="AI硬件", sub="半导体制造", score=85.2, q=85, g=87, v=76, r=77, grade="A", t="本土制造需求与成熟制程利用率改善提供支撑。", risk="重资产投入、周期波动与技术限制影响估值上限。"),
    dict(m="A股", c="601398", yf="601398.SS", n="工商银行", s="金融", sub="银行", score=81.6, q=88, g=60, v=91, r=89, grade="A", t="资产质量、资本实力和股东回报提供防御属性。", risk="净息差下行与宏观信用成本是核心跟踪变量。"),
    dict(m="美股", c="XOM", yf="XOM", n="Exxon Mobil", s="传统能源", sub="综合油气", score=80.9, q=88, g=60, v=86, r=82, grade="A", t="低成本资源、资本纪律和股东回报构成周期防御。", risk="油气价格和地缘政治变化决定盈利弹性。"),
    dict(m="港股", c="3690", yf="3690.HK", n="美团", s="AI软件", sub="本地生活", score=78.7, q=85, g=79, v=70, r=66, grade="B", t="高频本地生活网络具备规模和数据优势。", risk="竞争投入、利润率波动与新业务回报存在不确定性。"),
    dict(m="A股", c="688256", yf="688256.SS", n="寒武纪", s="AI硬件", sub="AI芯片", score=75.8, q=66, g=94, v=38, r=61, grade="B", t="国产AI芯片稀缺性较高，收入处于快速成长阶段。", risk="估值、盈利确定性和融资拥挤度均触发高风险提示。"),
]


def finite(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def load_previous():
    if not OUTPUT.exists():
        return {}
    try:
        payload = json.loads(OUTPUT.read_text(encoding="utf-8"))
        return {x["c"]: x for x in payload.get("stocks", [])}
    except Exception:
        return {}


def price_label(market, price):
    prefix = {"美股": "$", "港股": "HK$", "A股": "¥"}[market]
    return f"{prefix}{price:,.2f}"


def update_prices(stocks, errors):
    for item in stocks:
        try:
            hist = yf.Ticker(item.pop("yf")).history(period="7d", interval="1d", auto_adjust=False)
            close = hist["Close"].dropna()
            if len(close) < 1:
                raise ValueError("no close")
            last = finite(close.iloc[-1])
            prev = finite(close.iloc[-2]) if len(close) > 1 else None
            item["p"] = price_label(item["m"], last)
            item["chg"] = round((last / prev - 1) * 100, 2) if prev else 0
            item["price_date"] = str(close.index[-1].date())
        except Exception as exc:
            item.pop("yf", None)
            errors.append(f'{item["c"]} price: {type(exc).__name__}')
        time.sleep(0.15)


def find_column(frame, words):
    for column in frame.columns:
        label = str(column).replace(" ", "")
        if all(word in label for word in words):
            return column
    return None


def margin_frame(exchange, target):
    name = "stock_margin_detail_sse" if exchange == "sh" else "stock_margin_detail_szse"
    func = getattr(ak, name, None)
    if func is None:
        raise RuntimeError(f"{name} unavailable")
    for offset in range(9):
        day = target - timedelta(days=offset)
        if day.weekday() > 4:
            continue
        try:
            frame = func(date=day.strftime("%Y%m%d"))
            if frame is not None and not frame.empty:
                return frame, day.date().isoformat()
        except Exception:
            continue
    raise RuntimeError("no recent margin snapshot")


def margin_map(frame):
    code_col = find_column(frame, ["证券", "代码"]) or find_column(frame, ["代码"])
    balance_col = find_column(frame, ["融资", "余额"])
    if code_col is None or balance_col is None:
        raise RuntimeError("margin columns changed")
    result = {}
    for _, row in frame.iterrows():
        code = str(row[code_col]).split(".")[0].zfill(6)
        value = finite(row[balance_col])
        if value is not None:
            result[code] = value
    return result


def floating_cap(code):
    frame = ak.stock_individual_info_em(symbol=code)
    key_col, value_col = frame.columns[:2]
    for _, row in frame.iterrows():
        if "流通市值" in str(row[key_col]):
            return finite(row[value_col])
    return None


def update_a_margin(stocks, errors):
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    for exchange in ("sh", "sz"):
        try:
            current_frame, margin_date = margin_frame(exchange, now)
            old_frame, _ = margin_frame(exchange, now - timedelta(days=28))
            current, old = margin_map(current_frame), margin_map(old_frame)
        except Exception as exc:
            errors.append(f"{exchange} margin: {type(exc).__name__}")
            continue
        for item in stocks:
            if item["m"] != "A股" or (item["c"].startswith("6")) != (exchange == "sh"):
                continue
            balance = current.get(item["c"])
            if balance is None:
                continue
            item["fb"] = round(balance / 100_000_000, 2)
            previous = old.get(item["c"])
            if previous:
                item["f20"] = round((balance / previous - 1) * 100, 2)
            try:
                cap = floating_cap(item["c"])
                if cap:
                    item["fr"] = round(balance / cap * 100, 2)
            except Exception as exc:
                errors.append(f'{item["c"]} float cap: {type(exc).__name__}')
            item["margin_date"] = margin_date


def main():
    previous = load_previous()
    stocks = deepcopy(BASE)
    for item in stocks:
        old = previous.get(item["c"], {})
        for field in ("p", "chg", "price_date", "fb", "fr", "f20", "margin_date"):
            if field in old:
                item[field] = old[field]
    errors = []
    update_prices(stocks, errors)
    update_a_margin(stocks, errors)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
        "data_type": "free_delayed_daily",
        "score_type": "research_model_baseline",
        "sources": ["Yahoo Finance via yfinance", "SSE/SZSE via AKShare"],
        "errors": errors,
        "stocks": stocks,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"updated {len(stocks)} stocks; warnings={len(errors)}")


if __name__ == "__main__":
    main()

