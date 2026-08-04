"""Build the public daily snapshot. Runs only in GitHub Actions."""
from __future__ import annotations

import json
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import akshare as ak
import requests
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "stocks.json"
NAME_CACHE = ROOT / "data" / "name_zh.json"

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

# 候选池按产业链维护；名称、市值和行情在云端更新时补齐。
# 这里的行业归类是研究标签，不等同于交易所行业分类。
POOLS = {
    ("美股", "AI硬件", "芯片/设备"): "AMD AVGO INTC QCOM MU MRVL ARM TSM ASML AMAT LRCX KLAC SNPS CDNS MCHP NXPI ON MPWR ADI TXN ALAB CRDO LSCC TER SMCI DELL HPE NTAP PSTG WDC STX ANET GLW COHR LITE CIEN KEYS FLEX JBL SANM CLS VRT MOD HIMS".split(),
    ("美股", "AI软件", "软件/平台"): "GOOGL META ORCL CRM ADBE NOW PLTR SNOW DDOG MDB NET PANW CRWD ZS OKTA TEAM HUBS APP PATH AI ESTC DOCU UBER ABNB SHOP AMZN NFLX SPOT RDDT DUOL TEM IOT PCOR".split(),
    ("美股", "算力服务", "云与数据中心"): "AMZN GOOGL MSFT ORCL IBM EQIX DLR CEG VST NRG CORZ IREN CIFR APLD NBIS CRWV BTDR WULF".split(),
    ("美股", "机器人", "机器人/自动化"): "TSLA ISRG SYM ROK TER CGNX ZBRA ABB FANUY YASKY PATH SERV RR MDT BSX".split(),
    ("美股", "创新药", "生物医药"): "LLY NVO JNJ MRK ABBV AMGN GILD REGN VRTX BMY PFE MRNA BIIB ALNY ARGX UCB NVS AZN TMO DHR ILMN CRSP RXRX EXAS".split(),
    ("美股", "传统能源", "油气/综合能源"): "XOM CVX COP EOG OXY SLB HAL MPC VLO PSX LNG KMI WMB OKE FANG DVN CTRA EQT".split(),
    ("美股", "新能源", "新能源/储能"): "NEE FSLR ENPH SEDG RUN BE PLUG FLNC STEM ALB SQM CHPT EVGO".split(),
    ("美股", "金融", "银行/保险/资管"): "JPM BAC WFC C GS MS BLK SCHW AXP V MA COF USB PNC BK STT SPGI MCO CME ICE BRK-B PGR CB AIG".split(),
    ("A股", "AI硬件", "芯片"): "688041 688012 688008 688256 688981 688396 603501 603986 603893 603290 603160 603005 600584 600460 002371 002049 002185 002156 002409 002916 300223 300474 300661 300782 300672 300604 300458 300666 300373 300346 300327 300054".split(),
    ("A股", "AI硬件", "PCB"): "002463 002916 002938 002436 002384 002579 002815 002913 300476 300657 300814 301132 603228 603920 605258 688183".split(),
    ("A股", "AI硬件", "光模块"): "300308 300394 300502 300548 300570 300620 300913 301205 002281 002902 603083 603236 688313 688498".split(),
    ("A股", "AI硬件", "存储/服务器"): "000066 000977 000938 002152 002180 002335 002368 002837 002881 300042 300302 603019 603881 688525".split(),
    ("A股", "AI软件", "软件/应用"): "000034 000158 000555 000938 002230 002236 002405 002410 002439 002415 300033 300058 300166 300188 300229 300253 300271 300339 300454 300496 300624 300678 300682 300738 300846 301236 600271 600536 600588 600570 603039 603019 688111 688158 688318 688561".split(),
    ("A股", "算力服务", "数据中心/IDC"): "000977 002335 002837 300017 300383 300442 300603 300738 600845 601138 603019 603881 603912 688041 688256 000063".split(),
    ("A股", "机器人", "机器人/自动化"): "000333 000425 000837 002008 002050 002472 002527 002747 002896 300024 300124 300161 300222 300276 300607 300660 300747 301029 601100 601689 603283 603486 603666 688017 688165 688320".split(),
    ("A股", "创新药", "创新药/医疗"): "000661 000963 002007 002044 002252 002294 002422 002821 300015 300122 300142 300347 300357 300363 300558 300601 300759 600196 600276 600436 600521 600763 603259 603392 688180 688202 688235 688266 688506 688578".split(),
    ("A股", "传统能源", "煤炭/油气"): "000983 002128 600028 600188 600256 600348 600546 600583 600871 601088 601225 601666 601699 601808 601857 601898 603619".split(),
    ("A股", "新能源", "光伏/电池/电网"): "000400 000591 000875 002129 002202 002459 002466 002487 002506 002594 002709 002812 002865 300014 300274 300316 300450 300750 300751 300763 300769 300827 300919 600438 600522 600732 601012 601615 601865 603185 603659 603806 688223 688390 688599".split(),
    ("A股", "金融", "银行/保险/券商"): "000001 000166 000776 002142 002736 002797 600000 600016 600030 600036 600061 600109 600837 600919 600958 600999 601009 601066 601166 601211 601229 601288 601318 601328 601336 601398 601601 601628 601688 601788 601818 601838 601881 601939 601988 601995".split(),
    ("港股", "AI硬件", "芯片/硬件"): "0981 1347 0522 2400 2855 3690 1810 0992 0669 2382 3888 1348 1970 6088 0780".split(),
    ("港股", "AI软件", "平台/应用"): "0700 9988 3690 9618 9999 1024 1810 3888 0241 0772 2013 2015 9626 9866 9899 6618 9961 9888 9992 7800".split(),
    ("港股", "算力服务", "云与运营商"): "0941 0762 0728 1686 9698 3888 2400 2855".split(),
    ("港股", "机器人", "机器人/自动化"): "0522 0669 1302 2252 2432 9880 9868 1211".split(),
    ("港股", "创新药", "创新药/医疗"): "2269 1177 1093 6160 1801 2359 9969 9926 1877 1548 2171 6996 8537 9688 3692 3347 1952 0867 6855 3759".split(),
    ("港股", "传统能源", "油气/煤炭"): "0857 0883 0386 1088 1898 1171 0836 2688 1193".split(),
    ("港股", "新能源", "新能源/电力"): "1211 0968 1772 3800 1798 0916 0956 0836 1811 6865 2380 2208 3393".split(),
    ("港股", "金融", "银行/保险/交易所"): "0005 0011 0023 0388 0939 1398 2318 2628 3328 3968 3988 6060 6837 6886 9668 9987".split(),
}


def expanded_base():
    existing = {item["c"]: deepcopy(item) for item in BASE}
    sector_defaults = {
        "AI硬件": (76, 82, 64, 72), "AI软件": (75, 80, 64, 71),
        "算力服务": (74, 79, 63, 69), "机器人": (72, 78, 61, 68),
        "创新药": (74, 76, 62, 68), "传统能源": (77, 60, 78, 76),
        "新能源": (73, 72, 70, 69), "金融": (79, 61, 81, 78),
    }
    for (market, sector, sub), codes in POOLS.items():
        q, g, v, r = sector_defaults[sector]
        for code in codes:
            if code in existing:
                continue
            ticker = code
            if market == "A股":
                ticker += ".SS" if code.startswith("6") else ".SZ"
            elif market == "港股":
                ticker = f"{int(code):04d}.HK"
            score = round(q * .35 + g * .25 + v * .2 + r * .2, 1)
            grade = "A" if score >= 80 else "B"
            existing[code] = dict(m=market, c=code, yf=ticker, n=code, s=sector,
                sub=sub, score=score, q=q, g=g, v=v, r=r, grade=grade,
                t="已进入产业链候选池，等待财报因子和竞争力指标进一步验证。",
                risk="当前为初筛候选，需结合最新财报、估值和行业景气度复核。")
    return list(existing.values())


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
        stocks = payload.get("stocks", [])
        if not isinstance(stocks, list):
            return {}
        return {x["c"]: x for x in stocks if isinstance(x, dict) and x.get("c")}
    except Exception:
        return {}


def apply_name_cache(stocks):
    try:
        names = json.loads(NAME_CACHE.read_text(encoding="utf-8"))
    except Exception:
        names = {}
    for item in stocks:
        name = names.get(item["m"] + ":" + item["c"])
        if name:
            item["name_zh"] = name
            item["n"] = name


def price_label(market, price):
    prefix = {"美股": "$", "港股": "HK$", "A股": "¥"}[market]
    return f"{prefix}{price:,.2f}"


def update_prices(stocks, errors):
    ticker_map = {item["yf"]: item for item in stocks}
    try:
        history = yf.download(list(ticker_map), period="1y", interval="1d",
            auto_adjust=False, group_by="ticker", threads=True, progress=False,
            timeout=30)
    except Exception as exc:
        errors.append(f"batch price: {type(exc).__name__}")
        history = None
    for ticker, item in ticker_map.items():
        try:
            if history is None:
                raise ValueError("no batch")
            if len(ticker_map) == 1:
                close = history["Close"].dropna()
            else:
                close = history[ticker]["Close"].dropna()
            last = finite(close.iloc[-1])
            prev = finite(close.iloc[-2]) if len(close) > 1 else None
            if last is None:
                raise ValueError("no close")
            item["p"] = price_label(item["m"], last)
            item["price_value"] = round(last, 6)
            item["chg"] = round((last / prev - 1) * 100, 2) if prev else 0
            item["price_date"] = str(close.index[-1].date())
            if len(close) >= 60:
                returns = close.pct_change().dropna()
                item["volatility_60d"] = round(float(returns.iloc[-60:].std()) * (252 ** .5), 6)
                peak = close.cummax()
                item["drawdown_1y"] = round(float((close / peak - 1).min()), 6)
            if len(close) >= 120:
                item["momentum_6m"] = round(float(last / close.iloc[-120] - 1), 6)
        except Exception as exc:
            errors.append(f'{item["c"]} price: {type(exc).__name__}')
        item.pop("yf", None)


def spot_metadata(stocks, errors):
    """One request per market supplies display names and A-share float caps."""
    float_caps = {}
    loaders = {
        "A股": getattr(ak, "stock_zh_a_spot_em", None),
        "港股": getattr(ak, "stock_hk_spot_em", None),
        "美股": getattr(ak, "stock_us_spot_em", None),
    }
    by_market = {m: {} for m in loaders}
    for item in stocks:
        by_market[item["m"]][item["c"]] = item
    for market, loader in loaders.items():
        if loader is None:
            errors.append(f"{market} metadata: unavailable")
            continue
        try:
            frame = loader()
            code_col = find_column(frame, ["代码"])
            name_col = find_column(frame, ["名称"])
            float_col = find_column(frame, ["流通", "市值"])
            total_col = find_column(frame, ["总", "市值"])
            if code_col is None or name_col is None:
                raise RuntimeError("metadata columns changed")
            for _, row in frame.iterrows():
                raw = str(row[code_col])
                code = raw.split(".")[-1] if market == "美股" else raw.split(".")[0]
                code = code.zfill(4 if market == "港股" else 6) if market != "美股" else code
                item = by_market[market].get(code) or by_market[market].get(code.lstrip("0"))
                if item:
                    item["n"] = str(row[name_col]).strip() or item["n"]
                    if total_col is not None:
                        cap = finite(row[total_col])
                        if cap:
                            item["market_cap"] = cap
                    if float_col is not None:
                        cap = finite(row[float_col])
                        if cap:
                            item["float_cap"] = cap
                            if market == "A股":
                                float_caps[item["c"]] = cap
        except Exception as exc:
            errors.append(f"{market} metadata: {type(exc).__name__}")
    # GitHub 云端偶尔无法访问东方财富。腾讯行情用于补中文简称，
    # Yahoo 只补仍缺失的名称和市值，不覆盖已取得的中文名。
    tencent_names(stocks, errors)

    # 对缺失项用 Yahoo 元数据回退，
    # 并控制并发，避免一次失败影响整个股票池。
    fundamental_keys = ("roe", "profit_margin", "debt_to_equity", "revenue_growth",
        "earnings_growth", "trailing_pe", "price_to_book", "beta")
    missing = [x for x in stocks if x.get("n") == x["c"] or
        not x.get("market_cap") or (x["m"] == "A股" and not x.get("float_cap")) or
        sum(x.get(key) is not None for key in fundamental_keys) < 5]

    def load_one(item):
        info = yf.Ticker(item["yf"]).get_info()
        name = info.get("longName") or info.get("shortName")
        total = finite(info.get("marketCap"))
        float_shares = finite(info.get("floatShares"))
        shares = finite(info.get("sharesOutstanding"))
        float_cap = total * float_shares / shares if total and float_shares and shares else None
        factors = {
            "roe": finite(info.get("returnOnEquity")),
            "profit_margin": finite(info.get("profitMargins")),
            "debt_to_equity": finite(info.get("debtToEquity")),
            "revenue_growth": finite(info.get("revenueGrowth")),
            "earnings_growth": finite(info.get("earningsGrowth")),
            "trailing_pe": finite(info.get("trailingPE")),
            "price_to_book": finite(info.get("priceToBook")),
            "beta": finite(info.get("beta")),
            "free_cashflow": finite(info.get("freeCashflow")),
        }
        return item, name, total, float_cap, factors

    if missing:
        failures = 0
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(load_one, item) for item in missing]
            for future in as_completed(futures):
                try:
                    item, name, total, float_cap, factors = future.result()
                    if name and not item.get("name_zh") and (not item.get("n") or item.get("n") == item["c"]):
                        item["n"] = str(name).strip()
                    if total:
                        item["market_cap"] = total
                    if float_cap:
                        item["float_cap"] = float_cap
                        if item["m"] == "A股":
                            float_caps[item["c"]] = float_cap
                    for key, value in factors.items():
                        if value is not None:
                            item[key] = value
                except Exception:
                    failures += 1
        if failures:
            errors.append(f"Yahoo metadata failures: {failures}/{len(missing)}")
    return float_caps


def tencent_names(stocks, errors):
    query_map = {}
    for item in stocks:
        if item["m"] == "A股":
            key = ("sh" if item["c"].startswith("6") else "sz") + item["c"]
        elif item["m"] == "港股":
            key = "hk" + item["c"].zfill(5)
        else:
            key = "us" + item["c"].replace("-", ".")
        query_map[key.lower()] = item
    keys = list(query_map)
    failures = 0
    for start in range(0, len(keys), 50):
        batch = keys[start:start + 50]
        try:
            response = requests.get("https://qt.gtimg.cn/q=" + ",".join(batch),
                timeout=20, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
            response.encoding = "gbk"
            for key, body in re.findall(r'v_([^=]+)="([^"]*)"', response.text):
                item = query_map.get(key.lower())
                parts = body.split("~")
                if item and len(parts) > 1 and parts[1].strip():
                    item["name_zh"] = parts[1].strip()
                    item["n"] = item["name_zh"]
        except Exception:
            failures += 1
    if failures:
        errors.append(f"Tencent name batches failed: {failures}")


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


def update_a_margin(stocks, errors, float_caps):
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
            cap = float_caps.get(item["c"])
            if cap:
                item["fr"] = round(balance / cap * 100, 2)
            item["margin_date"] = margin_date


def percentile_scores(stocks, key, higher=True, valid=None):
    result = {}
    groups = {}
    for item in stocks:
        value = finite(item.get(key))
        if value is None or (valid and not valid(value)):
            continue
        groups.setdefault((item["m"], item["s"]), []).append((value, item["m"] + ":" + item["c"]))
    for rows in groups.values():
        rows.sort(key=lambda x: x[0], reverse=not higher)
        size = len(rows)
        for rank, (_, identity) in enumerate(rows):
            # 收缩到 5–95，避免样本内第一/最后被误解为绝对满分或零分。
            result[identity] = 50.0 if size == 1 else 5 + rank / (size - 1) * 90
    return result


def rescore(stocks):
    specs = {
        "roe": (True, None), "profit_margin": (True, None),
        "debt_to_equity": (False, lambda x: x >= 0),
        "revenue_growth": (True, None), "earnings_growth": (True, None),
        "momentum_6m": (True, None),
        "trailing_pe": (False, lambda x: x > 0),
        "price_to_book": (False, lambda x: x > 0),
        "volatility_60d": (False, lambda x: x >= 0),
        "drawdown_1y": (True, lambda x: x <= 0),
        "beta": (False, lambda x: x >= 0),
    }
    ranks = {key: percentile_scores(stocks, key, higher, valid)
        for key, (higher, valid) in specs.items()}
    groups = {
        "q": ["roe", "profit_margin", "debt_to_equity"],
        "g": ["revenue_growth", "earnings_growth", "momentum_6m"],
        "v": ["trailing_pe", "price_to_book"],
        "r": ["volatility_60d", "drawdown_1y", "beta"],
    }
    for item in stocks:
        identity = item["m"] + ":" + item["c"]
        present = 0
        for score_key, factor_keys in groups.items():
            values = []
            for factor in factor_keys:
                if identity in ranks[factor]:
                    values.append(ranks[factor][identity])
                    present += 1
            item[score_key] = round(sum(values) / len(values), 1) if values else 50.0
        # 融资拥挤只作为A股风险扣分项。
        if item["m"] == "A股":
            crowd_penalty = max(0, (finite(item.get("fr")) or 0) - 3) * 2
            growth_penalty = max(0, (finite(item.get("f20")) or 0) - 10) * .25
            item["r"] = round(max(0, item["r"] - min(15, crowd_penalty + growth_penalty)), 1)
        item["score"] = round(item["q"] * .35 + item["g"] * .25 +
            item["v"] * .2 + item["r"] * .2, 1)
        item["factor_coverage"] = round(present / len(specs) * 100)
        item["grade"] = "S" if item["score"] >= 85 else "A" if item["score"] >= 70 else "B"


def main():
    previous = load_previous() or {}
    stocks = expanded_base()
    apply_name_cache(stocks)
    for item in stocks:
        old = previous.get(item["c"], {})
        for field in ("n", "name_zh", "p", "price_value", "chg", "price_date", "fb", "fr", "f20",
                "margin_date", "market_cap", "float_cap", "roe", "profit_margin",
                "debt_to_equity", "revenue_growth", "earnings_growth", "trailing_pe",
                "price_to_book", "beta", "free_cashflow", "momentum_6m",
                "volatility_60d", "drawdown_1y"):
            if field in old:
                if field != "n" or (not item.get("name_zh") and old[field] != item["c"]):
                    item[field] = old[field]
    errors = []
    float_caps = spot_metadata(stocks, errors)
    update_prices(stocks, errors)
    update_a_margin(stocks, errors, float_caps)
    rescore(stocks)
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
