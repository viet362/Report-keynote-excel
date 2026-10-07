import csv
import os
import re
from collections import defaultdict
from typing import Dict, List, Optional, Any, Set

# Pre-compiled regex patterns for performance (avoid re-compiling on every call)
_RE_DATE_YMD = re.compile(r'^\d{4}[-/]\d{1,2}[-/]\d{1,2}')
_RE_DATE_DMY = re.compile(r'^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}')
_RE_TIME_HMS = re.compile(r'\d{1,2}:\d{2}:\d{2}')
_RE_HAS_ALPHA = re.compile(r'[A-Za-z]')


def clean_int(val: Any) -> int:
    if not val:
        return 0
    s = str(val).replace(",", "").strip()
    try:
        return int(float(s))
    except ValueError:
        return 0


def clean_float(val: Any) -> float:
    if not val:
        return 0.0
    s = str(val).replace(",", "").replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def is_datetime_or_date(val: Any) -> bool:
    """
    Returns True if val is a date, time, timestamp, or purely numeric string.
    A test station name is NEVER a date or timestamp.
    """
    if not val:
        return False
    s = str(val).strip()
    if not s:
        return False
    # Date formats: YYYY-MM-DD, YYYY/MM/DD, DD/MM/YYYY, MM/DD/YYYY
    if _RE_DATE_YMD.search(s) or _RE_DATE_DMY.search(s):
        return True
    # Time formats: HH:MM:SS
    if _RE_TIME_HMS.search(s):
        return True
    # Pure numbers or float (e.g. "1,772", "1772", "0.68%")
    try:
        float(s.replace(",", "").replace("%", ""))
        return True
    except ValueError:
        pass
    return False


def parse_performance_breakdown(filepath: str) -> Dict[str, Dict[str, Any]]:
    """
    Parse Performance-Breakdown.csv, preserving station order as they appear in the file.
    Supports dynamic headers, shifted columns (e.g. date column inserted), and strips
    non-station metadata rows.
    """
    stations: Dict[str, Dict[str, Any]] = {}
    if not os.path.exists(filepath):
        return stations

    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    content = content.strip()
    # Handle trailing unclosed quote edge case
    if content.count('"') % 2 != 0:
        content += '"'

    rows = list(csv.reader(content.splitlines()))
    if not rows:
        return stations

    # Detect header row and column mapping
    header_idx = -1
    col_map = {
        "station": -1,
        "input": -1,
        "pass": -1,
        "yield": -1,
        "fail": -1,
        "fail_pct": -1,
        "retest": -1,
        "retest_pct": -1,
    }

    for idx, r in enumerate(rows[:10]):
        r_upper = [c.strip().upper() for c in r]
        if any("STATION" in c for c in r_upper) or (any("INPUT" in c for c in r_upper) and any("YIELD" in c for c in r_upper)):
            header_idx = idx
            for c_idx, c_name in enumerate(r_upper):
                if "STATION" in c_name and col_map["station"] == -1:
                    col_map["station"] = c_idx
                elif "INPUT" in c_name and col_map["input"] == -1:
                    col_map["input"] = c_idx
                elif "PASS" in c_name and col_map["pass"] == -1:
                    col_map["pass"] = c_idx
                elif "YIELD" in c_name and col_map["yield"] == -1:
                    col_map["yield"] = c_idx
                elif "FAIL" in c_name:
                    if "%" in c_name and col_map["fail_pct"] == -1:
                        col_map["fail_pct"] = c_idx
                    elif "%" not in c_name and col_map["fail"] == -1:
                        col_map["fail"] = c_idx
                elif "RETEST" in c_name:
                    if "%" in c_name and col_map["retest_pct"] == -1:
                        col_map["retest_pct"] = c_idx
                    elif "%" not in c_name and col_map["retest"] == -1:
                        col_map["retest"] = c_idx
            break

    start_row = header_idx + 1 if header_idx != -1 else 0

    st_col = col_map["station"] if col_map["station"] != -1 else 1
    inp_col = col_map["input"] if col_map["input"] != -1 else 2
    pass_col = col_map["pass"] if col_map["pass"] != -1 else 3
    yield_col = col_map["yield"] if col_map["yield"] != -1 else 4
    fail_col = col_map["fail"] if col_map["fail"] != -1 else 5
    fail_pct_col = col_map["fail_pct"] if col_map["fail_pct"] != -1 else 6
    retest_col = col_map["retest"] if col_map["retest"] != -1 else 7
    retest_pct_col = col_map["retest_pct"] if col_map["retest_pct"] != -1 else 8

    for row in rows[start_row:]:
        if not row or len(row) < 3:
            continue

        st_name = row[st_col].strip() if len(row) > st_col else ""

        # If candidate station name is a date/time or empty, look for the real station name in other columns (0, 1, 2, 3)
        if not st_name or is_datetime_or_date(st_name):
            for cand_idx in range(min(5, len(row))):
                cand = row[cand_idx].strip()
                if cand and not is_datetime_or_date(cand) and _RE_HAS_ALPHA.search(cand):
                    st_name = cand
                    break

        if not st_name or is_datetime_or_date(st_name):
            continue

        st_upper = st_name.upper()
        # Skip header rows and category rows
        if st_upper in ("STATION TYPE", "STATION NAME", "STATION", "FATP", "SMT", "NOT DEFINED"):
            continue
        if "STAGE" in st_upper or "NOT IN PSSO" in st_upper or st_name.startswith("Performance"):
            continue

        inp = clean_int(row[inp_col]) if len(row) > inp_col else 0
        pass_cnt = clean_int(row[pass_col]) if len(row) > pass_col else 0
        y_val = row[yield_col] if len(row) > yield_col else ""
        yield_pct = clean_float(y_val) / 100.0 if "%" in str(y_val) else clean_float(y_val)
        fail_cnt = clean_int(row[fail_col]) if len(row) > fail_col else 0
        f_val = row[fail_pct_col] if len(row) > fail_pct_col else ""
        fail_pct = clean_float(f_val) / 100.0 if "%" in str(f_val) else clean_float(f_val)
        retest_cnt = clean_int(row[retest_col]) if len(row) > retest_col else 0
        r_val = row[retest_pct_col] if len(row) > retest_pct_col else ""
        retest_pct = clean_float(r_val) / 100.0 if "%" in str(r_val) else clean_float(r_val)

        stations[st_name] = {
            "input": inp,
            "pass": pass_cnt,
            "yield": yield_pct,
            "fail": fail_cnt,
            "fail_pct": fail_pct,
            "retest": retest_cnt,
            "retest_pct": retest_pct
        }

    return stations


COMMON_BASE_SUBTESTS = {
    "Info", "Status", "SensorData", "CapAccuracyError", "CapCalibrationFactor",
    "State", "Transition", "StationHealth", "ConnectivityTest", "Bluetooth",
    "PowerCheck", "UOPCheck", "OpenShortTest", "PostProcessing", "FinishProcessControl"
}


def _clean_test_and_sub(t: str, sub_t: str, known_subs: Optional[set] = None) -> tuple[str, str]:
    """
    Cleans up factory test naming quirks:
    - Removes internal ':subsubtc=...' prefixes/suffixes (e.g. from RF station logs).
    - Normalizes sub-tests where sub-sub-tests were concatenated with '_' (e.g. 'CapAccuracyError_Error45TiltTest...').
    """
    if ":subsubtc=" in t:
        t = t.split(":subsubtc=")[0].strip()
    if ":subsubtc=" in sub_t:
        sub_t = sub_t.split(":subsubtc=")[0].strip()

    if known_subs:
        for b in sorted(known_subs, key=len):
            if sub_t != b and (sub_t.startswith(b + "_") or sub_t.startswith(b + "-")):
                return t, b

    prefix = sub_t.split("_")[0]
    if prefix in COMMON_BASE_SUBTESTS:
        return t, prefix

    return t, sub_t


def parse_retest_symptoms(
    filepath: str,
    grouping_level: str = "3_levels",
    include_sub_sub: Optional[bool] = None,
    out_known_subs: Optional[Dict[str, Dict[str, set]]] = None
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Parse Retest-Symptoms.csv.
    - grouping_level == "3_levels": Test/Sub-Test/Sub-Sub-Test (default).
    - grouping_level == "2_levels": Test/Sub-Test (omits Sub-Sub-Test), aggregating counts.
    - grouping_level == "1_level": Test (Test only, omits Sub-Test & Sub-Sub-Test), aggregating counts.
    """
    if include_sub_sub is not None:
        grouping_level = "3_levels" if include_sub_sub else "2_levels"

    station_issues: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    if not os.path.exists(filepath):
        return station_issues

    raw_rows = []
    station_known_subs: Dict[str, Dict[str, set]] = defaultdict(lambda: defaultdict(set))

    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        reader = csv.reader(f)
        try:
            first_line = next(reader)
            if "Retest Count" not in first_line:
                headers = next(reader)
            else:
                headers = first_line
        except StopIteration:
            return station_issues

        h_upper = [str(h).strip().upper() for h in headers]
        col_cnt = -1
        col_rr = -1
        col_t = -1
        col_sub_t = -1
        col_sub_sub_t = -1
        col_st = -1
        col_total = -1

        for c_idx, h in enumerate(h_upper):
            if "COUNT" in h or ("RETEST" in h and ("#" in h or "QTY" in h or "%" not in h)):
                if col_cnt == -1: col_cnt = c_idx
            elif "%" in h or "RATE" in h:
                if col_rr == -1: col_rr = c_idx
            elif "SUB-SUB" in h or "SUBSUB" in h:
                if col_sub_sub_t == -1: col_sub_sub_t = c_idx
            elif "SUB" in h and "SUB-SUB" not in h and "SUBSUB" not in h:
                if col_sub_t == -1: col_sub_t = c_idx
            elif "TEST" in h and "SUB" not in h and "RETEST" not in h and "STATION" not in h:
                if col_t == -1: col_t = c_idx
            elif "STATION" in h:
                if col_st == -1: col_st = c_idx
            elif "TOTAL" in h or "INPUT" in h:
                if col_total == -1: col_total = c_idx

        # Defaults
        col_cnt = col_cnt if col_cnt != -1 else 0
        col_rr = col_rr if col_rr != -1 else 1
        col_t = col_t if col_t != -1 else 2
        col_sub_t = col_sub_t if col_sub_t != -1 else 3
        col_sub_sub_t = col_sub_sub_t if col_sub_sub_t != -1 else 4
        col_st = col_st if col_st != -1 else 5
        col_total = col_total if col_total != -1 else 6

        for row in reader:
            if not row or len(row) < 3:
                continue
            cnt = clean_int(row[col_cnt]) if len(row) > col_cnt else 0
            rr_str = row[col_rr].strip() if len(row) > col_rr else ""
            t = row[col_t].strip() if len(row) > col_t else ""
            sub_t = row[col_sub_t].strip() if len(row) > col_sub_t else ""
            sub_sub_t = row[col_sub_sub_t].strip() if len(row) > col_sub_sub_t else ""
            st_name = row[col_st].strip() if len(row) > col_st else ""
            total = clean_int(row[col_total]) if len(row) > col_total else 0

            # If st_name is a date/time or empty, look for station name in other columns
            if not st_name or is_datetime_or_date(st_name):
                for cand_c in range(len(row)):
                    cand = row[cand_c].strip()
                    if cand and not is_datetime_or_date(cand) and _RE_HAS_ALPHA.search(cand):
                        if cand_c not in (col_t, col_sub_t, col_sub_sub_t):
                            st_name = cand
                            break

            if not st_name or is_datetime_or_date(st_name):
                continue

            raw_rows.append((cnt, rr_str, t, sub_t, sub_sub_t, st_name, total))
            if t and sub_t:
                station_known_subs[st_name][t].add(sub_t)

    if out_known_subs is not None:
        for st_k, t_map in station_known_subs.items():
            for t_k, subs in t_map.items():
                out_known_subs[st_k][t_k].update(subs)

    raw_items_by_station: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)

    for cnt, rr_str, t, sub_t, sub_sub_t, st_name, total in raw_rows:
        try:
            if grouping_level == "1_level":
                clean_t = t.split(":subsubtc=")[0].strip() if ":subsubtc=" in t else t
                parts = [clean_t] if clean_t else []
                issue_name = "/".join(parts) if parts else "Unknown"
                is_aggregated = True
                norm_t, norm_sub = clean_t, ""
            elif grouping_level == "2_levels":
                clean_t, clean_sub = _clean_test_and_sub(
                    t, sub_t, station_known_subs[st_name].get(t, set())
                )
                parts = [p for p in [clean_t, clean_sub] if p]
                issue_name = "/".join(parts) if parts else "Unknown"
                is_aggregated = True
                norm_t, norm_sub = clean_t, clean_sub
            else:
                parts = [p for p in [t, sub_t, sub_sub_t] if p]
                issue_name = "/".join(parts) if parts else "Unknown"
                is_aggregated = False
                norm_t, norm_sub = t, sub_t

            if not is_aggregated:
                rate = (cnt / total) if total > 0 else (clean_float(rr_str) / 100.0)
                station_issues[st_name].append({
                    "issue_name": issue_name,
                    "test": t,
                    "sub_test": sub_t,
                    "sub_sub_test": sub_sub_t,
                    "item_qty": cnt,
                    "item_rr": rate,
                    "total_unit_count": total
                })
            else:
                if issue_name not in raw_items_by_station[st_name]:
                    raw_items_by_station[st_name][issue_name] = {
                        "issue_name": issue_name,
                        "test": norm_t,
                        "sub_test": norm_sub,
                        "sub_sub_test": "",
                        "item_qty": cnt,
                        "total_unit_count": total
                    }
                else:
                    raw_items_by_station[st_name][issue_name]["item_qty"] += cnt
                    if total > raw_items_by_station[st_name][issue_name]["total_unit_count"]:
                        raw_items_by_station[st_name][issue_name]["total_unit_count"] = total
        except Exception:
            continue

    if grouping_level in ("1_level", "2_levels"):
        for st_name, issues_map in raw_items_by_station.items():
            for iss_name, data in issues_map.items():
                tot = data["total_unit_count"]
                rate = (data["item_qty"] / tot) if tot > 0 else 0.0
                station_issues[st_name].append({
                    "issue_name": iss_name,
                    "test": data["test"],
                    "sub_test": data["sub_test"],
                    "sub_sub_test": "",
                    "item_qty": data["item_qty"],
                    "item_rr": rate,
                    "total_unit_count": tot
                })

    # Sort each station's issues by count descending (Pareto)
    for st in station_issues:
        station_issues[st].sort(key=lambda x: x["item_qty"], reverse=True)

    return station_issues


def parse_unit_test_details(
    filepath: Optional[str],
    grouping_level: str = "3_levels",
    include_sub_sub: Optional[bool] = None,
    station_known_subs: Optional[Dict[str, Dict[str, set]]] = None
) -> Dict[str, Dict[str, List[str]]]:
    if include_sub_sub is not None:
        grouping_level = "3_levels" if include_sub_sub else "2_levels"

    # Use sets internally for O(1) dedup, convert to list at the end
    sn_set_map: Dict[str, Dict[str, Set[str]]] = defaultdict(lambda: defaultdict(set))
    if not filepath or not os.path.exists(filepath):
        return defaultdict(lambda: defaultdict(list))

    # Resolve sub-test field name once (handles CSV column naming variants)
    _SUBTEST_KEYS = ("Sub-test", "Sub-Test", "Sub Test", "sub_test")
    _SUBSUBTEST_KEYS = ("Sub-sub-test", "Sub-Sub-Test", "Sub Sub Test", "sub_sub_test")

    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return defaultdict(lambda: defaultdict(list))

        fieldnames_set = set(reader.fieldnames)
        sub_t_key = next((k for k in _SUBTEST_KEYS if k in fieldnames_set), None)
        sub_sub_t_key = next((k for k in _SUBSUBTEST_KEYS if k in fieldnames_set), None)

        for row in reader:
            try:
                res = (row.get("Test Result") or "").strip()
                if res and res != "RETEST":
                    continue

                sn = (row.get("Serial Number") or "").strip()
                if not sn:
                    continue

                st_name = ""
                for k in ("Station Name", "Station Type", "Station", "Station ID"):
                    val = (row.get(k) or "").strip()
                    if val and not is_datetime_or_date(val):
                        st_name = val
                        break

                if not st_name or is_datetime_or_date(st_name):
                    continue

                t = (row.get("Test") or "").strip()
                sub_t = (row.get(sub_t_key) or "").strip() if sub_t_key else ""
                sub_sub_t = (row.get(sub_sub_t_key) or "").strip() if sub_sub_t_key else ""

                if grouping_level == "1_level":
                    clean_t = t.split(":subsubtc=")[0].strip() if ":subsubtc=" in t else t
                    parts = [clean_t] if clean_t else []
                elif grouping_level == "2_levels":
                    known = station_known_subs.get(st_name, {}).get(t, set()) if station_known_subs else None
                    clean_t, clean_sub = _clean_test_and_sub(t, sub_t, known)
                    parts = [p for p in [clean_t, clean_sub] if p]
                else:
                    parts = [p for p in [t, sub_t, sub_sub_t] if p]
                issue_name = "/".join(parts) if parts else "Unknown"

                sn_set_map[st_name][issue_name].add(sn)
            except Exception as e:
                print(f"[data_processor] Skipping malformed unitTestDetails row: {e}")
                continue

    # Convert sets -> sorted lists for deterministic output
    result: Dict[str, Dict[str, List[str]]] = defaultdict(lambda: defaultdict(list))
    for st, issue_map in sn_set_map.items():
        for issue, sn_set in issue_map.items():
            result[st][issue] = sorted(sn_set)
    return result


def build_report_data(
    perf_file: str,
    symptoms_file: str,
    unit_details_file: Optional[str] = None,
    product_name: str = "Ruby",
    grouping_level: str = "3_levels",
    include_sub_sub: Optional[bool] = None,
    top_n: Optional[int] = 5
) -> Dict[str, Any]:
    """
    Build the full report data.
    Station order follows the exact order in Performance-Breakdown.csv.
    Stations in Retest-Symptoms.csv but NOT in Performance-Breakdown.csv are appended at the end.
    top_n: Max number of top issues per station (default 5, None for all).
    grouping_level options:
      - '3_levels': Test + Sub-test + Sub-sub-test (default)
      - '2_levels': Test + Sub-test (omits Sub-sub-test, sums item quantities)
      - '1_level': Test only (omits Sub-test and Sub-sub-test, sums item quantities)
    """
    if include_sub_sub is not None:
        grouping_level = "3_levels" if include_sub_sub else "2_levels"

    perf_data = parse_performance_breakdown(perf_file)
    known_subs: Dict[str, Dict[str, set]] = defaultdict(lambda: defaultdict(set))
    symptoms_data = parse_retest_symptoms(symptoms_file, grouping_level=grouping_level, out_known_subs=known_subs)
    sn_data = parse_unit_test_details(unit_details_file, grouping_level=grouping_level, station_known_subs=known_subs)

    # Build ordered station list: perf file order first, then any extra from symptoms
    # Strictly filter out any timestamp/datetime entries
    ordered_stations: List[str] = [st for st in perf_data.keys() if st and not is_datetime_or_date(st)]
    for st in symptoms_data.keys():
        if st and not is_datetime_or_date(st) and st not in ordered_stations:
            ordered_stations.append(st)

    report_stations = []
    for idx, st_name in enumerate(ordered_stations, start=1):
        perf = perf_data.get(st_name, {
            "input": 0,
            "pass": 0,
            "yield": 0.0,
            "fail": 0,
            "fail_pct": 0.0,
            "retest": 0,
            "retest_pct": 0.0
        })

        st_issues = symptoms_data.get(st_name, [])
        if top_n is not None and top_n > 0:
            st_issues = st_issues[:top_n]
        station_sn_map = sn_data.get(st_name, {})

        input_cnt = perf["input"]
        pass_cnt = perf["pass"]
        yield_pct = perf["yield"]
        fail_cnt = perf["fail"]
        fail_pct = perf["fail_pct"]
        retest_cnt = perf["retest"]
        retest_pct = perf["retest_pct"]

        # If station not in performance breakdown (or input is 0) but has failure symptoms
        if input_cnt == 0 and st_issues:
            input_cnt = st_issues[0].get("total_unit_count", 0)
            retest_cnt = sum(iss.get("item_qty", 0) for iss in st_issues)
            fail_cnt = 0
            pass_cnt = max(0, input_cnt - fail_cnt)
            yield_pct = (pass_cnt / input_cnt) if input_cnt > 0 else 1.0
            retest_pct = (retest_cnt / input_cnt) if input_cnt > 0 else 0.0

        formatted_issues = []
        for iss in st_issues:
            iss_name = iss["issue_name"]
            qty = iss["item_qty"]
            rate = (qty / input_cnt) if input_cnt > 0 else iss["item_rr"]
            rate_rounded = round(rate, 4)

            sns = station_sn_map.get(iss_name, [])
            sn_str = "\n".join(sns) + ("\n" if sns else "")

            rr_pct_str = f"{rate_rounded * 100:.2f}%"
            rr_symptom_str = f"{qty} x {rr_pct_str} - {iss_name}"

            formatted_issues.append({
                "issue_name": iss_name,
                "item_qty": qty,
                "item_rr": rate_rounded,
                "sn_str": sn_str,
                "rr_symptom": rr_symptom_str
            })

        report_stations.append({
            "no": idx,
            "product": product_name,
            "station": st_name,
            "input": input_cnt,
            "pass": pass_cnt,
            "yield": yield_pct,
            "fail": fail_cnt,
            "fail_pct": fail_pct,
            "retest": retest_cnt,
            "retest_pct": retest_pct,
            "issues": formatted_issues
        })

    return {
        "product_name": product_name,
        "stations": report_stations,
        "has_unit_details": bool(sn_data),
        "_sn_data": dict(sn_data),   # raw station→issue→[SNs] map for dedup counting
    }
