import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from collections import defaultdict
from typing import Dict, List, Any, Optional, Tuple, Callable
import openpyxl

from src.local_ai import translate_and_format_faca, is_ollama_running
from src.faca_sync import read_excel_faca, _normalize_key
from src.data_processor import parse_performance_breakdown
from src.utils import get_resource_path


def _normalize_station_for_matching(name: str) -> str:
    """Normalizes station name for fuzzy cross-matching between Performance CSV and Keynote."""
    if not name:
        return ""
    s = name.lower()
    s = s.replace("strain gauge", "sg").replace("strain_gauge", "sg")
    s = s.replace("charging rack", "charging").replace("charging_rack", "charging")
    s = s.replace("&", "").replace("_", "").replace("-", "")
    return re.sub(r'[^a-z0-9]', '', s)


def ensure_keynote_running():
    """Ensures Keynote / Keynote Creator Studio is active and ready to accept AppleEvents."""
    sc = 'tell application "System Events" to return (count of (processes whose bundle identifier is "com.apple.Keynote")) > 0'
    res = subprocess.run(["osascript", "-e", sc], capture_output=True, text=True)
    if res.stdout.strip() != "true":
        subprocess.run(["open", "-a", "Keynote Creator Studio"], capture_output=True)
        subprocess.run(["open", "-a", "Keynote"], capture_output=True)
        subprocess.run(["open", "-b", "com.apple.Keynote"], capture_output=True)
        for _ in range(20):
            time.sleep(0.5)
            r = subprocess.run(["osascript", "-e", sc], capture_output=True, text=True)
            if r.stdout.strip() == "true":
                time.sleep(1.0)
                # Wake up AppleEvent listener
                subprocess.run(["osascript", "-e", 'tell application id "com.apple.Keynote" to activate'], capture_output=True)
                time.sleep(0.5)
                break


def _sanitize_for_applescript(text: str) -> str:
    """Escapes text for AppleScript string literals."""
    if not text:
        return ""
    text = str(text)
    # Strip null bytes and non-printable control characters except newline and tab
    text = "".join(ch for ch in text if ch in "\n\r\t" or ord(ch) >= 32)
    text = text.replace("\\", "\\\\")
    text = text.replace('"', '\\"')
    text = text.replace("\r\n", "\\n").replace("\r", "\\n").replace("\n", "\\n")
    return text


def _parse_rate(val: Any) -> float:
    """
    Parses any percentage, decimal, float, or ratio (e.g. '1.20%', '0,012', '34R/5343T')
    into a decimal float (e.g. 0.012). Handles comma decimals (Vietnamese/European locale).
    """
    if val is None or val == "" or val == "missing value":
        return 0.0
    val_str = str(val).strip()
    if not val_str or val_str.lower() in ("missing value", "none", "nan"):
        return 0.0

    # 1. Check for count ratio like "34R/5343T", "34R / 5343T", "34 / 5343"
    m_ratio = re.search(r'(\d+(?:[.,]\d+)?)\s*[rR]?\s*/\s*(\d+(?:[.,]\d+)?)\s*[tT]?', val_str)
    if m_ratio:
        try:
            num = float(m_ratio.group(1).replace(",", "."))
            den = float(m_ratio.group(2).replace(",", "."))
            if den > 0:
                return num / den
        except (ValueError, TypeError):
            pass

    # 2. Check for percentage string, e.g. "1.20%", "0,64%", " 0.5% "
    is_percent = "%" in val_str
    clean = val_str.replace("%", "").strip()

    # Handle scientific notation like "6.0E-4" or "6,0E-4"
    clean = re.sub(r'(\d+),(\d+[eE])', r'\1.\2', clean)
    clean = clean.replace(",", ".")

    try:
        f = float(clean)
        if is_percent or f > 1.0:
            return f / 100.0
        return f
    except (ValueError, TypeError):
        return 0.0


def parse_keynote_for_phase3(
    keynote_path: str,
    log_cb: Optional[Callable[[str], None]] = None
) -> List[Dict[str, Any]]:
    """
    Reads all station slides from an English Keynote presentation (*_FACA_English.key)
    generated in Phase 2 via AppleScript.
    
    Dynamically identifies Station table vs Issues table on each slide,
    and flattens multi-line FACA text to prevent line-break corruption.
    """
    abs_path = os.path.abspath(keynote_path)
    if not os.path.exists(abs_path):
        raise FileNotFoundError(f"File Keynote không tồn tại: {abs_path}")

    ensure_keynote_running()

    if log_cb:
        log_cb(f"📖 Đang trích xuất dữ liệu trạm từ file Keynote: {os.path.basename(abs_path)}...")

    script = f'''
    on flattenText(txt)
        if txt is "missing value" or txt is missing value then return ""
        set AppleScript's text item delimiters to linefeed
        set itemParts to text items of (txt as text)
        set AppleScript's text item delimiters to " "
        set txt to itemParts as text
        set AppleScript's text item delimiters to return
        set itemParts to text items of txt
        set AppleScript's text item delimiters to " "
        set txt to itemParts as text
        set AppleScript's text item delimiters to tab
        set itemParts to text items of txt
        set AppleScript's text item delimiters to " "
        return (itemParts as text)
    end flattenText

    tell application id "com.apple.Keynote"
        activate
        delay 0.5
        set myDoc to open POSIX file "{abs_path}"
        delay 0.5
        set sCount to count of slides of myDoc
        set outStr to ""
        repeat with s from 1 to sCount
            tell slide s of myDoc
                set stTbl to 0
                set issTbl to 0
                set tCount to count of tables
                
                repeat with t from 1 to tCount
                    tell table t
                        set numCols to count of columns
                        set numRows to count of rows
                        set r1c1 to ""
                        set r2c1 to ""
                        try
                            set r1c1 to value of cell 1 of row 1 as text
                        end try
                        try
                            set r2c1 to value of cell 1 of row 2 as text
                        end try
                        
                        if numCols >= 8 then
                            set issTbl to t
                        else if (numCols >= 6 and numCols <= 8) and (r1c1 contains "Station" or r2c1 contains "Station") then
                            set stTbl to t
                        end if
                    end tell
                end repeat
                
                if stTbl > 0 then
                    tell table stTbl
                        set numRows to count of rows
                        set numCols to count of columns
                        set dataRow to 0
                        repeat with r from 2 to numRows
                            set c1Val to ""
                            try
                                set c1Val to value of cell 1 of row r as text
                            end try
                            if c1Val is not "" and c1Val is not "missing value" and c1Val does not contain "Station" then
                                set dataRow to r
                                exit repeat
                            end if
                        end repeat
                        
                        if dataRow > 0 then
                            set stName to ""
                            set stInput to ""
                            set stRetest to ""
                            set stRate to ""
                            try
                                set stName to my flattenText(value of cell 1 of row dataRow)
                            end try
                            try
                                set stInput to my flattenText(value of cell 2 of row dataRow)
                            end try
                            try
                                set stRetest to my flattenText(value of cell 4 of row dataRow)
                            end try
                            set stRate to ""
                            try
                                set stRate to my flattenText(value of cell 6 of row dataRow)
                            end try
                            if stRate is "" or stRate is "missing value" then
                                repeat with c from 1 to numCols
                                    try
                                        set hText to my flattenText(value of cell c of row 1)
                                        if hText contains "Retest" and hText does not contain "Target" and hText does not contain "MP" then
                                            set stRate to my flattenText(value of cell c of row dataRow)
                                            exit repeat
                                        end if
                                    end try
                                end repeat
                            end if
                            if stRate is "" or stRate is "missing value" then
                                try
                                    set stRate to my flattenText(value of cell numCols of row dataRow)
                                end try
                            end if
                            if stName is not "" and stName is not "missing value" then
                                set outStr to outStr & "STATION" & tab & (s as text) & tab & stName & tab & stInput & tab & stRetest & tab & stRate & linefeed
                            end if
                        end if
                    end tell
                end if
                
                if issTbl > 0 then
                    tell table issTbl
                        set rCount to count of rows
                        set cCount to count of columns
                        repeat with r from 2 to rCount
                            set iss to ""
                            set rate to ""
                            set rate2 to ""
                            set cat to ""
                            set faca to ""
                            set cp to ""
                            try
                                set iss to my flattenText(value of cell 2 of row r)
                            end try
                            try
                                set rate to my flattenText(value of cell 3 of row r)
                            end try
                            try
                                set rate2 to my flattenText(value of cell 4 of row r)
                            end try
                            try
                                set cat to my flattenText(value of cell 5 of row r)
                            end try
                            try
                                set faca to my flattenText(value of cell 6 of row r)
                            end try
                            if cCount >= 9 then
                                try
                                    set cp to my flattenText(value of cell 9 of row r)
                                end try
                            end if
                            if iss is not "" and iss is not "missing value" then
                                set outStr to outStr & "ISSUE" & tab & (s as text) & tab & (r as text) & tab & iss & tab & rate & tab & rate2 & tab & cat & tab & faca & tab & cp & linefeed
                            end if
                        end repeat
                    end tell
                end if
            end tell
        end repeat
        delay 0.3
        close myDoc saving no
        return outStr
    end tell
    '''
    
    proc_stdout = ""
    for attempt in range(2):
        ensure_keynote_running()
        with tempfile.NamedTemporaryFile("w", suffix=".applescript", delete=False) as f:
            f.write(script)
            tmp_script_path = f.name

        try:
            proc = subprocess.run(["osascript", tmp_script_path], capture_output=True, text=True)
        finally:
            if os.path.exists(tmp_script_path):
                os.remove(tmp_script_path)

        if proc.returncode == 0:
            proc_stdout = proc.stdout
            break
        elif attempt == 0 and ("-600" in proc.stderr or "Application isn’t running" in proc.stderr or "Application isn't running" in proc.stderr):
            time.sleep(1.5)
            continue
        else:
            raise RuntimeError(f"Lỗi khi đọc file Keynote bằng AppleScript: {proc.stderr}")

    stations: List[Dict[str, Any]] = []
    st_by_slide: Dict[int, Dict[str, Any]] = {}

    for line in proc_stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        tag = parts[0]
        if tag == "STATION" and len(parts) >= 6:
            s_idx = int(parts[1])
            st_name = parts[2].strip()
            if not st_name or st_name == "missing value":
                continue
            inp_str = parts[3].strip().replace(",", ".").replace(" ", "")
            ret_str = parts[4].strip().replace(",", ".").replace(" ", "")
            try:
                inp_val = float(inp_str)
            except (ValueError, TypeError):
                inp_val = 0.0
            try:
                ret_val = float(ret_str)
            except (ValueError, TypeError):
                ret_val = 0.0
            rate_val = _parse_rate(parts[5])
            if inp_val > 0 and ret_val >= 0:
                calc_val = ret_val / inp_val
                # If rate_val is 0, or if rate_val is 0.005 (0.50% target column) while calc_val differs,
                # use the true rate calculated from Retest and Input counts!
                if rate_val == 0.0 or (abs(rate_val - 0.005) < 1e-5 and abs(calc_val - 0.005) > 1e-4):
                    rate_val = calc_val
            elif rate_val == 0.0 and inp_val > 0 and ret_val > 0:
                rate_val = ret_val / inp_val

            st_dict = {
                "station": st_name,
                "input": inp_val,
                "retest": ret_val,
                "retest_pct": rate_val,
                "issues": []
            }
            stations.append(st_dict)
            st_by_slide[s_idx] = st_dict

        elif tag == "ISSUE" and len(parts) >= 8:
            s_idx = int(parts[1])
            target_st = st_by_slide.get(s_idx) or (stations[-1] if stations else None)
            if target_st is None:
                continue
            iss_name = parts[3].strip()
            rate_str1 = parts[4].strip()
            rate_str2 = parts[5].strip() if len(parts) >= 9 else ""
            cat_val = parts[6].strip() if len(parts) >= 9 and parts[6] != "missing value" else (parts[5].strip() if parts[5] != "missing value" else "")
            faca_val = parts[7].strip() if len(parts) >= 9 and parts[7] != "missing value" else (parts[6].strip() if len(parts) >= 7 and parts[6] != "missing value" else "")
            cp_val = parts[8].strip() if len(parts) >= 9 and parts[8] != "missing value" else (parts[7].strip() if len(parts) >= 8 and parts[7] != "missing value" else "")

            # 1. Parse from cell 3
            rr_val = _parse_rate(rate_str1)
            # 2. Fallback to cell 4 (which often contains counts like "34R/5343T")
            if rr_val == 0.0 and rate_str2:
                rr_val = _parse_rate(rate_str2)

            # 3. Fallback: check if rate_str1 or rate_str2 contains single count "34R" and station has input
            if rr_val == 0.0 and target_st.get("input", 0) > 0:
                m_cnt = re.search(r'(\d+)\s*[rR]', f"{rate_str1} {rate_str2}")
                if m_cnt:
                    try:
                        c_num = float(m_cnt.group(1))
                        rr_val = c_num / target_st["input"]
                    except (ValueError, TypeError):
                        pass

            target_st["issues"].append({
                "issue_name": iss_name,
                "item_rr": rr_val,
                "category": cat_val,
                "faca": faca_val,
                "check_point": cp_val
            })

    # Cross-validate station rate vs issue rates
    for s in stations:
        st_rate = s.get("retest_pct", 0.0)
        iss_list = s.get("issues", [])
        iss_sum = sum(i.get("item_rr", 0.0) for i in iss_list)

        # If station rate is 0 but issues have rates, derive station rate from issues
        if st_rate == 0.0 and iss_sum > 0:
            s["retest_pct"] = iss_sum
        # If station rate is positive but all issues have 0 rate, distribute station rate
        elif st_rate > 0.0 and iss_sum == 0.0 and iss_list:
            even_rate = st_rate / len(iss_list)
            for i in iss_list:
                i["item_rr"] = even_rate

    return stations


def build_phase3_station_comments(
    station_data: Dict[str, Any],
    excel_faca_map: Optional[Dict[Tuple[str, str], Dict[str, str]]] = None,
    use_ai_translation: bool = True,
    log_cb: Optional[Callable[[str], None]] = None
) -> Tuple[str, float]:
    """
    Groups a station's issues by Category, calculates cumulative %, translates/formats FACA,
    and returns (comments_string, station_retest_rate).
    
    Output format matches Sample-keynote2:
    [1.27%]Process:
    1.20% Test pad has some glue... CA: Clean test pad... CP: 8/25
    0.07% UOP issue... CA: UOP RR<0.2%... CP: Daily
    
    [0.45%]Fixture:
    0.34% Atlas send command... CP: Daily
    """
    st_name = station_data.get("station", "")
    st_rate = station_data.get("retest_pct", 0.0)
    issues = station_data.get("issues", [])

    if not issues:
        return ("", st_rate)

    # Group issues by category
    category_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for iss in issues:
        iss_name = iss.get("issue_name", "")
        iss_rr = iss.get("item_rr", 0.0)

        # 1. Use category, faca, and check_point directly parsed from the uploaded Keynote
        cat = iss.get("category", "").strip()
        faca = iss.get("faca", "").strip()
        cp = iss.get("check_point", "").strip()

        # 2. Fallback to excel_faca_map if missing
        if excel_faca_map:
            key = (_normalize_key(st_name), _normalize_key(iss_name))
            entry = excel_faca_map.get(key, {})
            if not cat:
                cat = entry.get("category", "").strip()
            if not faca:
                faca = entry.get("faca", "").strip()

        if not cat:
            cat = "Process"

        # Normalize category name
        cat_lower = cat.lower()
        if "process" in cat_lower:
            cat = "Process"
        elif "fixt" in cat_lower:
            cat = "Fixture"
        elif "ble" in cat_lower or "fw" in cat_lower:
            cat = "Castor BLE FW"
        elif "mat" in cat_lower:
            cat = "Material"
        elif "oper" in cat_lower or cat_lower == "op":
            cat = "Operator"
        elif "desig" in cat_lower:
            cat = "Design"
        elif "stat" in cat_lower:
            cat = "Station"

        category_groups[cat].append({
            "issue_name": iss_name,
            "item_rr": iss_rr,
            "faca": faca,
            "check_point": cp,
            "category": cat
        })

    # Assemble Category blocks
    comment_blocks: List[str] = []

    # Sort categories with highest cumulative RR first
    sorted_categories = sorted(
        category_groups.keys(),
        key=lambda c: sum(i["item_rr"] for i in category_groups[c]),
        reverse=True
    )

    for cat in sorted_categories:
        cat_issues = category_groups[cat]
        cat_total_rr = sum(i["item_rr"] for i in cat_issues)
        if cat_total_rr == 0 and st_rate > 0:
            cat_total_rr = st_rate / max(1, len(sorted_categories))
        cat_header = f"[{cat_total_rr*100:.2f}%]{cat}:"

        lines = [cat_header]

        # Merge identical descriptions and sum their percentages
        merged_items: Dict[str, Dict[str, Any]] = {}
        for it in cat_issues:
            rr = it.get("item_rr", 0.0)
            raw_faca = it.get("faca", "").strip()
            raw_iss = it.get("issue_name", "").strip()
            raw_cp = it.get("check_point", "").strip()
            if raw_cp.lower() in ("missing value", "none", "nan"):
                raw_cp = ""

            # Determine core text
            if raw_faca and raw_faca.lower() not in ("missing value", "none"):
                core_text = raw_faca
            else:
                core_text = raw_iss

            if not core_text or core_text.lower() in ("missing value", "none"):
                continue

            # Check if core_text already contains CP:
            cp_in_text = ""
            cp_match = re.search(r'\bcp\s*:\s*([^;\n]+)', core_text, re.IGNORECASE)
            if cp_match:
                cp_in_text = cp_match.group(1).strip()
                core_without_cp = re.sub(r'\bcp\s*:\s*[^;\n]+', '', core_text, flags=re.IGNORECASE).strip()
            else:
                core_without_cp = core_text

            final_cp = raw_cp or cp_in_text

            # Create a normalized key for comparison
            # Strip leading % if already present (e.g., "1.20% Test pad...")
            norm_key = re.sub(r'^\d+(\.\d+)?%\s*', '', core_without_cp)
            norm_key = re.sub(r'\s+', ' ', norm_key.strip().lower())
            norm_key = re.sub(r'[.,;:\s]+$', '', norm_key)

            clean_core = re.sub(r'^\d+(\.\d+)?%\s*', '', core_without_cp).strip()
            clean_core = clean_core.rstrip(".,; ")

            if norm_key in merged_items:
                merged_items[norm_key]["total_rr"] += rr
                if final_cp and final_cp not in merged_items[norm_key]["cps"]:
                    merged_items[norm_key]["cps"].append(final_cp)
            else:
                merged_items[norm_key] = {
                    "core_text": clean_core,
                    "cps": [final_cp] if final_cp else [],
                    "total_rr": rr
                }

        # Sort descending by cumulative rate
        sorted_merged = sorted(
            merged_items.values(),
            key=lambda x: x["total_rr"],
            reverse=True
        )

        for item in sorted_merged:
            item_rr = item["total_rr"]
            if item_rr == 0.0 and cat_total_rr > 0:
                item_rr = cat_total_rr / max(1, len(sorted_merged))
            rate_pct = f"{item_rr*100:.2f}%"
            core = item["core_text"]
            cps = item["cps"]
            if cps:
                cp_str = f" CP: {', '.join(cps)}"
                display_line = f"{rate_pct} {core}{cp_str}"
            else:
                display_line = f"{rate_pct} {core}"
            lines.append(display_line)

        comment_blocks.append("\n".join(lines))

    # Join multiple categories with blank line
    full_comments = "\n\n".join(comment_blocks)
    return (full_comments, st_rate)


def _get_rate_background_color(rate: Optional[float]) -> Optional[str]:
    """Returns AppleScript RGB background color matching the RR tier legend in Table 2."""
    if rate is None:
        return None
    if rate <= 0.005:  # RR <= 0.5%
        return "{44259, 58790, 33996}"  # Light Green
    elif rate <= 0.02:  # 0.5% < RR <= 2%
        return "{65535, 65292, 37803}"  # Light Yellow
    elif rate <= 0.03:  # 2% < RR <= 3%
        return "{65163, 53278, 33819}"  # Light Orange
    else:  # RR > 3%
        return "{64938, 36638, 32225}"  # Light Red


# Arrow images used by the legend cells (Table 3, row 2 on slide 1 of the template).
# key -> (asset file inside the template's Data/ folder, display width, display height in pt).
# The sizes are the ones the legend cell styles use, so the arrows look identical.
TREND_LEGEND_IMAGES = {
    "down": ("pasted-image-9090.png", 21, 21),   # BYPT PPVT < BYLG MP  (green)
    "flat": ("Neutral-9091.png", 28, 13),        # Comparable           (gray)
    "up": ("pasted-image-9092.png", 19, 19),     # BYPT PPVT > BYLG MP  (single red)
    "up2": ("pasted-movie-9093.png", 57, 28),    # > BYLG MP by > 1%    (double red)
}


def _calculate_trend(
    current_rate: Optional[float],
    benchmark_rate: Optional[float]
) -> Optional[str]:
    """
    Returns the trend key for Column 4 (see TREND_LEGEND_IMAGES), or None if no benchmark.
      - current < benchmark                -> 'down' (âm là bé hơn, BYPT PPVT < BYLG MP - mũi tên xanh lá)
      - 0 <= current - benchmark <= 0.5%   -> 'flat' (Comparable, chỉ lấy phần +0.5% không lấy phần âm - mũi tên xám)
      - 0.5% < current - benchmark <= 1.0% -> 'up'   (BYPT PPVT > BYLG MP - mũi tên cam / đỏ đơn)
      - current - benchmark > 1.0%         -> 'up2'  (> BYLG MP by > 1% - mũi tên đỏ đôi)
    """
    if current_rate is None or benchmark_rate is None:
        return None

    diff = round(current_rate - benchmark_rate, 6)
    if diff < 0:
        return "down"
    elif diff <= 0.005:
        return "flat"
    elif diff <= 0.01:
        return "up"
    else:
        return "up2"


def _extract_trend_images(template_path: str, out_dir: str) -> Dict[str, Tuple[str, int, int]]:
    """Copies the legend arrow images out of the template (.key zip or package)."""
    result: Dict[str, Tuple[str, int, int]] = {}
    for key, (asset, w, h) in TREND_LEGEND_IMAGES.items():
        dest = os.path.join(out_dir, asset)
        member = f"Data/{asset}"
        if os.path.isdir(template_path):
            src = os.path.join(template_path, member)
            if not os.path.exists(src):
                raise FileNotFoundError(f"Template thiếu ảnh mũi tên chú thích: {member}")
            shutil.copy2(src, dest)
        else:
            with zipfile.ZipFile(template_path) as z:
                if member not in z.namelist():
                    raise FileNotFoundError(f"Template thiếu ảnh mũi tên chú thích: {member}")
                with open(dest, "wb") as f:
                    f.write(z.read(member))
        result[key] = (dest, w, h)
    return result


def _place_trend_arrows(
    doc_path: str,
    template_path: str,
    targets: List[Tuple[int, int, str]],
    log_cb: Optional[Callable[[str], None]] = None
) -> None:
    """
    Places the legend's own arrow image centered in cell D{row} of Table 1 on each slide.
    targets = [(slide_num, row_num, key)]. Keynote's AppleScript cannot set a cell's image
    fill, so the image is positioned over the cell (no macOS permissions needed).
    """
    if not targets:
        return
    ensure_keynote_running()
    if log_cb:
        log_cb(f"🏹 Đặt mũi tên chú thích vào cột Trending ({len(targets)} trạm)...")

    img_dir = tempfile.mkdtemp(prefix="kn_trend_")
    try:
        images = _extract_trend_images(template_path, img_dir)
        lines = [
            'on placeArrow(theSlide, r, imgPath, w, h)',
            '    tell application id "com.apple.Keynote"',
            '        tell theSlide',
            '            tell table 1',
            '                set tp to position',
            '                set x0 to (item 1 of tp) + (width of column 1) + (width of column 2) + (width of column 3)',
            '                set w4 to width of column 4',
            '                set y0 to item 2 of tp',
            '                repeat with i from 1 to (r - 1)',
            '                    set y0 to y0 + (height of row i)',
            '                end repeat',
            '                set hR to height of row r',
            '            end tell',
            '            set px to (x0 + (w4 - w) / 2) as integer',
            '            set py to (y0 + (hR - h) / 2) as integer',
            '            make new image with properties {file:(POSIX file imgPath), position:{px, py}, width:w, height:h}',
            '        end tell',
            '    end tell',
            'end placeArrow',
            'tell application id "com.apple.Keynote"',
            '    activate',
            '    delay 0.5',
            f'    set myDoc to open POSIX file "{doc_path}"',
            '    delay 1.0',
        ]
        for s_num, r_num, key in targets:
            img_path, w, h = images[key]
            lines.append(f'    my placeArrow(slide {s_num} of myDoc, {r_num}, "{img_path}", {w}, {h})')
        lines += [
            '    delay 0.5',
            '    save myDoc',
            '    delay 0.5',
            '    close myDoc saving yes',
            'end tell',
            'return "DONE"',
        ]

        with tempfile.NamedTemporaryFile("w", suffix=".applescript", delete=False) as f:
            f.write("\n".join(lines))
            tmp_path = f.name
        try:
            proc = subprocess.run(["osascript", tmp_path], capture_output=True, text=True)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        if proc.returncode != 0:
            raise RuntimeError(f"Lỗi khi đặt mũi tên vào cột 4: {proc.stderr}")
    finally:
        shutil.rmtree(img_dir, ignore_errors=True)


def calculate_summary_metrics(
    stations: List[Dict[str, Any]],
    target_mp_rate: float = 0.005,
    benchmarks: Optional[Dict[str, float]] = None
) -> str:
    """
    Computes overall summary KPIs for the top of Slide 1:
    • 39% (7/18)stations projected RR can achieve <0.5% Retest target
    • 56% (10/18)stations are trending comparable to BYLG MP
    • 6% (1/18)stations are trending down compared to BYLG MP
    """
    valid = [s for s in stations if s.get("input", 0) > 0 or s.get("retest_pct", 0.0) > 0]
    total = len(valid) if valid else len(stations)
    if total == 0:
        return "Summary:\n• Chưa có dữ liệu trạm."

    achieve_target = sum(1 for s in valid if s.get("retest_pct", 0.0) <= target_mp_rate)
    pct_achieve = round((achieve_target / total) * 100)

    # If benchmarks are provided, compare each station with its benchmark
    if benchmarks:
        comparable = 0
        trending_down = 0
        for s in valid:
            st_name = s.get("station", "")
            r = s.get("retest_pct", 0.0)
            norm = _normalize_station_for_matching(st_name)
            bench = benchmarks.get(norm)
            if bench is None:
                for bk, bv in benchmarks.items():
                    if norm in bk or bk in norm:
                        bench = bv
                        break
            if bench is not None:
                diff = round(r - bench, 6)
                if diff < 0:
                    trending_down += 1
                elif diff <= 0.005:
                    comparable += 1
            else:
                if r <= target_mp_rate:
                    trending_down += 1
                elif r <= (target_mp_rate + 0.005):
                    comparable += 1
    else:
        comparable = sum(1 for s in valid if target_mp_rate < s.get("retest_pct", 0.0) <= (target_mp_rate + 0.01))
        trending_down = sum(1 for s in valid if s.get("retest_pct", 0.0) > (target_mp_rate + 0.01))

    pct_comp = round((comparable / total) * 100)
    pct_down = max(0, 100 - pct_achieve - pct_comp) if (achieve_target + comparable + trending_down == total) else round((trending_down / total) * 100)

    target_str = f"<{target_mp_rate*100:.1f}%" if target_mp_rate < 0.01 else f"<{target_mp_rate*100:.0f}%"

    summary_text = (
        f"Summary:\n"
        f"• {pct_achieve:.0f}% ({achieve_target}/{total})stations projected RR can achieve {target_str} Retest target\n"
        f"• {pct_comp:.0f}% ({comparable}/{total})stations are trending comparable to BYLG MP\n"
        f"• {pct_down:.0f}% ({trending_down}/{total})stations are trending down compared to BYLG MP"
    )
    return summary_text


def _concatenate_cover_and_user_slides(
    output_keynote_path: str,
    cover_template_path: str,
    project_name: str,
    user_keynote_path: Optional[str] = None,
    log_cb: Optional[Callable[[str], None]] = None
) -> None:
    """
    Concatenates slides in the exact order requested:
    1. Sample-keynote3.key (Cover slide) with project name replaced and exact font/color styling.
    2. Executive Summary slides (already populated in output_keynote_path).
    3. User original uploaded Keynote slides (from user_keynote_path, if provided).
    """
    abs_output = os.path.abspath(output_keynote_path)
    abs_cover = get_resource_path(cover_template_path)
    if not os.path.exists(abs_cover):
        rel_cov = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Sample output", "Sample-keynote3.key")
        if os.path.exists(rel_cov):
            abs_cover = os.path.abspath(rel_cov)

    tmp_cover = None
    tmp_user = None
    try:
        has_cover = os.path.exists(abs_cover)
        if has_cover:
            tmp_cover = tempfile.mktemp(suffix=".key", prefix="_cov_tmp_")
            if os.path.isdir(abs_cover):
                shutil.copytree(abs_cover, tmp_cover)
            else:
                shutil.copy2(abs_cover, tmp_cover)
            if log_cb:
                log_cb("📑 Chuẩn bị trang bìa Cover Slide từ Sample-keynote3.key...")

        has_user = False
        if user_keynote_path and os.path.exists(user_keynote_path):
            abs_user = os.path.abspath(user_keynote_path)
            tmp_user = tempfile.mktemp(suffix=".key", prefix="_usr_tmp_")
            if os.path.isdir(abs_user):
                shutil.copytree(abs_user, tmp_user)
            else:
                shutil.copy2(abs_user, tmp_user)
            has_user = True
            if log_cb:
                log_cb(f"📑 Chuẩn bị dữ liệu nối từ file gốc: {os.path.basename(abs_user)}...")

        if not has_cover and not has_user:
            return

        ensure_keynote_running()

        proj_display = project_name.strip() if project_name and project_name.strip() else "Project"
        clean_proj = proj_display
        if clean_proj.lower().startswith("project "):
            clean_proj = clean_proj[8:].strip()
        elif clean_proj.lower() == "project":
            clean_proj = "Project"

        # Preserve the "Build..." suffix from Sample-keynote3.key (e.g. "Build FATP/SMT")
        if "build" in clean_proj.lower():
            blue_part = clean_proj.rstrip() + " "
        else:
            blue_part = f"{clean_proj} Build FATP/SMT "

        sanitized_blue_part = _sanitize_for_applescript(blue_part)
        full_cover_title = f"{sanitized_blue_part}| Retest Breakdown"
        blue_len = len(blue_part)
        c_bar = blue_len + 1
        c_space = blue_len + 2
        c_breakdown_start = blue_len + 3
        c_end = len(full_cover_title)

        as_lines = [
            'use AppleScript version "2.4"',
            'with timeout of 600 seconds',
            '    tell application id "com.apple.Keynote"',
            '        activate',
            '        delay 0.5',
            f'        set myDoc to open POSIX file "{abs_output}"',
            '        delay 0.5',
        ]

        if has_cover and tmp_cover:
            as_lines.extend([
                f'        set coverDoc to open POSIX file "{tmp_cover}"',
                '        delay 0.5',
                '        move slide 1 of coverDoc to before slide 1 of myDoc',
                '        delay 0.3',
                '        close coverDoc saving no',
                '        delay 0.3',
                '        tell slide 1 of myDoc',
                '            repeat with ti in {text item 2, text item 3}',
                '                try',
                f'                    set object text of ti to "{full_cover_title}"',
                '                    tell object text of ti',
                '                        set size to 56.0',
                f'                        set font of characters 1 thru {blue_len} to "HelveticaNeue-Light"',
                f'                        set color of characters 1 thru {blue_len} to {{3897, 32894, 65434}}',
                f'                        set font of character {c_bar} to "HelveticaNeue-UltraLight"',
                f'                        set color of character {c_bar} to {{13363, 13363, 13363}}',
                f'                        set font of character {c_space} to "HelveticaNeue-Light"',
                f'                        set color of character {c_space} to {{13363, 13363, 13363}}',
                f'                        set font of characters {c_breakdown_start} thru {c_end} to "HelveticaNeue-Bold"',
                f'                        set color of characters {c_breakdown_start} thru {c_end} to {{13363, 13363, 13363}}',
                '                    end tell',
                '                end try',
                '            end repeat',
                '        end tell',
                '        delay 0.3',
            ])

        if has_user and tmp_user:
            as_lines.extend([
                f'        set userDoc to open POSIX file "{tmp_user}"',
                '        delay 0.5',
                '        set uCount to count of slides of userDoc',
                '        repeat uCount times',
                '            move slide 1 of userDoc to after last slide of myDoc',
                '            delay 0.05',
                '        end repeat',
                '        close userDoc saving no',
                '        delay 0.3',
            ])

        as_lines.extend([
            '        save myDoc',
            '        delay 0.5',
            '        close myDoc saving yes',
            '        return "DONE"',
            '    end tell',
            'end timeout'
        ])

        batch_script = "\n".join(as_lines)

        for attempt in range(2):
            ensure_keynote_running()
            with tempfile.NamedTemporaryFile("w", suffix=".applescript", delete=False) as f:
                f.write(batch_script)
                tmp_script_path = f.name
            try:
                proc = subprocess.run(["osascript", tmp_script_path], capture_output=True, text=True)
            finally:
                if os.path.exists(tmp_script_path):
                    os.remove(tmp_script_path)

            if proc.returncode == 0:
                break
            elif attempt == 0 and ("-600" in proc.stderr or "Application isn’t running" in proc.stderr or "Application isn't running" in proc.stderr):
                time.sleep(1.5)
                continue
            else:
                raise RuntimeError(f"Lỗi khi ghép nối slide Keynote: {proc.stderr}")

    finally:
        if tmp_cover:
            if os.path.isdir(tmp_cover):
                shutil.rmtree(tmp_cover, ignore_errors=True)
            elif os.path.exists(tmp_cover):
                os.remove(tmp_cover)
        if tmp_user:
            if os.path.isdir(tmp_user):
                shutil.rmtree(tmp_user, ignore_errors=True)
            elif os.path.exists(tmp_user):
                os.remove(tmp_user)


def generate_phase3_executive_keynote(
    report_data: Optional[Dict[str, Any]] = None,
    input_keynote_path: Optional[str] = None,
    output_keynote_path: str = "output/Executive_Retest_Breakdown_Report.key",
    template_keynote_path: str = "Sample output/Sample-keynote2.key",
    cover_template_path: str = "Sample output/Sample-keynote3.key",
    excel_source_path: Optional[str] = None,
    performance_csv_path: Optional[str] = None,
    benchmark_performance_csv_path: Optional[str] = None,
    target_mp_rate: float = 0.005,
    project_name: Optional[str] = None,
    use_ai_translation: bool = False,
    log_cb: Optional[Callable[[str], None]] = None
) -> str:
    """
    Generates the Executive Summary Keynote report (Retest Breakdown)
    matching the layout and styling of Sample-keynote2.key.
    
    Directly consumes the English Keynote (*_FACA_English.key) generated from Phase 2,
    and optionally aligns station names, order, and % with Performance-Breakdown.csv,
    plus an optional benchmark Performance-Breakdown.csv for column 2.
    """
    abs_template = get_resource_path(template_keynote_path)
    abs_output = os.path.abspath(output_keynote_path)
    os.makedirs(os.path.dirname(abs_output), exist_ok=True)

    if not os.path.exists(abs_template):
        raise FileNotFoundError(f"Không tìm thấy template Keynote mẫu: {abs_template}")

    # Determine Project Name
    if not project_name and input_keynote_path:
        base = os.path.splitext(os.path.basename(input_keynote_path))[0]
        clean_base = base.replace("_FACA_English", "").replace("_FACA_Updated", "").replace("Retest_Breakdown_", "")
        if clean_base and clean_base != "xxx":
            project_name = clean_base
        else:
            project_name = "Project"
    elif not project_name:
        project_name = "Project"

    # Determine stations data
    valid_stations: List[Dict[str, Any]] = []

    # 1. Parse Keynote if provided to extract issues, FACA, and any station data
    keynote_stations: List[Dict[str, Any]] = []
    if input_keynote_path and os.path.exists(input_keynote_path):
        if log_cb:
            log_cb(f"📖 Đang đọc dữ liệu từ file Keynote Tiếng Anh: {os.path.basename(input_keynote_path)}")
        keynote_stations = parse_keynote_for_phase3(input_keynote_path, log_cb=log_cb)

    # 2. If Performance-Breakdown.csv is provided, it acts as the primary station roster
    if performance_csv_path and os.path.exists(performance_csv_path):
        if log_cb:
            log_cb(f"📊 Đang nạp danh mục trạm và % từ Performance-Breakdown: {os.path.basename(performance_csv_path)}...")
        perf_data = parse_performance_breakdown(performance_csv_path)

        # Build lookup map for Keynote stations
        kn_by_norm: Dict[str, Tuple[int, Dict[str, Any]]] = {}
        matched_kn_indices = set()
        for idx, ks in enumerate(keynote_stations):
            n = _normalize_station_for_matching(ks.get("station", ""))
            if n:
                kn_by_norm[n] = (idx, ks)

        # Build valid_stations following the EXACT order of Performance-Breakdown
        for perf_st_name, p_info in perf_data.items():
            norm_p = _normalize_station_for_matching(perf_st_name)
            matched_ks = None

            if norm_p in kn_by_norm:
                m_idx, matched_ks = kn_by_norm[norm_p]
                matched_kn_indices.add(m_idx)
            else:
                for norm_k, (m_idx, cand_ks) in kn_by_norm.items():
                    if norm_p in norm_k or norm_k in norm_p:
                        matched_ks = cand_ks
                        matched_kn_indices.add(m_idx)
                        break

            # Rate (Column 3): Ưu tiên lấy % từ file Keynote nếu trùng tên trạm, fallback sang Performance CSV
            perf_rate = p_info.get("retest_pct", 0.0)
            kn_rate = matched_ks.get("retest_pct", 0.0) if matched_ks else 0.0

            if matched_ks and kn_rate > 0:
                final_rate = kn_rate
            elif perf_rate > 0:
                final_rate = perf_rate
            elif matched_ks and "retest_pct" in matched_ks and matched_ks["retest_pct"] is not None:
                final_rate = kn_rate
            else:
                final_rate = perf_rate

            # Input / Retest count: ưu tiên Keynote nếu có dữ liệu, fallback sang Performance CSV
            final_input = p_info.get("input", 0)
            final_retest = p_info.get("retest", 0)
            if matched_ks:
                if matched_ks.get("input", 0) > 0:
                    final_input = matched_ks.get("input", 0)
                if matched_ks.get("retest", 0) > 0:
                    final_retest = matched_ks.get("retest", 0)

            # Name: prefer matched Keynote station name if available, otherwise perf_st_name
            final_st_name = matched_ks.get("station", "") if matched_ks else perf_st_name
            if not final_st_name:
                final_st_name = perf_st_name

            issues = matched_ks.get("issues", []) if matched_ks else []

            valid_stations.append({
                "station": final_st_name,
                "input": final_input,
                "retest": final_retest,
                "retest_pct": final_rate,
                "issues": issues
            })

        # Append any leftover stations from Keynote that were not in Performance CSV
        for idx, ks in enumerate(keynote_stations):
            if idx not in matched_kn_indices:
                valid_stations.append(ks)

    elif keynote_stations:
        valid_stations = keynote_stations
    elif report_data:
        stations = report_data.get("stations", [])
        valid_stations = [s for s in stations if s.get("input", 0) > 0]
        if not valid_stations:
            valid_stations = stations

    if not valid_stations:
        raise ValueError("Không tìm thấy dữ liệu trạm nào từ file đầu vào!")

    # 3. Parse Benchmark Performance CSV if provided (for Column 2)
    bench_by_norm: Dict[str, float] = {}
    if benchmark_performance_csv_path and os.path.exists(benchmark_performance_csv_path):
        if log_cb:
            log_cb(f"📊 Đang nạp file Performance đối chứng (cột 2): {os.path.basename(benchmark_performance_csv_path)}...")
        bench_data = parse_performance_breakdown(benchmark_performance_csv_path)
        for b_name, b_info in bench_data.items():
            b_norm = _normalize_station_for_matching(b_name)
            if b_norm:
                bench_by_norm[b_norm] = b_info.get("retest_pct", 0.0)

    if log_cb:
        log_cb(f"📊 Danh sách tổng hợp gồm {len(valid_stations)} trạm kiểm tra.")
        log_cb(f"📋 Chuẩn bị template báo cáo tổng kết: {os.path.basename(abs_template)}")

    # 1. Duplicate template to target output
    if os.path.exists(abs_output):
        if os.path.isdir(abs_output):
            shutil.rmtree(abs_output)
        else:
            os.remove(abs_output)

    if os.path.isdir(abs_template):
        shutil.copytree(abs_template, abs_output)
    else:
        shutil.copy2(abs_template, abs_output)

    # 2. Load Excel FACA map if provided as fallback
    excel_faca_map = {}
    if excel_source_path and os.path.exists(excel_source_path):
        if log_cb:
            log_cb(f"📖 Đọc Category & FACA bổ trợ từ file Excel: {os.path.basename(excel_source_path)}")
        excel_faca_map = read_excel_faca(excel_source_path)

    # 3. Pre-compute comments and rates for each station
    station_payloads = []
    for idx, st in enumerate(valid_stations):
        st_name = st.get("station", "")
        if log_cb:
            log_cb(f"   ➔ [{idx+1}/{len(valid_stations)}] Phân loại & tổng hợp lỗi trạm: {st_name}")
        comments, rate = build_phase3_station_comments(
            st,
            excel_faca_map=excel_faca_map,
            use_ai_translation=use_ai_translation,
            log_cb=log_cb
        )

        # Look up rate in benchmark map for column 2
        bench_rate = None
        if bench_by_norm:
            norm_name = _normalize_station_for_matching(st_name)
            if norm_name in bench_by_norm:
                bench_rate = bench_by_norm[norm_name]
            else:
                for b_k, b_val in bench_by_norm.items():
                    if norm_name in b_k or b_k in norm_name:
                        bench_rate = b_val
                        break

        trend_key = _calculate_trend(rate, bench_rate)
        bench_bg = _get_rate_background_color(bench_rate)
        rate_bg = _get_rate_background_color(rate)

        station_payloads.append({
            "station": st_name,
            "rate": rate,
            "rate_str": f"{rate*100:.2f}%",
            "rate_bg": rate_bg,
            "benchmark_rate": bench_rate,
            "benchmark_bg": bench_bg,
            "trend_key": trend_key,
            "comments": comments
        })

    # 4. Calculate high-level summary KPIs
    summary_text = calculate_summary_metrics(valid_stations, target_mp_rate=target_mp_rate, benchmarks=bench_by_norm if bench_by_norm else None)

    # 5. Build AppleScript batch to write data into Keynote slides
    # Each slide has 6 station rows (rows 2..7 of Table 1)
    STATIONS_PER_SLIDE = 6
    num_slides_needed = max(1, (len(station_payloads) + STATIONS_PER_SLIDE - 1) // STATIONS_PER_SLIDE)

    # Ensure Keynote is running before opening and writing
    ensure_keynote_running()

    if log_cb:
        log_cb(f"✍️ Ghi dữ liệu vào {num_slides_needed} slide Keynote qua AppleScript...")

    as_lines = [
        'use AppleScript version "2.4"',
        'tell application id "com.apple.Keynote"',
        '    activate',
        '    delay 0.5',
        f'    set myDoc to open POSIX file "{abs_output}"',
        '    delay 0.5',
        '    tell myDoc'
    ]

    # Ensure correct slide count with delays
    as_lines.append(f'        set curSlides to count of slides')
    as_lines.append(f'        if curSlides < {num_slides_needed} then')
    as_lines.append(f'            repeat with i from (curSlides + 1) to {num_slides_needed}')
    as_lines.append(f'                duplicate slide 2 to after slide (i - 1)')
    as_lines.append(f'                delay 0.5')
    as_lines.append(f'            end repeat')
    as_lines.append(f'        else if curSlides > {num_slides_needed} then')
    as_lines.append(f'            repeat with i from curSlides to ({num_slides_needed} + 1) by -1')
    as_lines.append(f'                delete slide i')
    as_lines.append(f'                delay 0.2')
    as_lines.append(f'            end repeat')
    as_lines.append(f'        end if')
    as_lines.append(f'        delay 0.5')

    # Update Project title in Shape 1 of all slides (Project bold blue, | Retest breakdown light grey)
    proj_display = project_name.strip() if project_name and project_name.strip() else "Project"
    sanitized_project = _sanitize_for_applescript(proj_display)
    full_title = f"{sanitized_project} | Retest breakdown"
    p_len = len(proj_display)
    full_len = len(full_title)

    as_lines.append(f'        repeat with s from 1 to {num_slides_needed}')
    as_lines.append(f'            tell slide s')
    as_lines.append(f'                try')
    as_lines.append(f'                    set object text of shape 1 to "{full_title}"')
    as_lines.append(f'                    tell object text of shape 1')
    as_lines.append(f'                        set font of characters 1 thru {p_len} to "Helvetica-Bold"')
    as_lines.append(f'                        set color of characters 1 thru {p_len} to {{3918, 32850, 65535}}')
    as_lines.append(f'                        set font of characters {p_len + 1} thru {full_len} to "Helvetica-Light"')
    as_lines.append(f'                        set color of characters {p_len + 1} thru {full_len} to {{19531, 19532, 19532}}')
    as_lines.append(f'                    end tell')
    as_lines.append(f'                end try')
    as_lines.append(f'            end tell')
    as_lines.append(f'        end repeat')

    # Update Summary Shape 2 on Slide 1
    sanitized_summary = _sanitize_for_applescript(summary_text)
    as_lines.append(f'        try')
    as_lines.append(f'            tell slide 1')
    as_lines.append(f'                set object text of shape 2 to "{sanitized_summary}"')
    as_lines.append(f'            end tell')
    as_lines.append(f'        end try')

    # Fill stations into Table 1 of each slide
    trend_targets: List[Tuple[int, int, str]] = []
    for slide_idx in range(num_slides_needed):
        s_num = slide_idx + 1
        slide_chunk = station_payloads[slide_idx * STATIONS_PER_SLIDE : (slide_idx + 1) * STATIONS_PER_SLIDE]

        as_lines.append(f'        tell slide {s_num}')
        as_lines.append(f'            tell table 1')

        for r_offset, payload in enumerate(slide_chunk):
            r_num = r_offset + 2  # Table row 1 is header, data starts at row 2
            st_clean = _sanitize_for_applescript(payload["station"])
            rate_val = payload["rate"]
            bench_val = payload.get("benchmark_rate")
            comm_clean = _sanitize_for_applescript(payload["comments"])
            if payload.get("trend_key"):
                trend_targets.append((s_num, r_num, payload["trend_key"]))

            as_lines.append(f'                try')
            as_lines.append(f'                    set value of cell 1 of row {r_num} to "{st_clean}"')
            if bench_val is not None:
                as_lines.append(f'                    set value of cell 2 of row {r_num} to {bench_val}')
                if payload.get("benchmark_bg"):
                    as_lines.append(f'                    set background color of cell 2 of row {r_num} to {payload["benchmark_bg"]}')
            else:
                as_lines.append(f'                    set value of cell 2 of row {r_num} to ""')
                as_lines.append(f'                    set background color of cell 2 of row {r_num} to {{65527, 65535, 65524}}')
            as_lines.append(f'                    set value of cell 3 of row {r_num} to {rate_val}')
            if payload.get("rate_bg"):
                as_lines.append(f'                    set background color of cell 3 of row {r_num} to {payload["rate_bg"]}')
            as_lines.append(f'                    set value of cell 4 of row {r_num} to ""')
            as_lines.append(f'                    set value of cell 5 of row {r_num} to "{comm_clean}"')
            as_lines.append(f'                end try')

        # If chunk is less than 6 stations, blank out unused rows
        if len(slide_chunk) < STATIONS_PER_SLIDE:
            for blank_r in range(len(slide_chunk) + 2, STATIONS_PER_SLIDE + 2):
                as_lines.append(f'                try')
                as_lines.append(f'                    set value of cell 1 of row {blank_r} to ""')
                as_lines.append(f'                    set value of cell 2 of row {blank_r} to ""')
                as_lines.append(f'                    set background color of cell 2 of row {blank_r} to {{65527, 65535, 65524}}')
                as_lines.append(f'                    set value of cell 3 of row {blank_r} to ""')
                as_lines.append(f'                    set background color of cell 3 of row {blank_r} to {{65527, 65535, 65524}}')
                as_lines.append(f'                    set value of cell 4 of row {blank_r} to ""')
                as_lines.append(f'                    set value of cell 5 of row {blank_r} to ""')
                as_lines.append(f'                end try')

        as_lines.append(f'            end tell')
        as_lines.append(f'        end tell')

    as_lines.extend([
        '    end tell',
        '    delay 0.5',
        '    save myDoc',
        '    delay 0.5',
        '    close myDoc saving yes',
        '    return "DONE"',
        'end tell'
    ])

    batch_script = "\n".join(as_lines)

    for attempt in range(2):
        ensure_keynote_running()
        with tempfile.NamedTemporaryFile("w", suffix=".applescript", delete=False) as f:
            f.write(batch_script)
            tmp_script_path = f.name

        try:
            proc = subprocess.run(["osascript", tmp_script_path], capture_output=True, text=True)
        finally:
            if os.path.exists(tmp_script_path):
                os.remove(tmp_script_path)

        if proc.returncode == 0:
            break
        elif attempt == 0 and ("-600" in proc.stderr or "Application isn’t running" in proc.stderr or "Application isn't running" in proc.stderr):
            if log_cb:
                log_cb("⚠️ Keynote cần khởi động lại (-600), đang kích hoạt lại...")
            time.sleep(1.5)
            continue
        else:
            raise RuntimeError(f"Lỗi khi lưu báo cáo tổng kết Keynote: {proc.stderr}")

    # 6. Column 4: place the exact legend arrow images into Table 1
    _place_trend_arrows(abs_output, abs_template, trend_targets, log_cb=log_cb)

    # 7. Concatenate Cover Slide (Sample 3) + Executive Summary (Sample 2) + User Original Keynote
    if log_cb:
        log_cb("🔗 Ghép nối file theo thứ tự: Trang bìa (Sample 3) ➔ Báo cáo tổng kết ➔ File gốc...")
    _concatenate_cover_and_user_slides(
        output_keynote_path=abs_output,
        cover_template_path=cover_template_path,
        project_name=proj_display,
        user_keynote_path=input_keynote_path,
        log_cb=log_cb
    )

    if log_cb:
        log_cb(f"🎉 Hoàn tất xuất báo cáo tổng kết Executive Keynote: {os.path.basename(abs_output)}")

    return abs_output
