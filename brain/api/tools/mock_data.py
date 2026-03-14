"""Mock business data for FAQ and order tools.

This module contains hardcoded data constants only.
Replace with real API calls when integrating with external services.
"""

from __future__ import annotations

from typing import Any

FAQ_ENTRIES: tuple[dict[str, str], ...] = (
    {
        "id": "faq-001",
        "question": "如何退貨？",
        "answer": "請於收到商品後 7 天內至「我的訂單」頁面申請退貨，我們會在 3 個工作天內處理退款。",
        "keywords": "退貨,退款,退換貨",
    },
    {
        "id": "faq-002",
        "question": "運費怎麼算？",
        "answer": "單筆訂單滿 $999 免運費，未達免運門檻酌收 $60 運費。離島地區另計。",
        "keywords": "運費,免運,宅配",
    },
    {
        "id": "faq-003",
        "question": "可以更改訂單嗎？",
        "answer": "訂單成立後 30 分鐘內可於「我的訂單」頁面修改數量或取消，出貨後則無法更改。",
        "keywords": "修改訂單,更改,取消",
    },
    {
        "id": "faq-004",
        "question": "付款方式有哪些？",
        "answer": "支援信用卡（VISA/MasterCard/JCB）、ATM 轉帳、超商代碼繳費三種方式。",
        "keywords": "付款,信用卡,轉帳",
    },
    {
        "id": "faq-005",
        "question": "訂單多久會出貨？",
        "answer": "工作日下午 2 點前完成付款，當日出貨；之後的訂單隔日出貨。預計 1-3 個工作天送達。",
        "keywords": "出貨,配送,到貨時間",
    },
    {
        "id": "faq-006",
        "question": "如何查詢訂單狀態？",
        "answer": "登入後至「我的訂單」頁面即可查看訂單狀態與物流追蹤編號。",
        "keywords": "查詢訂單,訂單狀態,物流",
    },
)

ORDER_RECORDS: dict[str, dict[str, Any]] = {
    "ORD-20260301-001": {
        "order_id": "ORD-20260301-001",
        "customer_name": "王小明",
        "status": "已出貨",
        "items": [
            {"name": "無線藍牙耳機", "qty": 1, "price": 1280},
        ],
        "total": 1280,
        "created_at": "2026-03-01T10:30:00+08:00",
    },
    "ORD-20260301-002": {
        "order_id": "ORD-20260301-002",
        "customer_name": "李小華",
        "status": "處理中",
        "items": [
            {"name": "手機保護殼", "qty": 2, "price": 280},
        ],
        "total": 560,
        "created_at": "2026-03-01T14:15:00+08:00",
    },
    "ORD-20260228-003": {
        "order_id": "ORD-20260228-003",
        "customer_name": "張大偉",
        "status": "已完成",
        "items": [
            {"name": "機械鍵盤", "qty": 1, "price": 2800},
            {"name": "滑鼠墊", "qty": 1, "price": 400},
        ],
        "total": 3200,
        "created_at": "2026-02-28T09:00:00+08:00",
    },
}
