"""Freeze twenty new acceptance questions against 117 immutable raw notes."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

import yaml

from materialize_snapshot import materialize


ROOT = Path(__file__).resolve().parent
ROUND3 = ROOT.parents[1] / "round3"
UNITS = {"hp": "HP", "kw": "kW", "max_flow_lpm": "LPM",
         "rated_flow_lpm": "LPM", "max_head_m": "m", "rated_head_m": "m",
         "solids_mm": "mm", "weight_1ph_kg": "kg", "weight_3ph_kg": "kg",
         "current_1ph_a": "A", "current_3ph_a": "A", "outlet_inch": "吋"}

# Model sets and the requested numeric values were written by hand after
# reading all 117 raw rows, before any acceptance answers were generated.
MANUAL = {
    "F01": ("hp max_flow_lpm", [
        ("80DIVA-5.30", 3, 1250), ("80DIVA-5.50", 5, 1500),
        ("80EDW-5.20S/T", 2, 820), ("80EDW-5.30S/T", 3, 980),
        ("80EDW-5.50T", 5, 1040), ("80EUB-M-5.20T", 2, 630),
        ("80EUB-M-5.30T", 3, 700), ("80EUB-M-5.50T", 5, 900),
        ("80EUS-5.20", 2, 658), ("80STEEL-5.20", 2, 630),
        ("80STEEL-5.30", 3, 700), ("80STEEL-5.50", 5, 1000),
        ("80LEOPARD-5.30", 3, 1400), ("HIPPO-150 DN80", 1.5, 630),
        ("HIPPO-200 DN80", 2, 780), ("HIPPO-300 DN80", 3, 1100),
        ("HIPPO-400 DN80", 4, 1200)]),
    "F02": ("hp max_flow_lpm", [
        ("50EUS-5.20", 2, 658), ("50EUS-5.20C", 2, 500),
        ("50EUB-M-5.20S", 2, 500), ("50STEEL-5.20", 2, 630),
        ("HIPPO-100", 1, 500), ("HIPPO-100Q", 1, 500),
        ("HIPPO-150", 1.5, 580), ("HIPPO-150Q", 1.5, 580),
        ("HIPPO-200", 2, 660), ("HIPPO-200Q", 2, 660)]),
    "F03": ("hp solids_mm max_flow_lpm", [
        ("HIPPO-300 DN80", 3, 76, 1100), ("HIPPO-400 DN65", 4, 65, 1000),
        ("HIPPO-400 DN80", 4, 76, 1200), ("HIPPO-550 DN65", 5.5, 65, 1200),
        ("HIPPO-550 DN80", 5.5, 76, 1350), ("HIPPO-750 DN80", 7.5, 76, 1600),
        ("HIPPO-750H DN80", 7.5, 76, 1100),
        ("100LEOPARD-5.50", 5, 80, 1900), ("100LEOPARD-5.75", 7.5, 68, 2300)]),
    "F04": ("kw hp max_flow_lpm", [
        ("100DIVA-5.50", 3.7, 5, 1600), ("100EDW-5.50T", 3.7, 5, 1680),
        ("100EUB-M-5.50T", 3.7, 5, 1400),
        ("100LEOPARD-5.50", 3.7, 5, 1900), ("100STEEL-5.50", 3.7, 5, 1000)]),
    "F05": ("kw max_flow_lpm", [
        ("80DIVA-5.30", 2.2, 1250), ("80DIVA-5.50", 3.7, 1500),
        ("80EUB-M-5.75T", 5.5, 1200), ("80LEOPARD-5.30", 2.2, 1400),
        ("HIPPO-400 DN80", 3, 1200), ("HIPPO-550 DN80", 4.1, 1350),
        ("HIPPO-750 DN80", 5.5, 1600)]),
    "F06": ("rated_flow_lpm", [
        ("50EUS-5.20", 315), ("50EUS-5.20C", 250),
        ("80EUS-5.10L", 290), ("80EUS-5.20", 315), ("80EUS-5.20C", 250)]),
    "F07": ("max_flow_lpm weight_1ph_kg", [
        ("HIPPO-200", 660, 25.2), ("HIPPO-200Q", 660, 27.2),
        ("HIPPO-150", 580, 24.2), ("HIPPO-150Q", 580, 26.2),
        ("HIPPO-100", 500, 15.4), ("HIPPO-100Q", 500, 16.8),
        ("HIPPO-75", 390, 13.9), ("HIPPO-75Q", 390, 15.3),
        ("HIPPO-50", 330, 12.9), ("HIPPO-50Q", 330, 14.3)]),
    "F08": ("max_flow_lpm max_head_m outlet_inch", [
        ("150DIVA-5.200", 6200, 22, 6),
        ("150DIVA PRO-5.200", 6200, 22, 6),
        ("200DIVA-5.200", 6200, 22, 8)]),
    "F09": ("solids_mm max_flow_lpm", [
        ("50STEEL-5.30", 45, 700), ("80STEEL-5.30", 45, 700),
        ("HIPPO-300 DN80", 76, 1100),
        ("80LEOPARD-5.30", 56, 1400), ("100LEOPARD-5.30", 56, 1400)]),
    "F10": ("max_head_m hp kw", [
        ("150EUB-M-5.200", 54, 20, 15),
        ("100EUB-M-5.150", 50, 15, 11),
        ("50ALLIGATOR-5.75", 46, 7.5, 5.5)]),
    "F11": {
        "甲": ("hp max_flow_lpm", [
            ("80EUS-5.10L", 1, 560), ("80EUS-5.20", 2, 658),
            ("80EUS-5.20C", 2, 500), ("80EDW-5.20S/T", 2, 820),
            ("80EUB-M-5.20S", 2, 690), ("80STEEL-5.20", 2, 630),
            ("HIPPO-150 DN80", 1.5, 630), ("HIPPO-200 DN80", 2, 780)]),
        "乙": ("kw solids_mm max_flow_lpm", [
            ("100STEEL-5.50", 3.7, 45, 1000),
            ("100LEOPARD-5.30", 2.2, 56, 1400),
            ("100LEOPARD-5.50", 3.7, 80, 1900)])
    },
    "F12": ("kw rated_head_m rated_flow_lpm", [
        ("100DIVA-5.150", 11, 15, 2000), ("150DIVA-5.150", 11, 15, 2000),
        ("100DIVA PRO-5.150", 11, 15, 2000),
        ("150DIVA PRO-5.150", 11, 15, 2000),
        ("150EUB-M-5.100", 7.5, 15, 1550)]),
    "F13": ("rated_head_m rated_flow_lpm max_head_m max_flow_lpm", [
        ("100LEOPARD-5.50", 11, 800, 16, 1900),
        ("100LEOPARD-5.75", 13, 800, 18, 2300)]),
    "F14": ("current_1ph_a weight_1ph_kg solids_mm", [
        ("50EUB-5.05", 3, 11.3, 6), ("50EUB-5.10", 6, 13.7, 6),
        ("50EUBI-5.05", 3, 13.8, 6), ("50EUBS-5.05", 3, 14.1, 6),
        ("50EUS-5.05", 3, 11.3, 6), ("50EUS-5.10", 5.8, 13.9, 6),
        ("80EUS-5.10", 5.8, 13.9, 6), ("50EUBL-5.10", 5.8, 14, 38),
        ("50STEEL-5.05", 3.5, 13, 35), ("HIPPO-50", 4.2, 12.9, 50),
        ("HIPPO-50Q", 4.2, 14.3, 50), ("HIPPO-75", 5.5, 13.9, 50)]),
    "F15": ("hp max_head_m solids_mm", [
        ("100LEOPARD-5.75", 7.5, 18, 68), ("100LEOPARD-5.100", 10, 23, 68),
        ("HIPPO-550 DN80", 5.5, 18.5, 76),
        ("HIPPO-750 DN80", 7.5, 18, 76), ("HIPPO-750H DN80", 7.5, 21, 76)]),
    "F16": ("solids_mm max_head_m", [
        ("50EUSR-5.05", None, 14), ("32ALLIGATOR-5.15", None, 21),
        ("32ALLIGATOR-5.20", None, 28.5), ("32ALLIGATOR-5.30", None, 31),
        ("50ALLIGATOR-5.50", None, 37), ("50ALLIGATOR-5.75", None, 46)]),
    "F17": ("hp kw outlet_inch rated_head_m rated_flow_lpm max_head_m max_flow_lpm", [
        ("150DIVA PRO-5.200", 20, 15, 6, 15, 4000, 22, 6200),
        ("200DIVA PRO-5.200", 20, 15, 8, 15, 4000, 22, 6200)]),
    "F18": ("", []), "F19": ("", []),
    "F20": ("weight_3ph_kg", [("HIPPO-550 DN80", 51.9)])
}


TEXT = {
    "F01": ("跨系列完整AND清單", "我要接3吋管、用三相，馬力最多5HP，而且最大流量至少600 LPM。全型錄有哪些符合？請完整列出，每款的HP和最大流量也給我，不要只挑幾款。"),
    "F02": ("單相與合併列", "只有單相電，2吋出水口，最多2HP，最大流量要500 LPM以上。全部有哪些？把HP和最大流量寫上，表上單三相寫一起的款式也別漏掉。"),
    "F03": ("跨系列粒徑AND", "泥水裡會有65毫米的顆粒，先只比明列通過粒徑至少65毫米、馬力不超過7.5HP、最大流量至少1000 LPM的款式。全部列給我，三個數字都寫上。"),
    "F04": ("kW與HP對照邊界", "我說的是3.7kW，不是3.7HP。三相、4吋、功率剛好3.7kW，最大流量至少1000 LPM有哪些？每款寫kW、HP和最大流量，順便說這份表的3.7kW對應幾HP。"),
    "F05": ("每小時流量換算", "用三相、3吋管，功率最多5.5kW，最大流量至少每小時72立方米。這門檻是多少LPM？全部符合款幫我列功率，再把每款最大流量同時寫成LPM和每小時立方米。"),
    "F06": ("額定流量單位與完整清單", "只看EUS這個系列，額定流量至少每小時15立方米的全部有哪些？口徑不限，把每款額定流量同時寫LPM和每小時立方米，也告訴我門檻換成LPM是多少。"),
    "F07": ("同分重量次排序", "把HIPPO的2吋款都排給我，普通版和Q版分開算一款。先按最大流量由大到小，同流量再按單相重量由輕到重，每款的流量和單相重量都寫出來。"),
    "F08": ("多欄排序與前三名", "DIVA和DIVA PRO合在一起比最大流量，給我前三款。流量一樣先挑最大揚程較低，再挑口徑較小；還一樣就DIVA排在DIVA PRO前面。每款寫最大流量、最大揚程和吋數。"),
    "F09": ("跨系列並列冠軍", "都只看3HP，STEEL、HIPPO DN和LEOPARD這三系列各自通過粒徑最大的是誰？並列的都要列，附粒徑與最大流量，再說三系列誰的粒徑最大。"),
    "F10": ("全型錄最大揚程前三名", "口徑和相數先不限，全型錄最大揚程最高的前三款是哪些？由高到低排，寫最大揚程、HP和kW。"),
    "F11": ("兩現場獨立OR", "我有兩個現場，符合任何一邊都能考慮，但請分開列完整清單：甲要單相、3吋、最多2HP、最大流量至少500 LPM；乙要三相、4吋、功率最多3.7kW、明列通過粒徑至少40毫米、最大流量至少1000 LPM。甲每款寫HP和最大流量，乙寫kW、粒徑和最大流量。"),
    "F12": ("額定點與工況保證", "我想在15米揚程抽1600 LPM，表上有直接明列這一組額定點的嗎？先把功率最多11kW、同一額定點揚程至少15米且流量至少1500 LPM的候選全列出，附功率和額定點。這樣就能保證我的目標嗎？"),
    "F13": ("額定與獨立最大值", "100LEOPARD-5.50和100LEOPARD-5.75各自的額定揚程配流量是多少？也分別寫最大揚程與最大流量。能直接把每款這兩個最大值拼在一起，當成能同時做到的工作點嗎？"),
    "F14": ("單相電流重量與已知粒徑", "全型錄找單相滿載電流不超過6A、單相重量不超過15公斤，而且粒徑有明列並至少6毫米的款式。全部列給我，每款三個數字都要；沒寫粒徑的先不要當確認符合。"),
    "F15": ("三門檻含精確邊界", "三相泵裡，馬力最多10HP、最大揚程至少18米、明列通過粒徑至少68毫米的有哪些？全部列出HP、最大揚程和粒徑，剛好等於門檻也算。"),
    "F16": ("null未知不可確認否", "EUSR和ALLIGATOR有哪些款式沒寫通過粒徑？請逐款列，順便寫各自已知的最大揚程。沒寫就當0毫米嗎？如果我要至少10毫米，能直接判它們都不符合嗎？"),
    "F17": ("拆分口徑款不得混名", "DIVA PRO的20HP款，6吋和8吋出水口分別是哪個型號？功率、額定點、最大揚程和最大流量各是多少？換這兩個口徑，表上這幾個水力數字有差嗎？"),
    "F18": ("價格缺資料", "這117款裡哪款買起來最便宜？能照型錄把最便宜的前三款和售價排給我嗎？沒價格就說缺什麼，不要拿馬力或重量當價格。"),
    "F19": ("保固缺資料", "我想挑保固最長的，這117款哪幾款保固年數最高，保馬達還是也保軸封？型錄沒講就直接說，不要用品牌或系列來猜。"),
    "F20": ("已載選配但組合重量缺值", "HIPPO-550 DN80標的著脫座是什麼？泵本身三相淨重多少？把那個著脫座一起裝上，整套會有幾公斤？別直接拿泵的淨重當整套，沒資料就說還缺什麼。")
}


def digest_bytes(data):
    return hashlib.sha256(data).hexdigest()


def digest(path):
    return digest_bytes(path.read_bytes())


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def phases(row):
    phase = row["phase"]
    return phase if isinstance(phase, list) else [phase]


def known_ge(row, field, boundary):
    return row[field] is not None and row[field] >= boundary


def known_le(row, field, boundary):
    return row[field] is not None and row[field] <= boundary


def model_list(rows):
    return [r["model"] for r in rows]


def recompute(qid, rows):
    # Independent explicit Python operators; no filter/tool implementation.
    if qid == "F01":
        return model_list([r for r in rows if 3 in phases(r)
                           and r["outlet_inch"] == 3 and r["hp"] <= 5
                           and r["max_flow_lpm"] >= 600])
    if qid == "F02":
        return model_list([r for r in rows if 1 in phases(r)
                           and r["outlet_inch"] == 2 and r["hp"] <= 2
                           and r["max_flow_lpm"] >= 500])
    if qid == "F03":
        return model_list([r for r in rows if known_ge(r, "solids_mm", 65)
                           and r["hp"] <= 7.5 and r["max_flow_lpm"] >= 1000])
    if qid == "F04":
        return model_list([r for r in rows if 3 in phases(r)
                           and r["outlet_inch"] == 4 and r["kw"] == 3.7
                           and r["max_flow_lpm"] >= 1000])
    if qid == "F05":
        return model_list([r for r in rows if 3 in phases(r)
                           and r["outlet_inch"] == 3 and r["kw"] <= 5.5
                           and r["max_flow_lpm"] >= 72 * 1000 / 60])
    if qid == "F06":
        return model_list([r for r in rows if r["series"] == "EUS"
                           and r["rated_flow_lpm"] >= 15 * 1000 / 60])
    if qid == "F07":
        selected = [r for r in rows if r["series"] == "HIPPO"
                    and r["outlet_inch"] == 2]
        assert all(1 in phases(r) and r["weight_1ph_kg"] is not None
                   for r in selected)
        return model_list(sorted(selected, key=lambda r:
                                 (-r["max_flow_lpm"], r["weight_1ph_kg"])))
    if qid == "F08":
        selected = [r for r in rows if r["series"] in ("DIVA", "DIVA PRO")]
        return model_list(sorted(selected, key=lambda r: (
            -r["max_flow_lpm"], r["max_head_m"], r["outlet_inch"],
            0 if r["series"] == "DIVA" else 1))[:3])
    if qid == "F09":
        selected = []
        for series in ("STEEL", "HIPPO DN", "LEOPARD"):
            candidates = [r for r in rows if r["series"] == series and r["hp"] == 3]
            highest = max(r["solids_mm"] for r in candidates)
            selected.extend(r for r in candidates if r["solids_mm"] == highest)
        return model_list(selected)
    if qid == "F10":
        return model_list(sorted(rows, key=lambda r: -r["max_head_m"])[:3])
    if qid == "F11":
        return {
            "甲": model_list([r for r in rows if 1 in phases(r)
                              and r["outlet_inch"] == 3 and r["hp"] <= 2
                              and r["max_flow_lpm"] >= 500]),
            "乙": model_list([r for r in rows if 3 in phases(r)
                              and r["outlet_inch"] == 4 and r["kw"] <= 3.7
                              and known_ge(r, "solids_mm", 40)
                              and r["max_flow_lpm"] >= 1000])
        }
    if qid == "F12":
        assert not any(r["rated_head_m"] == 15 and r["rated_flow_lpm"] == 1600
                       for r in rows)
        return model_list([r for r in rows if r["kw"] <= 11
                           and r["rated_head_m"] >= 15
                           and r["rated_flow_lpm"] >= 1500])
    if qid == "F13":
        return model_list([r for r in rows if r["model"] in
                           ("100LEOPARD-5.50", "100LEOPARD-5.75")])
    if qid == "F14":
        return model_list([r for r in rows if 1 in phases(r)
                           and known_le(r, "current_1ph_a", 6)
                           and known_le(r, "weight_1ph_kg", 15)
                           and known_ge(r, "solids_mm", 6)])
    if qid == "F15":
        return model_list([r for r in rows if 3 in phases(r) and r["hp"] <= 10
                           and r["max_head_m"] >= 18
                           and known_ge(r, "solids_mm", 68)])
    if qid == "F16":
        return model_list([r for r in rows if r["series"] in ("EUSR", "ALLIGATOR")
                           and r["solids_mm"] is None])
    if qid == "F17":
        return model_list([r for r in rows if r["series"] == "DIVA PRO"
                           and r["hp"] == 20 and r["outlet_inch"] in (6, 8)])
    if qid in ("F18", "F19"):
        return []
    if qid == "F20":
        return model_list([r for r in rows if r["model"] == "HIPPO-550 DN80"])
    raise ValueError(qid)


def manual_models(value):
    if isinstance(value, dict):
        return {scenario: [r[0] for r in rows]
                for scenario, (_, rows) in value.items()}
    return [r[0] for r in value[1]]


def numeric_points(value):
    if isinstance(value, dict):
        return [f"{scenario}：{point}" for scenario, sub in value.items()
                for point in numeric_points(sub)]
    fields, rows = value
    points = []
    for row in rows:
        values = [f"{key}={value:g} {UNITS[key]}" if value is not None else
                  f"{key}=未提供／null" for key, value in zip(fields.split(), row[1:])]
        points.append(row[0] + "：" + "，".join(values))
    return points


def flatten_models(value):
    expected = manual_models(value)
    return sum(expected.values(), []) if isinstance(expected, dict) else expected


def compare_numeric(value, by_model):
    if isinstance(value, dict):
        for sub in value.values():
            compare_numeric(sub, by_model)
        return
    fields, rows = value
    for row in rows:
        assert [by_model[row[0]][key] for key in fields.split()] == list(row[1:]), row


def page_by_line(lines):
    pages, page = {}, None
    for index, line in enumerate(lines, 1):
        if match := re.match(r"## 第 (\d+) 頁", line):
            page = int(match[1])
        if line.startswith("## 附錄"):
            page = None
        pages[index] = page
    return pages


def citation(path, text, page, start, end):
    return {"path": path, "page": page, "line_start": start,
            "line_end": end, "quote": "\n".join(text.splitlines()[start - 1:end])}


def catalog_tables(source):
    lines = source.splitlines()
    pages = page_by_line(lines)
    blocks = []
    index = 0
    while index < len(lines):
        if lines[index].startswith("| 機型") or lines[index].startswith("| HIPPO-"):
            end = index
            while end + 1 < len(lines) and lines[end + 1].startswith("|"):
                end += 1
            if ("額定" in "\n".join(lines[index:end + 1])
                    or "HIPPO-" in lines[index]):
                blocks.append((pages[index + 1], index + 1, end + 1))
            index = end
        index += 1
    return blocks


def build_question(qid, by_model, texts, source, blocks):
    kind, prompt = TEXT[qid]
    manual = MANUAL[qid]
    models = manual_models(manual)
    flat = flatten_models(manual)
    required = numeric_points(manual)
    extra = []
    forbidden = ["錯納範圍外、未滿足明示條件的型號或給錯規格／單位"]
    if qid not in ("F07", "F08", "F10", "F18", "F19", "F20"):
        extra.append("應列型號完整，沒有錯納；模型別名需能無歧義對應原表列，口徑拆分款各自保留")
    if qid in ("F01", "F02", "F04", "F05", "F11", "F14", "F15"):
        extra.append("按已載phase與各相對應規格判斷，單／三相合併列可提供所問相數，不把它當未知或排除")
        forbidden.append("把單三相合併列排除該相數，或將未提供那一相數值當0／另一相值")
    if qid == "F04":
        extra.append("表列3.7 kW對應5 HP，是不同單位；不能把3.7 kW當3.7 HP")
        forbidden.append("以3.7 HP作門檻、排除表列5 HP／3.7 kW款")
    if qid == "F05":
        extra.append("72 m³/h ×1000÷60=1200 LPM；每款最大流量LPM乘0.06轉m³/h")
        extra += [f"{model}：最大流量{lpm} LPM={lpm * 0.06:g} m³/h"
                  for model, _, lpm in manual[1]]
        forbidden.append("換算門檻或每款流量錯誤，或把最大流量冒充額定流量")
    if qid == "F06":
        extra.append("15 m³/h=250 LPM；依額定流量而非最大流量比較，250 LPM邊界符合")
        extra += [f"{model}：額定流量{lpm} LPM={lpm * 0.06:g} m³/h"
                  for model, lpm in manual[1]]
    if qid in ("F07", "F08", "F10"):
        extra.append("完整指定順序：" + "、".join(models))
        forbidden.append("明確列出錯誤排序／錯誤前三名；只漏排序資訊可部分對")
    if qid == "F07":
        extra.append("普通版與Q版分開，各同最大流量均按已載單相重量由輕到重")
    if qid == "F08":
        extra.append("最大流量降冪、最大揚程升冪、口徑升冪、同值DIVA在DIVA PRO之前；只給指定前三款")
    if qid == "F09":
        extra.append("STEEL冠軍兩款45 mm、HIPPO DN冠軍HIPPO-300 DN80為76 mm、LEOPARD冠軍兩款56 mm；三系列最高為HIPPO DN的76 mm")
        forbidden.append("漏並列冠軍僅部分對，錯選較低粒徑為冠軍或錯比較則判錯")
    if qid == "F11":
        extra.append("甲8款、乙3款獨立給完整清單，符合任一情境可考慮，不壓成AND")
        forbidden.append("把兩現場合併為單一同時要滿足的AND，或混用甲乙相數及門檻")
    if qid == "F12":
        extra += ["117款沒有15 m @1600 LPM的明列額定點",
                  "五款只滿足同一額定點門檻，是待核對候選，不能直接保證目標；需性能曲線／工況確認"]
        forbidden += ["說候選已保證15 m @1600 LPM，或未知能力可確認不符合",
                      "用最大值代替額定值篩選，或把最大揚程與最大流量拼成同時點"]
    if qid == "F13":
        extra += ["每款額定揚程及額定流量是同一額定點",
                  "最大揚程及最大流量各自獨立，不是同一工作點，不能直接拼成同時達成的數字"]
        forbidden.append("將16 m／1900 LPM或18 m／2300 LPM說成該款可同時達成或額定點")
    if qid == "F14":
        extra.append("未載粒徑不列確認符合，也不能由null推成已確認不符合；6 A與6 mm精確邊界包括")
    if qid == "F15":
        extra.append("18 m、68 mm、10 HP等於門檻也符合")
    if qid == "F16":
        forbidden = ["將缺粒徑當0或其他數字", "說這六款已確認不符合至少10 mm，或由研磨／殘水用途推算粒徑"]
        extra += ["六款通過粒徑未提供／null，不等於0，也不能確認不符合≥10 mm",
                  "需要原廠通過粒徑／工況資料，不憑型號或用途補值"]
    if qid == "F17":
        extra.append("兩口徑各自型號；除6吋／8吋外，表列功率、額定點、最大揚程與最大流量相同；兩個最大值仍不可合工作點")
        forbidden.append("把6吋與8吋合成一個未分口徑的型號、猜口徑或推論水力數字有差")
    if qid == "F18":
        required = []
        extra = ["117款與型錄未提供售價，不能挑最低價款或排行前三售價",
                 "需各款同條件報價／售價；不能以馬力、重量或其他規格當價格"]
        forbidden = ["虛構價格、最低價型號或前三價格排序", "把沒有價格當0元，或以馬力／重量猜售價"]
    if qid == "F19":
        required = []
        extra = ["型錄未提供各款保固年數及涵蓋馬達／軸封的條款，不能選最長保固",
                 "需各型號保固年數與涵蓋範圍資料，不從品牌／系列猜"]
        forbidden = ["虛構保固年數、條款或最長保固型號", "把未載保固說成0年或沒有保固"]
    if qid == "F20":
        extra = ["HIPPO-550 DN80明列可搭QD-80著脫座",
                 "51.9 kg是泵三相淨重；型錄沒有QD-80座本身重量／整套重量，不能計算總重",
                 "需QD-80及隨附組件重量，不能把泵淨重直接當整套重"]
        forbidden = ["說沒有QD-80選配或推錯配座", "把51.9 kg說成泵加座總重",
                     "把座未載重量當0、虛構座重或整套重"]
    required += extra
    sources = []
    for model in dict.fromkeys(flat):
        path = next(path for path, data in texts.items()
                    if path.startswith("knowledge/products/")
                    and data.splitlines()[1] == "model: " + model)
        text = texts[path]
        end = next(index for index, line in enumerate(text.splitlines()[1:], 2)
                   if line == "---")
        sources.append(citation(path, text, by_model[model]["source"]["page"], 1, end))
    pages = {by_model[model]["source"]["page"] for model in flat}
    if qid in ("F18", "F19"):
        pages = {4, 9, 13, 16, 18, 19, 20}
    for page, start, end in blocks:
        if page in pages:
            sources.append(citation("knowledge/EVAK_CATALOG.md", source, page, start, end))
    if qid == "F20":
        footnote = next(index for index, line in enumerate(source.splitlines(), 1)
                        if "DN80 機型搭配 QD-80" in line)
        sources.append(citation("knowledge/EVAK_CATALOG.md", source, 17, footnote, footnote))
    answer = "；".join(numeric_points(manual) + extra)
    return {"id": qid, "kind": kind, "question": prompt,
            "expected_answer": answer, "required_points": required,
            "forbidden_claims": forbidden, "expected_models": models,
            "sources": sources}


def verify_snapshot():
    materialize(ROOT)
    snap = load(ROOT / "source_snapshot.json")
    assert set(snap["files"]) == set(snap["hashes"])
    for path, text in snap["files"].items():
        assert digest_bytes(text.encode()) == snap["hashes"][path], path
    assert snap["parity"]["resolved_metadata_equal"] is True
    texts, rows = snap["files"], []
    notes = list((ROOT / "notes").glob("*.md"))
    assert len(notes) == 117
    for path in sorted(notes):
        name = "knowledge/products/" + path.name
        assert path.read_text(encoding="utf-8") == texts[name], path
        fm = yaml.safe_load(texts[name].split("---", 2)[1])
        assert isinstance(fm, dict) and fm["source"]["path"] == "knowledge/EVAK_CATALOG.md"
        page = fm["source"]["page"]
        assert type(page) is int and 4 <= page <= 20
        assert re.search(rf"出處：第 {page} 頁", texts[name]), name
        rows.append(fm)
    assert len({r["model"] for r in rows}) == 117
    assert (ROOT / "catalog.yaml").read_text() == texts["knowledge/products/_catalog.yaml"]
    assert (ROOT / "source_catalog.md").read_text() == texts["knowledge/EVAK_CATALOG.md"]
    return snap, rows


def acceptance_rubric(old):
    rubric = dict(old)
    rubric["範圍與缺資料"] = (
        "只比較scope的117列；未知不可說成確認不符合。價格、保固問答不能自行補值。")
    rubric["OR與排序"] = (
        "多現場情境各自給完整集合，不能壓成AND；題目指定的多欄排序及同分次序為必要，"
        "其他集合題不要求型號出現順序。")
    rubric["等值與名稱"] = (
        "精確等值單位與同義敘述可接受；原表單三相合併列保留名稱，若答明同一列的單相或"
        "三相版本亦可接受，不要求把合併列拆成兩款。117列中的口徑、材質或Q版拆分款需"
        "各自完整；可用原圖合併名稱，但須明示本題對應的口徑、材質或Q版本，不能因此少算變體。")
    return rubric


def main():
    snapshot, rows = verify_snapshot()
    source = snapshot["files"]["knowledge/EVAK_CATALOG.md"]
    by_model = {r["model"]: r for r in rows}
    old = load(ROUND3 / "questions.json")
    catalog_pages = page_by_line(source.splitlines())
    blocks = catalog_tables(source)
    questions = [build_question(f"F{i:02}", by_model, snapshot["files"], source, blocks)
                 for i in range(1, 21)]
    data = {
        "scope": {"row_count": 117, "source_snapshot": "source_snapshot.json",
                  "catalog_path": "knowledge/products/_catalog.yaml",
                  "source_catalog_path": "knowledge/EVAK_CATALOG.md",
                  "series": sorted({r["series"] for r in rows}),
                  "models": sorted(by_model),
                  "model_rule": "按117篇實際模型列，口徑、Q版及材質拆分款各自一款；EDW S/T合併列仍保留，名稱及phase按已載值，不從型號猜。",
                  "comparison_rule": "額定揚程及流量同一點，兩個最大值獨立；缺值未知不可視0或確認否。"},
        "grading_rubric": acceptance_rubric(old["grading_rubric"]), "questions": questions
    }
    details, citations = [], 0
    for q in questions:
        qid = q["id"]
        manual = MANUAL[qid]
        compare_numeric(manual, by_model)
        actual = recompute(qid, rows)
        expected = q["expected_models"]
        ordered = qid in ("F07", "F08", "F10")
        if isinstance(expected, dict):
            assert set(expected) == set(actual)
            assert all(set(expected[key]) == set(actual[key]) for key in expected), qid
        else:
            assert expected == actual if ordered else set(expected) == set(actual), qid
        refs = []
        for ref in q["sources"]:
            text = snapshot["files"][ref["path"]]
            start, end = ref["line_start"], ref["line_end"]
            assert "\n".join(text.splitlines()[start - 1:end]) == ref["quote"]
            if ref["path"] == "knowledge/EVAK_CATALOG.md":
                assert all(catalog_pages[index] == ref["page"]
                           for index in range(start, end + 1)), (qid, ref)
            else:
                fm = yaml.safe_load(text.split("---", 2)[1])
                assert fm["source"]["page"] == ref["page"]
            refs.append({"path": ref["path"], "page": ref["page"],
                         "line_start": start, "line_end": end,
                         "exact_quote": True, "page_matches_source": True})
            citations += 1
        details.append({"id": qid, "manual_expected_models": expected,
                        "raw_frontmatter_recomputation": actual,
                        "manual_numeric_fields_and_rows": manual,
                        "manual_numeric_values_match": True, "complete_set_match": True,
                        "order_is_required": ordered, "sources": refs,
                        "numeric_evidence": [by_model[model] for model in
                                             dict.fromkeys(flatten_models(manual))]})
    absence_checks = {}
    for key, pattern in {
        "price": r"價格|售價|報價|定價|價錢|NT\$|USD|\bprice\b|pricing",
        "warranty": r"保固|保修|質保|warranty|guarantee"
    }.items():
        matches = [index for index, line in enumerate(source.splitlines(), 1)
                   if re.search(pattern, line, re.I)]
        assert not matches, (key, matches)
        absence_checks[key] = {"pattern": pattern, "catalog_line_range": [1, len(source.splitlines())],
                               "matching_lines": matches,
                               "all_117_raw_frontmatters_lack_field": all(
                                   key not in row for row in rows)}
    assert source.count("QD-80") > 0
    assert by_model["HIPPO-550 DN80"]["weight_3ph_kg"] == 51.9
    qd_lines = [{"line": index, "quote": line}
                for index, line in enumerate(source.splitlines(), 1) if "QD-80" in line]
    assert not any(re.search(r"QD-80.*(?:\d+(?:\.\d+)?\s*kg|公斤|重量\s*[:：=])", r["quote"])
                   for r in qd_lines)
    path, validation_path = ROOT / "questions.json", ROOT / "question_validation.json"
    if path.exists():
        assert load(path) == data, "既有標準不同，不可重寫"
    else:
        assert not validation_path.exists(), "有凍結記錄而無題目，不可重建"
        artifacts = [p.name for p in ROOT.iterdir()
                     if p.name.startswith(("answers", "results", "grading", "evaluation_checkpoint"))]
        assert not artifacts, f"回答已開始，不得補凍結: {artifacts}"
        write(path, data)
    expected_hashes = {
        "source_snapshot_sha256": digest(ROOT / "source_snapshot.json"),
        "questions_sha256": digest(path), "source_catalog_sha256": digest(ROOT / "source_catalog.md"),
        "catalog_sha256": digest(ROOT / "catalog.yaml")}
    if validation_path.exists():
        frozen = load(validation_path)
        assert all(frozen[key] == value for key, value in expected_hashes.items())
        print(json.dumps({"status": "verified_frozen", "questions": 20,
                          "source_notes": 117, "exact_citations": citations,
                          "questions_sha256": expected_hashes["questions_sha256"]}, ensure_ascii=False))
        return
    validation = {
        "status": "frozen_before_answer_generation",
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(), **expected_hashes,
        "summary": {"question_count": 20, "raw_note_count": 117,
                    "series_count": len(data["scope"]["series"]),
                    "all_snapshot_files_hashes_match": True,
                    "all_local_exports_match_snapshot": True,
                    "all_manual_numeric_values_match": True,
                    "all_manual_model_sets_match": True,
                    "exact_citations": citations, "all_pages_match_source": True,
                    "has_17_match_complete_list": True,
                    "has_12_match_complete_list": True,
                    "has_multi_scenario_or": True,
                    "has_multicolumn_sort_with_tie": True,
                    "has_m3h_lpm_both_directions": True,
                    "has_kw_hp_catalog_unit_mapping": True,
                    "has_rated_point_vs_target_and_independent_maxima": True,
                    "has_null_not_zero_or_confirmed_false": True,
                    "price_warranty_option_missing_questions": 3,
                    "grading_rules_equivalent_to_round3": True,
                    "grading_scope_adapted_to_117_and_question_numbers_generalized": True,
                    "production_filter_or_tool_used_as_oracle": False,
                    "answer_model_called": False},
        "arithmetic": {"F05_threshold": "72×1000÷60=1200 LPM",
                       "F05_LPM_to_m3h": {r[0]: r[2] * 0.06 for r in MANUAL["F05"][1]},
                       "F06_threshold": "15×1000÷60=250 LPM",
                       "F06_LPM_to_m3h": {r[0]: r[1] * 0.06 for r in MANUAL["F06"][1]},
                       "F04_unit_mapping": "原表5 HP／3.7 kW，兩單位分欄；不假設所有額定值為無誤差通用換算",
                       "F12_exact_15m_1600LPM": [],
                       "F16_unknown_solids_count": 6,
                       "F20_pump_kg": 51.9,
                       "F20_QD80_catalog_mentions": qd_lines,
                       "F20_QD80_weight": None,
                       "F20_assembled_weight": None},
        "full_catalog_absence_checks": absence_checks,
        "source_file_count": len(snapshot["files"]),
        "questions": details
    }
    write(validation_path, validation)
    print(json.dumps({"status": validation["status"], "questions": 20,
                      "source_notes": 117, "exact_citations": citations,
                      "questions_sha256": expected_hashes["questions_sha256"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
