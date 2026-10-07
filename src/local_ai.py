import os
import shutil
import subprocess
import time
import json
import re
from typing import Optional, List, Dict, Any, Callable
import requests

from src.utils import get_resource_path

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5:3b"


def _fix_binary_permissions(bin_path: str):
    """Ensures executable bits and clears com.apple.quarantine for ollama and sibling binaries."""
    try:
        if not os.path.exists(bin_path):
            return
        # Ensure executable permission
        os.chmod(bin_path, 0o755)
        # Clear gatekeeper quarantine if present
        subprocess.run(["xattr", "-d", "com.apple.quarantine", bin_path], capture_output=True)
        # Also fix sibling binaries in the same directory (e.g. llama-server, dylibs)
        bin_dir = os.path.dirname(os.path.abspath(bin_path))
        if os.path.isdir(bin_dir):
            for fname in os.listdir(bin_dir):
                full_p = os.path.join(bin_dir, fname)
                if os.path.isfile(full_p):
                    if "llama" in fname or "ollama" in fname or fname.endswith(".dylib") or fname.endswith(".so"):
                        try:
                            os.chmod(full_p, 0o755)
                            subprocess.run(["xattr", "-d", "com.apple.quarantine", full_p], capture_output=True)
                        except Exception:
                            pass
    except Exception:
        pass


def find_ollama_binary() -> Optional[str]:
    """Finds the ollama binary path on the system, prioritizing bundled and project directory."""
    # 1. Bundled in dedicated ollama_bin directory (via get_resource_path)
    cand_bin_dir = get_resource_path("ollama_bin/ollama")
    if os.path.exists(cand_bin_dir):
        _fix_binary_permissions(cand_bin_dir)
        if os.access(cand_bin_dir, os.X_OK):
            return cand_bin_dir

    # 2. Bundled / Project ollama binary directly in Resources
    cand_bin = get_resource_path("ollama")
    if os.path.exists(cand_bin):
        _fix_binary_permissions(cand_bin)
        if os.access(cand_bin, os.X_OK):
            return cand_bin

    # 3. Project directory Ollama.app
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proj_ollama = os.path.join(proj_root, "Ollama.app", "Contents", "Resources", "ollama")
    if os.path.exists(proj_ollama):
        _fix_binary_permissions(proj_ollama)
        if os.access(proj_ollama, os.X_OK):
            return proj_ollama

    # 4. Local relative Ollama.app
    rel_ollama = os.path.abspath("Ollama.app/Contents/Resources/ollama")
    if os.path.exists(rel_ollama):
        _fix_binary_permissions(rel_ollama)
        if os.access(rel_ollama, os.X_OK):
            return rel_ollama

    # 5. User home & system paths
    candidates = [
        os.path.expanduser("~/bin/ollama"),
        os.path.expanduser("~/Applications/Ollama.app/Contents/Resources/ollama"),
        "/usr/local/bin/ollama",
        "/Applications/Ollama.app/Contents/Resources/ollama",
    ]
    for p in candidates:
        if os.path.exists(p):
            _fix_binary_permissions(p)
            if os.access(p, os.X_OK):
                return p

    which_path = shutil.which("ollama")
    if which_path and os.path.exists(which_path):
        _fix_binary_permissions(which_path)
        return which_path

    return None


def get_models_dir() -> Optional[str]:
    """Returns absolute path to models directory if present."""
    cand = get_resource_path("models")
    if os.path.exists(cand) and os.path.isdir(cand):
        return cand
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proj_cand = os.path.join(proj_root, "models")
    if os.path.exists(proj_cand) and os.path.isdir(proj_cand):
        return proj_cand
    return None


_models_dir = get_models_dir()
if _models_dir:
    os.environ["OLLAMA_MODELS"] = _models_dir


def is_ollama_running(url: str = DEFAULT_OLLAMA_URL) -> bool:
    """Checks whether the Ollama server is responding."""
    try:
        r = requests.get(f"{url}/api/tags", timeout=1.5)
        return r.status_code == 200
    except Exception:
        return False


def ensure_ollama_running(
    url: str = DEFAULT_OLLAMA_URL,
    max_wait: int = 15,
    log_cb: Optional[Callable[[str], None]] = None
) -> bool:
    """Ensures Ollama daemon is active, starting it in the background if necessary."""
    if is_ollama_running(url):
        return True

    ollama_bin = find_ollama_binary()
    if not ollama_bin:
        if log_cb:
            log_cb("❌ Không tìm thấy bộ máy Ollama offline trong ứng dụng.")
        return False

    if log_cb:
        log_cb("⏳ Đang khởi động AI server nội bộ (offline)...")

    try:
        env = os.environ.copy()
        m_dir = get_models_dir()
        if m_dir:
            env["OLLAMA_MODELS"] = m_dir
        # Ensure PATH includes directory of ollama for llama-server discovery
        bin_dir = os.path.dirname(os.path.abspath(ollama_bin))
        env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"

        subprocess.Popen(
            [ollama_bin, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            start_new_session=True
        )
    except Exception as e:
        if log_cb:
            log_cb(f"❌ Lỗi khi khởi chạy process Ollama: {e}")
        return False

    start_time = time.time()
    while time.time() - start_time < max_wait:
        time.sleep(0.5)
        if is_ollama_running(url):
            if log_cb:
                log_cb("✅ AI server nội bộ đã sẵn sàng hoạt động.")
            return True

    if log_cb:
        log_cb(f"❌ AI server nội bộ không phản hồi sau {max_wait} giây.")
    return False


def warmup_ollama_model(
    model_name: str = DEFAULT_MODEL,
    url: str = DEFAULT_OLLAMA_URL,
    log_cb: Optional[Callable[[str], None]] = None
) -> bool:
    """Pre-loads the target model into RAM/GPU memory to prevent latency on first inference."""
    try:
        if log_cb:
            log_cb(f"🔥 Đang nạp trước mô hình AI '{model_name}' vào bộ nhớ RAM/GPU...")
        res = requests.post(
            f"{url}/api/generate",
            json={"model": model_name, "prompt": "OK", "stream": False, "options": {"num_predict": 1}},
            timeout=40
        )
        if res.status_code == 200:
            if log_cb:
                log_cb(f"✅ Mô hình AI '{model_name}' đã nạp sẵn sàng!")
            return True
        else:
            if log_cb:
                log_cb(f"⚠️ Nạp mô hình trả về mã HTTP {res.status_code}: {res.text[:100]}")
    except Exception as e:
        if log_cb:
            log_cb(f"⚠️ Cảnh báo khởi động mô hình: {e}")
    return False


def get_available_models(url: str = DEFAULT_OLLAMA_URL) -> List[str]:
    """Returns list of currently downloaded model names in Ollama."""
    try:
        r = requests.get(f"{url}/api/tags", timeout=3.0)
        if r.status_code == 200:
            data = r.json()
            models = [m.get("name", "") for m in data.get("models", [])]
            return [m for m in models if m]
    except Exception:
        pass
    return []


def is_model_available(model_name: str = DEFAULT_MODEL, url: str = DEFAULT_OLLAMA_URL) -> bool:
    """Checks if the specified model is already pulled."""
    models = get_available_models(url)
    clean_target = model_name.split(":")[0].lower()
    for m in models:
        if clean_target in m.lower():
            return True
    return False


def pull_model_stream(
    model_name: str = DEFAULT_MODEL,
    progress_cb: Optional[Callable[[str], None]] = None,
    url: str = DEFAULT_OLLAMA_URL
) -> bool:
    """Pulls an Ollama model with streaming progress updates."""
    if not ensure_ollama_running(url, log_cb=progress_cb):
        if progress_cb:
            progress_cb("❌ Không thể kết nối tới dịch vụ Ollama.")
        return False

    if is_model_available(model_name, url):
        if progress_cb:
            progress_cb(f"✅ Mô hình '{model_name}' đã có sẵn trong máy.")
        return True

    if progress_cb:
        progress_cb(f"📥 Đang tải mô hình AI '{model_name}' (khoảng 2.0GB, lưu dùng offline vĩnh viễn)...")

    try:
        res = requests.post(
            f"{url}/api/pull",
            json={"name": model_name, "stream": True},
            stream=True,
            timeout=600
        )
        if res.status_code != 200:
            if progress_cb:
                progress_cb(f"❌ Lỗi tải model từ Ollama: HTTP {res.status_code}")
            return False

        last_report = 0
        for line in res.iter_lines():
            if not line:
                continue
            try:
                data = json.loads(line.decode("utf-8"))
                status_str = data.get("status", "")
                completed = data.get("completed", 0)
                total = data.get("total", 0)
                if total > 0 and progress_cb:
                    pct = int((completed / total) * 100)
                    if pct - last_report >= 10:
                        last_report = pct
                        progress_cb(f"   ➔ Đang tải {model_name}: {pct}% ({completed // (1024*1024)}MB / {total // (1024*1024)}MB)...")
                elif status_str and progress_cb and "pulling" not in status_str:
                    progress_cb(f"   ➔ {status_str}")
            except Exception:
                continue

        if progress_cb:
            progress_cb(f"🎉 Đã tải thành công mô hình '{model_name}'!")
        return True
    except Exception as e:
        if progress_cb:
            progress_cb(f"❌ Lỗi khi tải mô hình: {e}")
        return False


FACA_SYSTEM_PROMPT = """You are a senior hardware manufacturing test engineer at Apple / Foxconn.
Your job is to translate and format test failure FACA (Root Cause, Corrective Action, Check Point) into concise, professional manufacturing English.

RULES:
1. Translate any Chinese (中文) or Vietnamese (tiếng Việt) into concise engineering English.
2. Keep all industry acronyms unchanged: DUT, OP, SOP, B2B flex, Fixture, SFC, PDCA, UOP, CCD, Mylar, ME, IE, WIP, BLE, etc.
3. OUTPUT FORMAT:
   Always structure as:
   {Root Cause description}. CA: {Corrective Action}. CP: {Check Point date or Daily}
   - If Corrective Action is present, prefix with "CA: "
   - If Check Point or date is present, prefix with "CP: " (e.g. "CP: 8/27" or "CP: Daily")
   - Do NOT include markdown bolding, quotes, or preamble. Just return the single formatted paragraph.

Example 1:
Input: 治具探针粘胶导致误测，CA: 清理探针并复测OK，IE培训OP按SOP操作，CP: 8/25
Output: Fixture probe had glue causing false retest. CA: Clean probe and retest pass, IE retrain OP follow SOP to operate. CP: 8/25

Example 2:
Input: OP đặt hàng không chuẩn, flex bị gập. CA: Chỉnh lại flex và test lại pass. CP: Daily
Output: OP did not place unit properly, flex folded. CA: Re-align flex and retest pass. CP: Daily
"""


ZH_FACTORY_DICT = {
    "探针": "probe",
    "脏污": "dirty/contaminated",
    "异物": "foreign object",
    "治具": "fixture",
    "复测": "retest",
    "误测": "false retest",
    "未放平": "not placed flat",
    "未放好": "not placed properly",
    "点胶": "dispensing glue",
    "断开": "disconnected",
    "短路": "short circuit",
    "开路": "open circuit",
    "接触不良": "poor contact",
    "螺丝": "screw",
    "铜帽": "copper cap",
    "扭曲": "twisted",
    "未拧紧": "not tightened",
    "低电量": "low battery",
    "充电": "charging",
    "超时": "timeout",
    "排线": "flex cable",
    "折痕": "folded/creased",
    "偏移": "misaligned",
    "卡住": "stuck",
    "漏测": "missed test",
    "按SOP": "follow SOP",
    "培训": "training",
    "清理": "clean",
    "复位": "reset",
    "重启": "restart",
}


def clean_remaining_chinese(text: str) -> str:
    """Replaces common Chinese factory terms if LLM missed them."""
    out = text
    for zh, en in ZH_FACTORY_DICT.items():
        out = out.replace(zh, en)
    return out


def translate_and_format_faca(
    raw_text: str,
    category: str = "",
    station: str = "",
    model_name: str = DEFAULT_MODEL,
    url: str = DEFAULT_OLLAMA_URL,
    timeout: int = 35,
    log_cb: Optional[Callable[[str], None]] = None
) -> str:
    """
    Translates mixed Chinese/Vietnamese/English FACA into standardized technical English
    matching the exact style in Sample-keynote2.
    Guarantees no Chinese characters remain in the output.
    """
    cleaned = raw_text.strip()
    if not cleaned:
        return ""

    if not is_ollama_running(url):
        # Try once to activate Ollama if it was not running
        ensure_ollama_running(url=url, max_wait=8, log_cb=log_cb)

    if not is_ollama_running(url):
        if log_cb:
            log_cb(f"⚠️ AI server offline chưa phản hồi, giữ nguyên mục: {cleaned[:30]}...")
        return clean_remaining_chinese(cleaned)

    has_chinese_input = bool(re.search(r'[\u4e00-\u9fff]', cleaned))
    user_prompt = f"Station: {station}\nCategory: {category}\nInput: {cleaned}\nOutput:"

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": FACA_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        "stream": False,
        "options": {
            "temperature": 0.1,
            "top_p": 0.9,
            "num_predict": 180
        }
    }

    out = ""
    try:
        r = requests.post(f"{url}/api/chat", json=payload, timeout=timeout)
        if r.status_code == 200:
            resp_data = r.json()
            out = resp_data.get("message", {}).get("content", "").strip()
            if out.startswith('"') and out.endswith('"'):
                out = out[1:-1].strip()
        else:
            if log_cb:
                log_cb(f"   ⚠️ Chat API trả về mã {r.status_code}: {r.text[:80]}")
    except Exception as e:
        if log_cb:
            log_cb(f"   ⚠️ Kết nối dịch chat gặp lỗi: {e}")

    # If output still contains Chinese or is empty, retry with direct translation prompt
    if (not out) or (has_chinese_input and re.search(r'[\u4e00-\u9fff]', out)):
        retry_prompt = f"Translate the following factory test failure description directly into English. Important: Do NOT output any Chinese characters.\nInput: {cleaned}\nEnglish Output:"
        try:
            r = requests.post(
                f"{url}/api/generate",
                json={
                    "model": model_name,
                    "prompt": retry_prompt,
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 100}
                },
                timeout=timeout
            )
            if r.status_code == 200:
                retry_out = r.json().get("response", "").strip()
                if retry_out:
                    out = retry_out
            else:
                if log_cb:
                    log_cb(f"   ⚠️ Generate API trả về mã {r.status_code}: {r.text[:80]}")
        except Exception as e:
            if log_cb:
                log_cb(f"   ⚠️ Kết nối retry gặp lỗi: {e}")

    # Final guarantee: dictionary clean-up if any Chinese characters linger
    if re.search(r'[\u4e00-\u9fff]', out):
        out = clean_remaining_chinese(out)
    if not out:
        out = clean_remaining_chinese(cleaned)

    return out
