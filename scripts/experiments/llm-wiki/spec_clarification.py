"""Experimental clarification before retrieval/model execution; no service patch.

Identity recognition uses catalog keys and user turns only. An explicit ranking
metric can search the whole catalog, so missing a model alone is not sufficient
to block a well-defined selection request.
"""

import re

from spec_product_route import normalize_model, route_spec_question


_METRICS = {
    "head": r"揚程|水頭|\bhead\b",
    "flow": r"流量|\bflow\b",
    "power": r"馬力|功率|\b(?:hp|power|kw)\b",
    "weight": r"重量|多重|\bweight\b",
    "current": r"電流|\bcurrent\b",
    "outlet": r"口徑|\boutlet\b",
    "solids": r"粒徑|\bsolids\b",
}
_RANK = re.compile(r"最大|最小|最高|最低|最好|最強|最輕|最重|\b(?:largest|smallest|best|maximum|minimum)\b")
_SELECTION = re.compile(r"哪[款些台幾]|選型|有哪些|推薦|挑選|\b(?:which|select|recommend)\b")


def clarification_plan(question, previous="", *, catalog=None):
    """Return a fixed clarification, or allow the ordinary answering callback.

    Testable conditions, in priority order: unknown/incomplete identity;
    multiple antecedents without an explicit current comparison; unspecified
    ranking metric; missing model for a point lookup. No numeric fact is emitted.
    """
    route = route_spec_question(question, previous, catalog=catalog)
    result = {"action": "answer", "reason": None, "reply": None, "route": route}
    if not route["required"]:
        return result
    text = normalize_model(question)
    metrics = {key for key, pattern in _METRICS.items() if re.search(pattern, text)}
    reason = None
    if route["unknown_model_tokens"]:
        reason = "incomplete_model"
    elif any("多個" in issue for issue in route["unresolved"]):
        reason = "ambiguous_model"
    elif _RANK.search(text) and len(metrics) != 1:
        reason = "missing_metric"
    elif not route["matched_models"] and not _SELECTION.search(text) and not _RANK.search(text):
        reason = "missing_model"
    replies = {
        "incomplete_model": "請提供完整系列與型號，不能用部分型號代選；查電流時也請提供相數。",
        "ambiguous_model": "前文有多個型號候選，請指定這次要問的完整型號，或明確說要比較哪些型號。",
        "missing_metric": "請先指定比較指標：最大揚程、流量、馬力或其他指標；目前無法選出唯一型號。",
        "missing_model": "請提供完整系列與型號；若要查電流，也請指定單相或三相。",
    }
    if reason:
        result.update(action="clarify", reason=reason, reply=replies[reason])
    return result


def dispatch(question, previous="", *, catalog=None, answer):
    """The clarification branch returns before any model/tool callback is invoked."""
    plan = clarification_plan(question, previous, catalog=catalog)
    if plan["action"] == "clarify":
        return {"answer": plan["reply"], "clarification": plan, "model_calls": 0}
    return answer(question, previous, plan)
