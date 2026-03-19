# TASK-25: Tool Schema Registry and Execution Bridge

> Issue: #34 — Tool schema registry and execution bridge
> Epic: #9
> Branch: `feature/brain`
> Status: **Draft**

---

## 開發需求

強化既有的 tool registry 與 execution bridge，讓 tool 呼叫更安全、可觀測、可擴充。

| 需求 | 說明 |
|------|------|
| Schema 驗證 | tool handler 執行前，依宣告的 JSON Schema 驗證參數，缺必填欄位或型別錯誤時回傳結構化錯誤 |
| 執行安全 | handler 異常不會炸掉 agent loop，一律包裝成 ToolResult 回傳 |
| Result contract | 統一 `ToolResult` 型別，包含 status + data/error + tool metadata |
| 可觀測性 | tool 執行加入 metrics（計次、延遲）和 structured log |
| 測試覆蓋 | registry / executor / 驗證 / error 路徑皆有單元測試 |

---

## 現況分析

### 已完成

| 元件 | 狀態 |
|------|------|
| `Tool` frozen dataclass | name + description + parameters (JSON Schema) + handler |
| `ToolRegistry` | register / get / list_tools / build_openai_tools |
| `execute_tool_call()` | 解析 JSON arguments → 呼叫 handler → format_tool_result |
| 3 個內建 tool | get_document, search_knowledge, search_memory |
| `bind_tool_persona()` | context manager 設定 active persona |
| agent_loop 整合 | `_run_tool_phase` + `_append_tool_turns` + `_execute_tool_call` |

### 缺口

| 缺口 | 說明 |
|------|------|
| 無 schema 驗證 | handler 拿到的 dict 沒有驗證 required / type，壞參數可能引發不可預期的錯誤 |
| handler 例外無防護 | `tool.handler(arguments)` 如果 raise，整個 agent loop 就爆了 |
| result 無統一型別 | handler 可以回傳 dict 或 str，沒有 status/error 結構 |
| 無 metrics | tool 執行沒有計時、計次、成功/失敗率 |
| 無單元測試 | tool_registry 和 tool_executor 完全沒有直接測試 |

---

## 開發方法

### 架構

```
LLM tool_call
    │
    ▼
execute_tool_call(name, raw_arguments)
    ├─ registry.get(name)                    ← 未知 tool → ToolResult(error)
    ├─ _parse_arguments(raw_arguments)       ← 非法 JSON → ToolResult(error)
    ├─ validate_tool_arguments(schema, args) ← schema 不符 → ToolResult(error)  [新增]
    ├─ tool.handler(validated_args)           ← 包在 try/except [強化]
    │      └─ 成功 → ToolResult(ok, data)
    │      └─ 例外 → ToolResult(error, message)
    ├─ metrics.increment(tool_calls_total)   [新增]
    └─ return result.serialize()
```

### 設計決策

1. **用 `jsonschema` 做 schema 驗證** — 參數 schema 已經是 JSON Schema 格式，直接用 `jsonschema.validate()` 做驗證最自然，不需要轉 Pydantic/Zod
2. **`ToolResult` frozen dataclass** — 統一 ok/error 兩種結果，序列化時一律帶 `status` + `tool_name` 欄位
3. **handler 例外包在 executor 層** — handler 不需要自己 try/except，executor 統一攔截並轉成 ToolResult(error)
4. **不改 Tool dataclass** — 現有的 `Tool(name, description, parameters, handler)` 不變，保持向後相容
5. **不改 agent_loop 呼叫方式** — `execute_tool_call` 的回傳值仍然是 str，只是內容現在有統一的 JSON 結構

### 實作步驟

| 步驟 | 內容 | 產出檔案 |
|------|------|---------|
| 1. 寫失敗測試 | registry lookup / argument parsing / schema validation / handler error / result format | `brain/api/tests/test_tools.py` |
| 2. ToolResult 型別 | frozen dataclass with ok/error factory methods + serialize | `brain/api/tools/tool_executor.py` |
| 3. Schema 驗證 | `validate_tool_arguments()` 用 jsonschema 驗證參數 | `brain/api/tools/tool_executor.py` |
| 4. 安全執行 | handler 包 try/except，例外轉 ToolResult(error) | `brain/api/tools/tool_executor.py` |
| 5. Metrics | tool 執行加入計次和延遲 metrics | `brain/api/tools/tool_executor.py` |
| 6. 驗證 | 全部測試通過 | `pytest -v` |

### ToolResult 設計

```python
@dataclass(frozen=True, slots=True)
class ToolResult:
    status: str           # "ok" | "error"
    tool_name: str
    data: dict[str, Any]  # handler 回傳的結果（ok 時）或空 dict（error 時）
    error: str            # 錯誤訊息（error 時）或空字串（ok 時）

    @staticmethod
    def ok(tool_name: str, data: dict[str, Any]) -> ToolResult: ...

    @staticmethod
    def fail(tool_name: str, error: str) -> ToolResult: ...

    def serialize(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)
```

### Schema 驗證

```python
def validate_tool_arguments(
    schema: dict[str, Any],
    arguments: dict[str, Any],
) -> list[str]:
    """Validate arguments against JSON Schema, return list of error messages."""
    errors = []
    # check required fields
    for field in schema.get("required", []):
        if field not in arguments:
            errors.append(f"缺少必填參數：{field}")
    # check property types
    properties = schema.get("properties", {})
    for key, value in arguments.items():
        if key in properties:
            expected_type = properties[key].get("type")
            if expected_type and not _type_matches(value, expected_type):
                errors.append(f"參數 {key} 型別錯誤：預期 {expected_type}")
    return errors
```

用輕量自寫驗證而非完整 jsonschema 套件，因為 tool schema 結構簡單（flat object, 基本型別），不需要 $ref / anyOf / allOf 等進階功能。如果未來 schema 變複雜再引入 jsonschema。

### execute_tool_call 改動

```python
def execute_tool_call(tool_name: str, raw_arguments: str | dict[str, Any]) -> str:
    """Execute a registered tool with validation and error resilience."""
    # 1. lookup
    try:
        tool = get_tool_registry().get(tool_name)
    except ValueError:
        return ToolResult.fail(tool_name, f"未知工具：{tool_name}").serialize()

    # 2. parse arguments
    try:
        arguments = _parse_arguments(raw_arguments)
    except ValueError as exc:
        return ToolResult.fail(tool_name, str(exc)).serialize()

    # 3. validate against schema
    validation_errors = validate_tool_arguments(tool.parameters, arguments)
    if validation_errors:
        return ToolResult.fail(tool_name, "; ".join(validation_errors)).serialize()

    # 4. execute with error resilience
    try:
        result = tool.handler(arguments)
        data = result if isinstance(result, dict) else {"text": str(result)}
        return ToolResult.ok(tool_name, data).serialize()
    except Exception as exc:
        return ToolResult.fail(tool_name, f"工具執行失敗：{exc}").serialize()
```

關鍵改動：
- 所有錯誤路徑都回傳 `ToolResult`，不 raise — agent loop 不會因為 tool 失敗而中斷
- LLM 看到 `status: "error"` 可以決定重試或換方法

---

## 驗收方法

### 自動驗收

| 檢查項目 | 指令 | 驗證內容 |
|---------|------|---------|
| Tool 測試 | `python3 -m pytest brain/api/tests/test_tools.py -v` | registry + executor + validation |
| 既有測試不壞 | `python3 -m pytest brain/api/tests/ -v` | 全部 pass |

### 測試案例規劃

| 測試 | 驗證內容 |
|------|---------|
| `test_registry_register_and_get` | 註冊後可依名稱取回 |
| `test_registry_get_unknown_tool` | 未知 tool name raise ValueError |
| `test_registry_list_tools_sorted` | list_tools 按名稱排序 |
| `test_registry_build_openai_tools_format` | 產出符合 OpenAI function calling 格式 |
| `test_execute_tool_call_returns_ok_result` | 正常執行回傳 status=ok + data |
| `test_execute_tool_call_unknown_tool_returns_error` | 未知 tool 回傳 status=error，不 raise |
| `test_execute_tool_call_invalid_json_returns_error` | 壞 JSON 回傳 error，不 raise |
| `test_execute_tool_call_missing_required_param_returns_error` | 缺必填參數回傳 error |
| `test_execute_tool_call_wrong_type_param_returns_error` | 型別錯誤回傳 error |
| `test_execute_tool_call_handler_exception_returns_error` | handler raise 時回傳 error，不炸 agent loop |
| `test_validate_tool_arguments_accepts_valid_args` | 合法參數回傳空 error list |
| `test_validate_tool_arguments_reports_missing_required` | 缺必填欄位回傳錯誤訊息 |
| `test_validate_tool_arguments_reports_wrong_type` | 型別不符回傳錯誤訊息 |
| `test_tool_result_ok_serialize` | ToolResult.ok 序列化有 status + tool_name + data |
| `test_tool_result_fail_serialize` | ToolResult.fail 序列化有 status + tool_name + error |

### 手動驗收

| 驗收標準 | 如何確認 |
|---------|---------|
| tool 可被註冊與依名稱執行 | test_registry_register_and_get + test_execute_tool_call_returns_ok_result |
| 壞參數不會炸掉整個流程 | test_execute_tool_call_handler_exception_returns_error — 回傳 ToolResult(error) |
| executor result 格式一致 | 所有路徑都回傳 ToolResult JSON，含 status + tool_name |

### 驗證指令

```bash
# 1. Tool 測試
python3 -m pytest brain/api/tests/test_tools.py -v

# 2. 全部測試
python3 -m pytest brain/api/tests/ -v
```

---

## 檔案清單

| 檔案 | 動作 | 用途 |
|------|------|------|
| `brain/api/tools/tool_executor.py` | 修改 | 新增 ToolResult + validate_tool_arguments + 安全執行 |
| `brain/api/tools/tool_registry.py` | 微調 | 移除 format_tool_result（改用 ToolResult.serialize） |
| `brain/api/tests/test_tools.py` | 新增 | registry + executor + validation 測試 |
| `docs/plans/TASK-25-tool-schema-registry.md` | 新增 | 計畫書 |
