# Community 27

Nodes: 31

## Members
- **importance.py** (`brain/api/memory/importance.py`)
- **ImportanceResult** (`brain/api/memory/importance.py`)
- **score_importance()** (`brain/api/memory/importance.py`)
- **_match_patterns()** (`brain/api/memory/importance.py`)
- **Heuristic importance scoring for memory records.** (`brain/api/memory/importance.py`)
- **Immutable result of importance scoring.** (`brain/api/memory/importance.py`)
- **Score the importance of a piece of text using regex heuristics.      Returns an** (`brain/api/memory/importance.py`)
- **Return signal labels for all patterns that match *text*.** (`brain/api/memory/importance.py`)
- **test_importance.py** (`brain/api/tests/memory/test_importance.py`)
- **TestScoreImportance** (`brain/api/tests/memory/test_importance.py`)
- **.test_empty_text_returns_low()** (`brain/api/tests/memory/test_importance.py`)
- **.test_preference_signal_is_high()** (`brain/api/tests/memory/test_importance.py`)
- **.test_instruction_signal_is_high()** (`brain/api/tests/memory/test_importance.py`)
- **.test_date_signal_is_medium()** (`brain/api/tests/memory/test_importance.py`)
- **.test_contact_info_is_medium()** (`brain/api/tests/memory/test_importance.py`)
- **.test_plain_text_is_low()** (`brain/api/tests/memory/test_importance.py`)
- **.test_result_is_frozen()** (`brain/api/tests/memory/test_importance.py`)
- **.test_multiple_high_signals_increase_score()** (`brain/api/tests/memory/test_importance.py`)
- **.test_high_takes_priority_over_medium()** (`brain/api/tests/memory/test_importance.py`)
- **.test_english_preference_signal()** (`brain/api/tests/memory/test_importance.py`)
- **Tests for memory importance scoring heuristics.** (`brain/api/tests/memory/test_importance.py`)
- **Empty or whitespace-only text should score low.** (`brain/api/tests/memory/test_importance.py`)
- **Text containing preference keywords should score high.** (`brain/api/tests/memory/test_importance.py`)
- **Text containing instruction/correction keywords should score high.** (`brain/api/tests/memory/test_importance.py`)
- **Text containing dates should score medium.** (`brain/api/tests/memory/test_importance.py`)
- **Text containing contact-related keywords should score medium.** (`brain/api/tests/memory/test_importance.py`)
- **Text with no special signals should score low.** (`brain/api/tests/memory/test_importance.py`)
- **ImportanceResult should be immutable.** (`brain/api/tests/memory/test_importance.py`)
- **Multiple high signals should yield a higher score within the high range.** (`brain/api/tests/memory/test_importance.py`)
- **When both high and medium signals are present, high wins.** (`brain/api/tests/memory/test_importance.py`)
- **English preference keywords should also score high.** (`brain/api/tests/memory/test_importance.py`)

## Connections to other communities
