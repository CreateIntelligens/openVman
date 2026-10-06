"""Freeze manual question keys before answers; verify from raw cells only."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent
ROUND2 = ROOT.parent / "round2"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_hash(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def source(lines, start, end, page):
    return {"path": "knowledge/EVAK_CATALOG.md", "page": page,
            "line_start": start, "line_end": end,
            "quote": "\n".join(lines[start - 1:end])}


def new_questions(lines):
    # These keys were calculated by hand from the catalogue, before answers.
    # The independent operators below must agree, never supply these keys.
    both = [source(lines, 199, 208, 9), source(lines, 231, 242, 11)]
    return [
        {
            "id": "Q13", "kind": "多條件篩選",
            "question": "我要三相電的泵，滿載電流最多5.5A，而且三相款重量不能超過30公斤，口徑不限。這批EDW和EUB-M有哪些符合？每款的三相電流和重量都列給我。",
            "expected_answer": "四款符合：50EUB-M-5.20T（3.5 A、26.4 kg）、80EUB-M-5.20T（3.5 A、25.9 kg）、50EUB-M-5.30T（5.2 A、29.8 kg）、80EUB-M-5.30T（5.2 A、30.0 kg）。EDW沒有同時符合兩個門檻的款式。",
            "required_points": [
                "完整列出50EUB-M-5.20T、80EUB-M-5.20T、50EUB-M-5.30T、80EUB-M-5.30T",
                "四款三相滿載電流／三相重量依序3.5 A／26.4 kg、3.5 A／25.9 kg、5.2 A／29.8 kg、5.2 A／30.0 kg",
                "沒有EDW同時符合三相電流≤5.5 A與三相重量≤30 kg"
            ],
            "forbidden_claims": [
                "納入三相電流大於5.5 A、三相重量大於30 kg或未列三相資料的款式",
                "把單相電流或單相重量代入三相門檻，或把未知三相值當0"
            ],
            "expected_models": ["50EUB-M-5.20T", "80EUB-M-5.20T",
                                "50EUB-M-5.30T", "80EUB-M-5.30T"],
            "sources": both
        },
        {
            "id": "Q14", "kind": "數值篩選與單位",
            "question": "先看通過粒徑至少10毫米、功率不超過3.7kW的款式，相數和口徑都不限。EDW和EUB-M符合的全部有哪些？幫我把kW、HP和粒徑一起寫出來。",
            "expected_answer": "七款：80EDW-5.20S/T（1.5 kW、2 HP、10 mm）、80EDW-5.30S/T（2.2 kW、3 HP、10 mm）、100EDW-5.30S/T（2.2 kW、3 HP、10 mm）、80EDW-5.50T（3.7 kW、5 HP、10 mm）、100EDW-5.50T（3.7 kW、5 HP、10 mm）、80EUB-M-5.50T（3.7 kW、5 HP、10 mm）、100EUB-M-5.50T（3.7 kW、5 HP、10 mm）。3.7 kW不是3.7 HP，表中5 HP／3.7 kW的款式符合。",
            "required_points": [
                "完整列出五款EDW與80EUB-M-5.50T、100EUB-M-5.50T，共七款",
                "80EDW-5.20S/T為1.5 kW／2 HP；80EDW-5.30S/T與100EDW-5.30S/T為2.2 kW／3 HP；其餘四款為3.7 kW／5 HP，七款通過粒徑皆10 mm",
                "以3.7 kW作門檻，5 HP／3.7 kW仍符合"
            ],
            "forbidden_claims": [
                "把3.7 kW門檻當作3.7 HP而排除5 HP／3.7 kW款式",
                "納入通過粒徑9 mm或功率5.5 kW款式"
            ],
            "expected_models": ["80EDW-5.20S/T", "80EDW-5.30S/T",
                                "100EDW-5.30S/T", "80EDW-5.50T",
                                "100EDW-5.50T", "80EUB-M-5.50T",
                                "100EUB-M-5.50T"],
            "sources": both
        },
        {
            "id": "Q15", "kind": "排序與同分次排序",
            "question": "這批泵裡三相、功率不超過2.2kW的全部排給我：先按三相滿載電流由小到大，電流相同就按三相重量由輕到重。每款的kW、電流和重量都寫上。",
            "expected_answer": "依序為80EUB-M-5.20T（1.5 kW、3.5 A、25.9 kg）、50EUB-M-5.20T（1.5 kW、3.5 A、26.4 kg）、80EDW-5.20S/T（1.5 kW、3.8 A、46 kg）、50EUB-M-5.30T（2.2 kW、5.2 A、29.8 kg）、80EUB-M-5.30T（2.2 kW、5.2 A、30.0 kg）、80EDW-5.30S/T（2.2 kW、5.7 A、45 kg）、100EDW-5.30S/T（2.2 kW、5.7 A、46 kg）。三組同電流以三相重量升冪決定先後。",
            "required_points": [
                "完整且依序列出80EUB-M-5.20T、50EUB-M-5.20T、80EDW-5.20S/T、50EUB-M-5.30T、80EUB-M-5.30T、80EDW-5.30S/T、100EDW-5.30S/T",
                "七款kW／三相電流A／三相重量kg依序1.5／3.5／25.9、1.5／3.5／26.4、1.5／3.8／46、2.2／5.2／29.8、2.2／5.2／30.0、2.2／5.7／45、2.2／5.7／46",
                "同電流3.5、5.2、5.7 A三組都按三相重量由輕到重"
            ],
            "forbidden_claims": [
                "納入功率超過2.2 kW或沒有已列三相電流的款式",
                "以單相電流／重量排序，或把未知值當0參與排序"
            ],
            "expected_models": ["80EUB-M-5.20T", "50EUB-M-5.20T",
                                "80EDW-5.20S/T", "50EUB-M-5.30T",
                                "80EUB-M-5.30T", "80EDW-5.30S/T",
                                "100EDW-5.30S/T"],
            "sources": both
        },
        {
            "id": "Q16", "kind": "多情境OR篩選",
            "question": "我有兩個現場，符合其中一邊就能考慮，但清單請分開列：甲用三相，滿載電流不超過8A、重量不超過50公斤、通過粒徑至少10毫米；乙用單相，重量不超過28公斤、通過粒徑至少9毫米。口徑不限，兩邊每款的相應電流、重量和粒徑也給我。",
            "expected_answer": "甲四款：80EDW-5.20S/T（3.8 A、46 kg、10 mm）、80EDW-5.30S/T（5.7 A、45 kg、10 mm）、100EDW-5.30S/T（5.7 A、46 kg、10 mm）、80EDW-5.50T（7.9 A、49.5 kg、10 mm）。乙兩款：50EUB-M-5.20S與80EUB-M-5.20S，皆單相12.5 A、27.5 kg、9 mm。兩現場獨立篩選，不要求一款同時滿足甲乙。",
            "required_points": [
                "甲完整列出80EDW-5.20S/T、80EDW-5.30S/T、100EDW-5.30S/T、80EDW-5.50T",
                "甲四款三相電流／重量／粒徑依序3.8 A／46 kg／10 mm、5.7 A／45 kg／10 mm、5.7 A／46 kg／10 mm、7.9 A／49.5 kg／10 mm",
                "乙完整列出50EUB-M-5.20S與80EUB-M-5.20S，皆單相12.5 A／27.5 kg／9 mm",
                "甲乙分開給清單，按各自相數使用對應電流及重量"
            ],
            "forbidden_claims": [
                "把甲乙兩情境壓成同時必須滿足的AND條件",
                "甲納入100EDW-5.50T（50.5 kg）、粒徑9 mm或三相電流超過8 A款式",
                "乙納入單相重量超過28 kg或沒有已列單相數值的款式"
            ],
            "expected_models": {
                "甲": ["80EDW-5.20S/T", "80EDW-5.30S/T",
                       "100EDW-5.30S/T", "80EDW-5.50T"],
                "乙": ["50EUB-M-5.20S", "80EUB-M-5.20S"]
            },
            "sources": both
        },
        {
            "id": "Q17", "kind": "跨系列極值比較",
            "question": "都選三相、4吋出水口，EDW和EUB-M各找重量最輕的一款，分別是誰、幾公斤？兩邊差多少公斤？",
            "expected_answer": "EDW為100EDW-5.30S/T的三相版本，46 kg；EUB-M為100EUB-M-5.50T，34.9 kg。EUB-M這款輕11.1 kg。",
            "required_points": [
                "EDW三相4吋最輕款為100EDW-5.30S/T，三相重量46 kg",
                "EUB-M三相4吋最輕款為100EUB-M-5.50T，三相重量34.9 kg",
                "EUB-M所選款比EDW所選款輕11.1 kg"
            ],
            "forbidden_claims": [
                "選非4吋、未列三相版本或錯誤系列最輕款",
                "把EDW單相47 kg當三相重量，或以最大流量選冠軍"
            ],
            "expected_models": ["100EDW-5.30S/T", "100EUB-M-5.50T"],
            "sources": both
        },
        {
            "id": "Q18", "kind": "額定點與最大值區分",
            "question": "我要12.5米揚程、1000 LPM，這批泵哪款明列這一組額定點？再把同一額定點揚程至少12米、流量至少750 LPM的候選全部列出並附額定點。其他候選能直接保證符合我的目標嗎？最大揚程和最大流量能拼成同時達到的數字嗎？",
            "expected_answer": "100EDW-5.50T明列12.5 m @1000 LPM。額定揚程≥12 m且額定流量≥750 LPM的完整候選為100EDW-5.50T（12.5 m @1000 LPM）、100EUB-M-5.50T（12.5 m @800 LPM）、100EUB-M-5.75T（16 m @1060 LPM）。另外兩款沒有明列12.5 m @1000 LPM，不能只憑額定候選門檻保證目標，需性能曲線／工況確認。最大揚程與最大流量是各自的極限值，不是同一個工作點，不能拼成同時達成的點。",
            "required_points": [
                "100EDW-5.50T明列12.5 m @1000 LPM這一組額定點",
                "完整候選三款100EDW-5.50T、100EUB-M-5.50T、100EUB-M-5.75T，額定點依序12.5 m @1000 LPM、12.5 m @800 LPM、16 m @1060 LPM",
                "其他兩款未明列目標點，門檻候選不能直接當目標保證，需性能曲線／工況確認",
                "最大揚程與最大流量是獨立極限，不能視為同時達成的工作點"
            ],
            "forbidden_claims": [
                "把100EUB-M-5.50T或100EUB-M-5.75T說成明列或已保證12.5 m @1000 LPM",
                "將最大揚程與最大流量合併成可同時達成的工作點",
                "使用最大值篩選額定候選或納入不符合任一額定門檻款式"
            ],
            "expected_models": ["100EDW-5.50T", "100EUB-M-5.50T",
                                "100EUB-M-5.75T"],
            "sources": both
        },
        {
            "id": "Q19", "kind": "選配數值缺資料",
            "question": "我看到EDW有CH選配。如果換成CH，最大揚程、最大流量和重量會比標準款增加多少？這份型錄能幫我挑出最輕的CH款嗎？沒有數字就直接說缺什麼，別用標準款硬算。",
            "expected_answer": "型錄有CH選配，209–213行說明高鉻閉式葉輪、熱處理球狀石墨鑄鐵吸水盤、AISI 410熱處理硬化軸心，但15列規格表未提供CH版最大揚程、最大流量、重量，也沒有標準款與CH款的數值差額。不能算出增加多少、不能挑出最輕CH款，需各CH版規格／性能與重量資料；不能將標準款數值移植為CH版數值。",
            "required_points": [
                "CH選配確有記載，但選配後最大揚程、最大流量、重量與相對標準款差額未提供",
                "不能計算三項增加多少，也不能判定哪款CH最輕",
                "需要CH版的性能與重量數據，不能把標準規格當CH規格"
            ],
            "forbidden_claims": [
                "說型錄沒有CH選配或虛構CH數值、增幅、最輕型號",
                "因未提供差額就斷言增加0或完全不變",
                "將標準款表格數值冒充CH版性能或重量"
            ],
            "expected_models": [],
            "sources": [source(lines, 199, 205, 9),
                        source(lines, 209, 213, 9)]
        },
        {
            "id": "Q20", "kind": "缺值與相數辨識",
            "question": "50EUB-M-5.20S和80EUB-M-5.20S的三相欄都是橫線，能當作三相0A、0公斤來挑最省電最輕的嗎？表上實際寫的是哪個相數、多少滿載電流和重量？沒寫的三相數字能光靠型號補出來嗎？",
            "expected_answer": "不能把橫線當三相0 A、0 kg，也不能據此挑三相最省電或最輕。兩款表上都只列單相滿載電流12.5 A、單相重量27.5 kg；三相電流與重量未提供，應保留未知／null，不能由型號補出數值，也不能由缺值保證有可用三相版本。滿載電流值本身也不能直接當能耗效率證明。",
            "required_points": [
                "50EUB-M-5.20S與80EUB-M-5.20S皆明列單相滿載電流12.5 A、單相重量27.5 kg",
                "兩款三相電流、三相重量皆未列，橫線代表無已載數值／未知，不能當0 A、0 kg",
                "不能靠型號補三相數值或據此保證三相可用，不能排三相最省電／最輕"
            ],
            "forbidden_claims": [
                "把三相空白欄當0 A、0 kg或其他推估數值",
                "把單相12.5 A、27.5 kg直接搬到三相欄",
                "只憑型號或橫線就宣稱三相版可用，或認定為三相最省電／最輕"
            ],
            "expected_models": ["50EUB-M-5.20S", "80EUB-M-5.20S"],
            "sources": [source(lines, 231, 234, 11)]
        }
    ]


def number(cell):
    match = re.search(r"\d+(?:\.\d+)?", cell)
    if match is None:
        raise ValueError(f"沒有數字: {cell!r}")
    return float(match[0])


def optional_number(cell):
    return None if cell.strip() == "-" else number(cell)


def parse_raw_rows(rows, lines, pages):
    records = []
    for row in rows:
        line = row["line"]
        assert lines[line - 1] == row["row"]
        cells = [cell.strip() for cell in lines[line - 1].strip("|").split("|")]
        assert cells == row["cells"]
        assert cells[0] == row["model"]
        assert pages[line] == row["page"]
        hp, kw = map(number, cells[1].split("/"))
        rh, rf = map(number, cells[3].split("@"))
        mh, mf = map(number, cells[4].split("@"))
        if row["series"] == "EDW":
            currents = list(map(optional_number, cells[6].split("/")))
            weights = list(map(optional_number, cells[7].split("/")))
        else:
            currents = [optional_number(cells[6]), optional_number(cells[7])]
            weights = list(map(optional_number, cells[8].split("/")))
        records.append({
            "model": cells[0], "series": row["series"],
            "page": row["page"], "line": line,
            "hp": hp, "kw": kw, "outlet_inch": number(cells[2]),
            "rated_head_m": rh, "rated_flow_lpm": rf,
            "max_head_m": mh, "max_flow_lpm": mf,
            "solids_mm": number(cells[5]),
            "available_phases": [phase for phase, current in
                                 zip((1, 3), currents) if current is not None],
            "current_1ph_a": currents[0], "current_3ph_a": currents[1],
            "weight_1ph_kg": weights[0], "weight_3ph_kg": weights[1]
        })
    assert len(records) == 15
    return records


def page_by_line(lines):
    pages = {}
    page = None
    for line, text in enumerate(lines, 1):
        match = re.match(r"## 第 (\d+) 頁", text)
        if match:
            page = int(match[1])
        pages[line] = page
    return pages


def models(rows):
    return [row["model"] for row in rows]


def recompute(question_id, rows):
    # Keep the operators explicit: no production filter engine as an oracle.
    if question_id == "Q01":
        return models([r for r in rows if r["outlet_inch"] == 3
                       and r["max_head_m"] >= 20])
    if question_id == "Q02":
        return models([r for r in rows if 3 in r["available_phases"]
                       and r["hp"] <= 3 and r["max_flow_lpm"] >= 500])
    if question_id == "Q03":
        return models([max(rows, key=lambda r: r["max_flow_lpm"])])
    if question_id == "Q04":
        return models([r for r in rows if r["hp"] == 3])
    if question_id in ("Q05", "Q10", "Q17"):
        outlet = 3 if question_id == "Q05" else 4
        field = {"Q05": "max_head_m", "Q10": "max_flow_lpm",
                 "Q17": "weight_3ph_kg"}[question_id]
        selector = min if question_id == "Q17" else max
        selected = []
        for series in ("EDW", "EUB-M"):
            candidates = [r for r in rows if r["series"] == series
                          and r["outlet_inch"] == outlet]
            if question_id == "Q17":
                candidates = [r for r in candidates
                              if 3 in r["available_phases"]
                              and r[field] is not None]
            selected.append(selector(candidates, key=lambda r: r[field]))
        return models(selected)
    if question_id == "Q06":
        return {
            "甲": models([r for r in rows if 1 in r["available_phases"]
                         and r["hp"] == 2 and r["outlet_inch"] == 3
                         and r["max_flow_lpm"] >= 650]),
            "乙": models([r for r in rows if 3 in r["available_phases"]
                         and r["hp"] == 3 and r["max_head_m"] >= 23])
        }
    if question_id == "Q07":
        selected = [r for r in rows if r["series"] == "EUB-M"
                    and 3 in r["available_phases"] and r["max_head_m"] >= 20]
        return models(sorted(selected, key=lambda r:
                             (-r["max_head_m"], -r["max_flow_lpm"])))
    if question_id == "Q08":
        return models([r for r in rows if 1 in r["available_phases"]
                       and r["hp"] == 2 and r["max_flow_lpm"] >= 30 * 1000 / 60])
    if question_id in ("Q09", "Q18"):
        head, flow = (15, 400) if question_id == "Q09" else (12, 750)
        return models([r for r in rows if r["rated_head_m"] >= head
                       and r["rated_flow_lpm"] >= flow])
    if question_id in ("Q11", "Q12", "Q19"):
        return []
    if question_id == "Q13":
        return models([r for r in rows if 3 in r["available_phases"]
                       and r["current_3ph_a"] is not None
                       and r["weight_3ph_kg"] is not None
                       and r["current_3ph_a"] <= 5.5
                       and r["weight_3ph_kg"] <= 30])
    if question_id == "Q14":
        return models([r for r in rows if r["solids_mm"] >= 10
                       and r["kw"] <= 3.7])
    if question_id == "Q15":
        selected = [r for r in rows if 3 in r["available_phases"]
                    and r["kw"] <= 2.2 and r["current_3ph_a"] is not None
                    and r["weight_3ph_kg"] is not None]
        return models(sorted(selected, key=lambda r:
                             (r["current_3ph_a"], r["weight_3ph_kg"])))
    if question_id == "Q16":
        return {
            "甲": models([r for r in rows if 3 in r["available_phases"]
                         and r["current_3ph_a"] is not None
                         and r["weight_3ph_kg"] is not None
                         and r["current_3ph_a"] <= 8
                         and r["weight_3ph_kg"] <= 50
                         and r["solids_mm"] >= 10]),
            "乙": models([r for r in rows if 1 in r["available_phases"]
                         and r["weight_1ph_kg"] is not None
                         and r["weight_1ph_kg"] <= 28 and r["solids_mm"] >= 9])
        }
    if question_id == "Q20":
        selected = [r for r in rows if r["model"] in
                    {"50EUB-M-5.20S", "80EUB-M-5.20S"}]
        assert all(r["available_phases"] == [1]
                   and r["current_3ph_a"] is None
                   and r["weight_3ph_kg"] is None for r in selected)
        return models(selected)
    raise ValueError(question_id)


MANUAL_NEW_NUMBERS = {
    "80EDW-5.20S/T": [1.5, 2, 10, 3.8, 46],
    "80EDW-5.30S/T": [2.2, 3, 10, 5.7, 45],
    "100EDW-5.30S/T": [2.2, 3, 10, 5.7, 46],
    "80EDW-5.50T": [3.7, 5, 10, 7.9, 49.5],
    "100EDW-5.50T": [3.7, 5, 10, 7.9, 50.5],
    "50EUB-M-5.20T": [1.5, 2, 9, 3.5, 26.4],
    "80EUB-M-5.20T": [1.5, 2, 9, 3.5, 25.9],
    "50EUB-M-5.30T": [2.2, 3, 9, 5.2, 29.8],
    "80EUB-M-5.30T": [2.2, 3, 9, 5.2, 30.0],
    "80EUB-M-5.50T": [3.7, 5, 10, 9.5, 35.6],
    "100EUB-M-5.50T": [3.7, 5, 10, 9.5, 34.9],
    "80EUB-M-5.75T": [5.5, 7.5, 10, 12.5, 51.6],
    "100EUB-M-5.75T": [5.5, 7.5, 10, 12.5, 51.4]
}


def matches(expected, actual, ordered=False):
    if isinstance(expected, dict):
        return set(expected) == set(actual) and all(
            matches(expected[k], actual[k]) for k in expected)
    return expected == actual if ordered else set(expected) == set(actual)


def main():
    source_path = ROOT / "source_catalog.md"
    rows_path = ROOT / "table_rows.json"
    assert sha256(source_path) == sha256(ROUND2 / "source_catalog.md"), (
        "來源快照與第二輪不同，停止凍結")
    assert sha256(rows_path) == sha256(ROUND2 / "table_rows.json")
    old = load(ROUND2 / "questions.json")
    old_validation = load(ROUND2 / "question_validation.json")
    lines = source_path.read_text(encoding="utf-8").splitlines()
    pages = page_by_line(lines)
    rows = parse_raw_rows(load(rows_path), lines, pages)
    by_model = {r["model"]: r for r in rows}
    questions = {**old, "scope": {**old["scope"],
                 "catalog_local_snapshot": str(source_path.relative_to(
                     ROOT.parents[3]))},
                 "questions": old["questions"] + new_questions(lines)}
    assert len(questions["questions"]) == 20
    assert questions["questions"][:12] == old["questions"]
    assert questions["grading_rubric"] == old["grading_rubric"]
    numeric_keys = ("kw", "hp", "solids_mm", "current_3ph_a",
                    "weight_3ph_kg")
    for model, manual_values in MANUAL_NEW_NUMBERS.items():
        assert [by_model[model][k] for k in numeric_keys] == manual_values
    manual_rated = {
        "100EDW-5.50T": [12.5, 1000],
        "100EUB-M-5.50T": [12.5, 800],
        "100EUB-M-5.75T": [16, 1060]
    }
    for model, pair in manual_rated.items():
        assert [by_model[model][k] for k in
                ("rated_head_m", "rated_flow_lpm")] == pair
    assert round(by_model["100EDW-5.30S/T"]["weight_3ph_kg"] -
                 by_model["100EUB-M-5.50T"]["weight_3ph_kg"], 1) == 11.1
    exact_point = models([r for r in rows if r["rated_head_m"] == 12.5
                          and r["rated_flow_lpm"] == 1000])
    assert exact_point == ["100EDW-5.50T"]
    for model in ("50EUB-M-5.20S", "80EUB-M-5.20S"):
        row = by_model[model]
        assert [row[k] for k in ("current_1ph_a", "weight_1ph_kg",
                                 "current_3ph_a", "weight_3ph_kg")] == (
            [12.5, 27.5, None, None])
    details = []
    conditions = {
        "Q13": "phase含3 AND current_3ph_a≤5.5 AND weight_3ph_kg≤30；null不能通過",
        "Q14": "solids_mm≥10 AND kw≤3.7，kW與HP分欄",
        "Q15": "phase含3 AND kw≤2.2；current_3ph_a升冪，再weight_3ph_kg升冪",
        "Q16": "甲：phase含3 AND current_3ph_a≤8 AND weight_3ph_kg≤50 AND solids_mm≥10；乙：phase含1 AND weight_1ph_kg≤28 AND solids_mm≥9；兩集合獨立",
        "Q17": "各series中phase含3 AND outlet_inch=4，分別weight_3ph_kg最小",
        "Q18": "rated_head_m≥12 AND rated_flow_lpm≥750；另查12.5m@1000LPM精確額定點",
        "Q19": "CH選配有記載，但CH性能與重量未形成規格列，無法計算差額或最輕款",
        "Q20": "指定兩S列：phase由電流欄確認為[1]，三相電流與重量null不能當0"
    }
    citation_count = 0
    for question in questions["questions"]:
        qid = question["id"]
        actual = recompute(qid, rows)
        ordered = qid in ("Q07", "Q15")
        assert matches(question["expected_models"], actual, ordered), qid
        citations = []
        for citation in question["sources"]:
            start, end = citation["line_start"], citation["line_end"]
            assert "\n".join(lines[start - 1:end]) == citation["quote"]
            assert all(pages[n] == citation["page"]
                       for n in range(start, end + 1)), (qid, citation)
            citations.append({"page": citation["page"],
                              "line_start": start, "line_end": end,
                              "match": True, "page_matches_lines": True})
            citation_count += 1
        flat_models = sum(actual.values(), []) if isinstance(actual, dict) else actual
        if flat_models:
            for model in flat_models:
                row = by_model[model]
                assert any(c["line_start"] <= row["line"] <= c["line_end"]
                           for c in question["sources"]), (qid, model)
        details.append({
            "id": qid,
            "manual_condition": conditions.get(qid, next(
                d["manual_condition"] for d in old_validation["questions"]
                if d["id"] == qid) if qid <= "Q12" else ""),
            "manual_expected_models": question["expected_models"],
            "recomputed_from_raw_rows": actual, "complete_set_match": True,
            "citation_matches": citations,
            "numeric_evidence": [by_model[model] for model in
                                 dict.fromkeys(flat_models)],
            "order_is_required": ordered
        })
    source_text = "\n".join(lines)
    for absent in ("price", "warranty"):
        pattern = old_validation["full_catalog_absence_checks"][absent]["pattern"]
        assert not re.search(pattern, source_text, re.IGNORECASE)
    ch_rows = [r for r in rows if "CH" in r["model"]]
    assert not ch_rows and "(CH)" in lines[209]
    ch_numeric_lines = [
        {"line": n, "text": line} for n, line in enumerate(lines, 1)
        if re.search(r"\bCH\b|\(CH\)", line)
    ]
    path = ROOT / "questions.json"
    validation_path = ROOT / "question_validation.json"
    if path.exists():
        assert load(path) == questions, "題目已存在且不同，不可重寫"
    else:
        assert not validation_path.exists(), "凍結記錄已存在，不可重建題目"
        answer_artifacts = [p.name for p in ROOT.glob("*.json")
                            if p.name.startswith(("results", "evaluation", "grading"))]
        assert not answer_artifacts, f"回答產物已出現，拒絕補凍結: {answer_artifacts}"
        write(path, questions)
    if validation_path.exists():
        frozen = load(validation_path)
        assert frozen["questions_sha256"] == sha256(path)
        assert frozen["source_sha256"] == sha256(source_path)
        assert frozen["table_rows_sha256"] == sha256(rows_path)
        assert frozen["old_questions_canonical_sha256"] == canonical_hash(
            old["questions"])
        print(json.dumps({"status": "verified_frozen", "question_count": 20,
                          "questions_sha256": sha256(path)}, ensure_ascii=False))
        return
    assert not list(ROOT.glob("results*.json")), "不得在回答產生後建立凍結記錄"
    validation = {
        "status": "frozen_before_answer_generation",
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_sha256": sha256(source_path), "table_rows_sha256": sha256(rows_path),
        "questions_sha256": sha256(path),
        "round2_questions_file_sha256": sha256(ROUND2 / "questions.json"),
        "old_questions_canonical_sha256": canonical_hash(old["questions"]),
        "round3_first12_canonical_sha256": canonical_hash(questions["questions"][:12]),
        "grading_rubric_canonical_sha256": canonical_hash(old["grading_rubric"]),
        "summary": {
            "question_count": 20, "old_question_count": 12, "new_question_count": 8,
            "source_row_count": 15, "table_rows_match_original": True,
            "old_question_objects_identical": True, "grading_rubric_identical": True,
            "all_citations_match": True, "all_citation_pages_match_lines": True,
            "exact_citation_count": citation_count,
            "all_manual_sets_match_recomputation": True,
            "manual_numeric_values_match_raw_cells": True,
            "production_filter_engine_used_as_oracle": False,
            "new_has_multi_scenario_or": True,
            "new_has_multicolumn_sort_with_tie": True,
            "new_sort_secondary_differs_from_Q07": True,
            "new_has_kw_vs_hp_check": True,
            "new_has_rated_vs_max_point_check": True,
            "new_unanswerable_option_and_null_questions": 2
        },
        "old_validation_summary_unchanged": old_validation["summary"],
        "full_catalog_absence_checks": old_validation["full_catalog_absence_checks"],
        "manual_arithmetic": {
            **old_validation["manual_arithmetic"],
            "Q14_units": "表列5 HP／3.7 kW，不把3.7 kW當3.7 HP；直接核對kW欄，不採近似換算",
            "Q15_tie_breaks": "3.5 A：25.9<26.4 kg；5.2 A：29.8<30.0 kg；5.7 A：45<46 kg",
            "Q17_difference": "46−34.9=11.1 kg；兩系列各自三相4吋最小值",
            "Q18_exact_rated_point": exact_point,
            "Q18_manual_rated_pairs": manual_rated,
            "Q19_CH_numeric_rows": ch_rows,
            "Q19_all_CH_mentions": ch_numeric_lines,
            "Q20_null_semantics": "兩指定列單相12.5 A／27.5 kg；三相current=null／weight=null；未知不等於0，資料不保證三相版"
        },
        "manual_new_numeric_keys": list(numeric_keys),
        "manual_new_numbers": MANUAL_NEW_NUMBERS,
        "phase_checks": old_validation["phase_checks"],
        "questions": details
    }
    write(validation_path, validation)
    print(json.dumps({"status": validation["status"],
                      "question_count": 20, "questions_sha256": sha256(path),
                      "old_questions_identical": True,
                      "citations": citation_count}, ensure_ascii=False))


if __name__ == "__main__":
    main()
