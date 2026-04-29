import os
import json
from datetime import datetime

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")


def _ensure_dir():
    os.makedirs(RESULTS_DIR, exist_ok=True)


def save_result(phone: str, filename: str, analysis: dict, was_truncated: bool):
    _ensure_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_phone = phone.replace("+", "").replace(" ", "")
    out_path = os.path.join(RESULTS_DIR, f"{safe_phone}_{timestamp}.json")
    payload = {
        "phone": phone,
        "filename": filename,
        "analyzed_at": datetime.now().isoformat(),
        "was_truncated": was_truncated,
        "analysis": analysis,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return out_path


def already_processed(phone: str) -> bool:
    """Возвращает True если звонок с таким номером уже есть в результатах."""
    _ensure_dir()
    safe_phone = phone.replace("+", "").replace(" ", "")
    for fname in os.listdir(RESULTS_DIR):
        if fname.startswith(safe_phone) and fname.endswith(".json"):
            return True
    return False


def load_all_results() -> list[dict]:
    _ensure_dir()
    results = []
    for fname in sorted(os.listdir(RESULTS_DIR), reverse=True):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(RESULTS_DIR, fname)
        try:
            with open(path, encoding="utf-8") as f:
                results.append(json.load(f))
        except Exception:
            continue
    return results
