import os
import math
import subprocess
import shutil
import tempfile
import zipfile
import uuid
from typing import Dict, List, Any, Optional

from keynote_parser import codec
from keynote_parser.versions.v14_5.generated import TSCHArchives_pb2
from src.data_processor import is_datetime_or_date

# Max issue rows that fit on a single slide
MAX_ISSUES_PRIMARY = 5
MAX_ISSUES_OVERFLOW = 10


def _sanitize_for_applescript(text: str) -> str:
    """Escape/sanitize a string for safe embedding inside AppleScript double-quoted literals."""
    # Replace backslash first, then double-quotes
    text = text.replace("\\", "\\\\")
    text = text.replace('"', '\\"')
    # Remove control characters that break AppleScript
    text = "".join(c for c in text if ord(c) >= 32 or c in "\t")
    return text


def _run_applescript(script: str) -> str:
    """Run an AppleScript and return stdout. Raises RuntimeError on failure."""
    proc = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True
    )
    if proc.returncode != 0:
        raise RuntimeError(f"AppleScript failed: {proc.stderr}\nOutput: {proc.stdout}")
    return proc.stdout.strip()


def compute_chart_dynamic_max_and_gridlines(max_val: float) -> tuple[float, int]:
    """
    Computes a clean, human-readable Y-axis maximum and number of major gridlines
    that fits the data with comfortable headroom (15%-30%), ensuring both Y-axes
    are synchronized and have identical scales.
    """
    if max_val <= 0.004:
        return 0.005, 1  # 0.0%, 0.5%
    elif max_val <= 0.008:
        return 0.010, 2  # 0.0%, 0.5%, 1.0%
    elif max_val <= 0.012:
        return 0.015, 3  # 0.0%, 0.5%, 1.0%, 1.5%
    elif max_val <= 0.017:
        return 0.020, 2  # 0.0%, 1.0%, 2.0%
    elif max_val <= 0.022:
        return 0.025, 5  # 0.0%, 0.5%, 1.0%, 1.5%, 2.0%, 2.5%
    elif max_val <= 0.027:
        return 0.030, 3  # 0.0%, 1.0%, 2.0%, 3.0%
    elif max_val <= 0.035:
        return 0.040, 4  # 0.0%, 1.0%, 2.0%, 3.0%, 4.0%
    elif max_val <= 0.045:
        return 0.050, 5  # 0.0%, 1.0%, ..., 5.0%
    elif max_val <= 0.055:
        return 0.060, 3  # 0.0%, 2.0%, 4.0%, 6.0%
    elif max_val <= 0.070:
        return 0.080, 4  # 0.0%, 2.0%, ..., 8.0%
    elif max_val <= 0.090:
        return 0.100, 5  # 0.0%, 2.0%, ..., 10.0%
    else:
        m = round(math.ceil(max_val * 1.25 * 50) / 50, 3)
        steps = max(2, min(6, int(round(m * 50))))
        return m, steps


def update_slide_charts(
    output_path: str,
    stations_payload: List[Dict[str, Any]],
    target_mp_rate: float,
    chart_items_limit: Optional[int] = 5
):
    """
    Updates the 2-Axis Combination Chart in each primary slide via protobuf IWA data grid.
    Dynamically resizes grid rows to accommodate Top 5, All, or custom N failure items.
    Also updates the Y-axis maximum in ObjectContainer.iwa so all points and bars fit cleanly.
    Overflow slides are skipped (they have no chart).
    """
    with zipfile.ZipFile(output_path, "r") as zin:
        file_map = {item.filename: zin.read(item.filename) for item in zin.infolist()}

    doc_data = file_map.get("Index/Document.iwa")
    if not doc_data:
        return

    doc_iwa = codec.IWAFile.from_buffer(doc_data, "Index/Document.iwa")

    slide_node_ids = []
    for chunk in doc_iwa.chunks:
        for archive in chunk.archives:
            if archive.header.message_infos[0].type == 2:
                obj = archive.objects[0]
                if obj.HasField("slideTree"):
                    for s_ref in obj.slideTree.slides:
                        slide_node_ids.append(s_ref.identifier)

    slide_ids = []
    # Build a flat archive id -> slide_id map for O(1) lookup (avoids O(N²) nested loop)
    archive_id_map: Dict[int, Any] = {}
    for chunk in doc_iwa.chunks:
        for archive in chunk.archives:
            archive_id_map[archive.header.identifier] = archive

    for s_node_id in slide_node_ids:
        arc = archive_id_map.get(s_node_id)
        if arc is not None:
            slide_obj = arc.objects[0]
            if slide_obj.HasField("slide"):
                slide_ids.append(slide_obj.slide.identifier)

    slide_file_names = []
    if slide_ids:
        for s_id in slide_ids:
            candidate1 = f"Index/Slide-{s_id}.iwa"
            candidate2 = "Index/Slide.iwa"
            if candidate1 in file_map:
                slide_file_names.append(candidate1)
            elif candidate2 in file_map and candidate2 not in slide_file_names:
                slide_file_names.append(candidate2)
    else:
        slide_file_names = [f for f in sorted(file_map.keys()) if "Slide" in f and "Template" not in f]

    # Filter out any leftover template slides (e.g. containing 'Station-name')
    slide_file_names = [
        sf for sf in slide_file_names
        if b"Station-name" not in file_map.get(sf, b"") and b"Retest breakdown_Station-name" not in file_map.get(sf, b"")
    ]

    # Map slide index -> station index (primary slides only)
    slide_to_station: Dict[int, int] = {}
    slide_idx = 0
    for st_idx, st_info in enumerate(stations_payload):
        slide_to_station[slide_idx] = st_idx
        slide_idx += 1 + st_info.get("num_overflow_slides", 0)

    # Track nonstyle_id -> (dynamic_max, major_gridlines) for ObjectContainer.iwa update
    axis_scaling_map: Dict[int, tuple[float, int]] = {}

    for s_idx, slide_file in enumerate(slide_file_names):
        # Priority 1: Match by station title marker inside slide bytes
        st_info = None
        sf_bytes = file_map.get(slide_file, b"")
        for candidate in stations_payload:
            marker = f"Retest breakdown_{candidate['station']}".encode("utf-8")
            if marker in sf_bytes:
                st_info = candidate
                break

        # Priority 2: Fall back to index-based mapping
        if st_info is None:
            if s_idx not in slide_to_station:
                continue
            st_idx = slide_to_station[s_idx]
            if st_idx >= len(stations_payload):
                break
            st_info = stations_payload[st_idx]

        station_rate = st_info["retest_rate"]
        all_issues = st_info["issues"]

        if chart_items_limit is None or chart_items_limit <= 0:
            chart_issues = all_issues
        else:
            chart_issues = all_issues[:chart_items_limit]

        num_chart_issues = len(chart_issues)
        # Row 0: Station rate
        # Rows 1..num_chart_issues: Issue items
        # Row num_chart_issues + 1: Final empty point for Target line
        target_num_rows = max(3, num_chart_issues + 2)

        slide_data = file_map[slide_file]
        slide_iwa = codec.IWAFile.from_buffer(slide_data, slide_file)

        chart_updated = False
        for chunk in slide_iwa.chunks:
            for archive in chunk.archives:
                if 5021 in [m.type for m in archive.header.message_infos]:
                    obj = archive.objects[0]
                    unity = obj.Extensions[TSCHArchives_pb2.ChartArchive.unity]
                    grid = unity.grid

                    # Expand rows if target_num_rows > current
                    while len(grid.grid_row) < target_num_rows:
                        r_idx = len(grid.grid_row)
                        new_r = grid.grid_row.add()
                        for _ in range(6):
                            new_r.value.add()
                        grid.row_name.append("")
                        new_id = grid.idMap.row_id_map.add()
                        new_id.uniqueId = str(uuid.uuid4()).upper()
                        new_id.index = r_idx

                    # Shrink rows if target_num_rows < current
                    while len(grid.grid_row) > target_num_rows:
                        del grid.grid_row[-1]
                        del grid.row_name[-1]
                        del grid.idMap.row_id_map[-1]

                    # Re-index row_id_map entries for consistency
                    for idx, entry in enumerate(grid.idMap.row_id_map):
                        entry.index = idx

                    # Row 0: Station Retest Rate (Red line point 0)
                    grid.row_name[0] = ""
                    if len(grid.grid_row[0].value) > 0:
                        grid.grid_row[0].value[0].numeric_value = round(station_rate, 4)
                    if len(grid.grid_row[0].value) > 2:
                        grid.grid_row[0].value[2].numeric_value = 0.0
                    if len(grid.grid_row[0].value) > 5:
                        grid.grid_row[0].value[5].numeric_value = round(target_mp_rate, 4)

                    # Rows 1..num_chart_issues: Issue rates & names
                    for i_offset, iss in enumerate(chart_issues):
                        row_idx = 1 + i_offset
                        grid.row_name[row_idx] = iss["name"]
                        iss_rate = round(iss["rr"], 4)
                        if len(grid.grid_row[row_idx].value) > 0:
                            grid.grid_row[row_idx].value[0].numeric_value = iss_rate
                        if len(grid.grid_row[row_idx].value) > 2:
                            grid.grid_row[row_idx].value[2].numeric_value = iss_rate
                        if len(grid.grid_row[row_idx].value) > 5:
                            grid.grid_row[row_idx].value[5].numeric_value = round(target_mp_rate, 4)

                    # Last row (target_num_rows - 1): Target line end point
                    last_row_idx = target_num_rows - 1
                    grid.row_name[last_row_idx] = ""
                    if len(grid.grid_row[last_row_idx].value) > 0:
                        grid.grid_row[last_row_idx].value[0].ClearField("numeric_value")
                    if len(grid.grid_row[last_row_idx].value) > 2:
                        grid.grid_row[last_row_idx].value[2].ClearField("numeric_value")
                    if len(grid.grid_row[last_row_idx].value) > 5:
                        grid.grid_row[last_row_idx].value[5].numeric_value = round(target_mp_rate, 4)

                    # Dynamic Y-axis scaling customized to station data (with headroom and clean intervals)
                    chart_rates = [iss["rr"] for iss in chart_issues]
                    max_val = max([station_rate, target_mp_rate] + chart_rates) if chart_rates else max(station_rate, target_mp_rate)
                    dynamic_max, major_gridlines = compute_chart_dynamic_max_and_gridlines(max_val)

                    # Synchronize BOTH vertical axes (Left Y-axis & Right Y-axis) with identical scale
                    for nonstyle_ref in unity.value_axis_nonstyles:
                        axis_scaling_map[nonstyle_ref.identifier] = (dynamic_max, major_gridlines)

                    chart_updated = True

        if chart_updated:
            file_map[slide_file] = slide_iwa.to_buffer()

    # Update value axis usermax & majorgridlines in ObjectContainer.iwa
    if axis_scaling_map and "Index/ObjectContainer.iwa" in file_map:
        oc_data = file_map["Index/ObjectContainer.iwa"]
        oc_iwa = codec.IWAFile.from_buffer(oc_data, "Index/ObjectContainer.iwa")
        oc_updated = False
        for chunk in oc_iwa.chunks:
            for archive in chunk.archives:
                if archive.header.identifier in axis_scaling_map:
                    target_max, target_gridlines = axis_scaling_map[archive.header.identifier]
                    obj = archive.objects[0]
                    for f_desc, val in obj.ListFields():
                        if f_desc.name == "current":
                            has_max = False
                            for cf, cv in val.ListFields():
                                if cf.name == "tschchartaxisdefaultusermax":
                                    cv.number_archive = target_max
                                    has_max = True
                                    oc_updated = True
                                elif cf.name == "tschchartaxisvaluenumberofmajorgridlines":
                                    setattr(val, cf.name, target_gridlines)
                                    oc_updated = True
                            if not has_max:
                                val.tschchartaxisdefaultusermax.number_archive = target_max
                                setattr(val, "tschchartaxisvaluenumberofmajorgridlines", target_gridlines)
                                oc_updated = True
        if oc_updated:
            file_map["Index/ObjectContainer.iwa"] = oc_iwa.to_buffer()

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_STORED) as zout:
        for fname, content in file_map.items():
            zout.writestr(fname, content)


def _chunk_issues(issues: List[Dict], max_primary: int = MAX_ISSUES_PRIMARY, max_overflow: int = MAX_ISSUES_OVERFLOW) -> List[List[Dict]]:
    """Split issues list into chunks: top 5 on primary slide, subsequent in groups of 10 on overflow slides."""
    if not issues:
        return [[]]
    chunks = [issues[:max_primary]]
    rem = issues[max_primary:]
    if rem:
        for i in range(0, len(rem), max_overflow):
            chunks.append(rem[i:i + max_overflow])
    return chunks


def _build_primary_slide_script(
    doc_var: str,
    base_slide_var: str,
    product_name: str,
    p_len: int,
    st_info: Dict[str, Any],
    target_mp_rate: float,
    first_chunk: List[Dict]
) -> str:
    """Build AppleScript snippet for a single primary station slide."""
    st_name = _sanitize_for_applescript(st_info["station"])
    if is_datetime_or_date(st_name):
        st_name = "Station"
    inp = st_info["input"]
    fail = st_info["fail"]
    retest = st_info["retest"]
    rate = st_info["retest_rate"]  # kept for potential future use by callers

    rest_title = f" | Retest breakdown_{st_name}"
    full_title = _sanitize_for_applescript(f"{product_name}{rest_title}")
    full_len = len(full_title)
    needed_rows = max(1, len(first_chunk)) + 1

    lines = [
        f'tell {doc_var}',
        '    duplicate slide 1',
        '    set newSlide to last slide',
        'end tell',
        'tell newSlide',
        f'    set object text of text item 6 to "{full_title}"',
        '    tell object text of text item 6',
        f'        set font of characters 1 thru {p_len} to "Helvetica-Bold"',
        f'        set color of characters 1 thru {p_len} to {{0, 38656, 65535}}',
        f'        set font of characters {p_len + 1} thru {full_len} to "Helvetica-Light"',
        f'        set color of characters {p_len + 1} thru {full_len} to {{24248, 24248, 24248}}',
        '    end tell',
        '    set t1 to table 1',
        f'    set value of cell 1 of row 2 of t1 to "{st_name}"',
        f'    set value of cell 2 of row 2 of t1 to {inp}',
        f'    set value of cell 3 of row 2 of t1 to {fail}',
        f'    set value of cell 4 of row 2 of t1 to {retest}',
        # Cells 5 (Actual Yield =(B2−C2)÷B2) and 6 (Retest Rate =D2÷B2) are native formulas in slide 1
        # Do NOT overwrite their values so Keynote automatically calculates them dynamically
        f'    set value of cell 7 of row 2 of t1 to {target_mp_rate}',
        # Let Keynote native conditional highlighting rules format cell 6 dynamically (3 tiers: Yellow, Orange, Coral)
    ]

    lines.extend([
        '    set t2 to table 2',
        f'    repeat while (count of rows of t2) < {needed_rows}',
        '        tell t2 to make new row at end of rows',
        '    end repeat',
        f'    repeat while (count of rows of t2) > {needed_rows}',
        '        delete last row of t2',
        '    end repeat',
    ])

    for i_idx, iss in enumerate(first_chunk, start=2):
        iss_name = _sanitize_for_applescript(iss["name"])
        iss_rr = round(iss["rr"], 4)
        iss_ratio = _sanitize_for_applescript(iss["ratio"])
        lines.extend([
            f'    set value of cell 2 of row {i_idx} of t2 to "{iss_name}"',
            f'    set value of cell 3 of row {i_idx} of t2 to {iss_rr}',
            f'    set value of cell 4 of row {i_idx} of t2 to "{iss_ratio}"',
            f'    set value of cell 5 of row {i_idx} of t2 to ""',
            f'    set value of cell 6 of row {i_idx} of t2 to ""',
            f'    set value of cell 7 of row {i_idx} of t2 to "/"',
            f'    set value of cell 8 of row {i_idx} of t2 to ""',
            f'    set value of cell 9 of row {i_idx} of t2 to ""',
        ])

    lines.append('end tell')
    return "\n".join(lines)


def _build_overflow_slide_script(
    doc_var: str,
    base_slide_var: str,
    product_name: str,
    p_len: int,
    cont_title: str,
    chunk: List[Dict]
) -> str:
    """Build AppleScript snippet for a single overflow slide."""
    safe_cont = _sanitize_for_applescript(cont_title)
    cont_len = len(safe_cont)
    needed_rows_ov = max(1, len(chunk)) + 1

    lines = [
        f'tell {doc_var}',
        '    duplicate slide 1',
        '    set ovSlide to last slide',
        'end tell',
        'tell ovSlide',
        f'    set object text of text item 6 to "{safe_cont}"',
        '    tell object text of text item 6',
        f'        set font of characters 1 thru {p_len} to "Helvetica-Bold"',
        f'        set color of characters 1 thru {p_len} to {{0, 38656, 65535}}',
        f'        set font of characters {p_len + 1} thru {cont_len} to "Helvetica-Light"',
        f'        set color of characters {p_len + 1} thru {cont_len} to {{24248, 24248, 24248}}',
        '    end tell',
        '    if (count of charts) > 0 then',
        '        delete chart 1',
        '    end if',
        '    if (count of tables) > 1 then',
        '        delete table 1',
        '    end if',
        '    set ovT2 to table 1',
        '    set position of ovT2 to {50, 140}',
        f'    repeat while (count of rows of ovT2) < {needed_rows_ov}',
        '        tell ovT2 to make new row at end of rows',
        '    end repeat',
        f'    repeat while (count of rows of ovT2) > {needed_rows_ov}',
        '        delete last row of ovT2',
        '    end repeat',
    ]

    for i_idx, iss in enumerate(chunk, start=2):
        iss_name = _sanitize_for_applescript(iss["name"])
        iss_rr = round(iss["rr"], 4)
        iss_ratio = _sanitize_for_applescript(iss["ratio"])
        lines.extend([
            f'    set value of cell 2 of row {i_idx} of ovT2 to "{iss_name}"',
            f'    set value of cell 3 of row {i_idx} of ovT2 to {iss_rr}',
            f'    set value of cell 4 of row {i_idx} of ovT2 to "{iss_ratio}"',
            f'    set value of cell 5 of row {i_idx} of ovT2 to ""',
            f'    set value of cell 6 of row {i_idx} of ovT2 to ""',
            f'    set value of cell 7 of row {i_idx} of ovT2 to "/"',
            f'    set value of cell 8 of row {i_idx} of ovT2 to ""',
            f'    set value of cell 9 of row {i_idx} of ovT2 to ""',
        ])

    lines.append('end tell')
    return "\n".join(lines)


def prepare_keynote_payload(
    report_data: Dict[str, Any],
    selected_stations: Optional[List[str]] = None,
    table_items_limit: Optional[int] = None,
    chart_items_limit: Optional[int] = 5,
    only_active: bool = True
) -> Dict[str, Any]:
    """
    Pure compute phase: filters stations, builds all table/chart payloads in memory.
    No file I/O is performed. Returns a dict ready to be passed to _write_keynote_file().
    """
    raw_prod = report_data.get("product_name", "Ruby")
    product_name = raw_prod.strip().strip("[]").strip() or "Ruby"
    p_len = len(product_name)

    stations_to_process = []
    for st in report_data.get("stations", []):
        st_name = st["station"]
        if not st_name or is_datetime_or_date(st_name) or not st.get("issues"):
            continue
        if only_active and not selected_stations and st.get("input", 0) <= 0:
            continue
        if selected_stations and st_name not in selected_stations:
            continue
        stations_to_process.append(st)

    if not stations_to_process:
        stations_to_process = [
            st for st in report_data.get("stations", [])
            if not is_datetime_or_date(st.get("station", "")) and st.get("issues")
        ]
        if not stations_to_process and report_data.get("stations"):
            for candidate in report_data["stations"]:
                if not is_datetime_or_date(candidate.get("station", "")):
                    stations_to_process = [candidate]
                    break

    stations_payload = []
    for st in stations_to_process:
        st_name = st["station"]
        inp = st.get("input", 0)
        all_issues = st.get("issues", [])

        table_issues = all_issues[:table_items_limit] if (table_items_limit and table_items_limit > 0) else all_issues

        table_payload = [
            {"name": iss.get("issue_name", ""), "rr": iss.get("item_rr", 0.0),
             "ratio": f"{iss.get('item_qty', 0)}R/{inp}T" if inp > 0 else f"{iss.get('item_qty', 0)}R"}
            for iss in table_issues
        ]
        chart_payload = [
            {"name": iss.get("issue_name", ""), "rr": iss.get("item_rr", 0.0),
             "ratio": f"{iss.get('item_qty', 0)}R/{inp}T" if inp > 0 else f"{iss.get('item_qty', 0)}R"}
            for iss in all_issues
        ]

        chunks = _chunk_issues(table_payload)
        stations_payload.append({
            "station": st_name, "input": inp,
            "fail": st.get("fail", 0), "retest": st.get("retest", 0),
            "yield": st.get("yield", 1.0), "retest_rate": st.get("retest_pct", 0.0),
            "issues": chart_payload, "table_issues": table_payload,
            "issue_chunks": chunks, "num_overflow_slides": max(0, len(chunks) - 1),
        })

    return {"product_name": product_name, "p_len": p_len, "stations_payload": stations_payload}


def _write_keynote_file(
    payload: Dict[str, Any],
    template_path: str,
    output_path: str,
    target_mp_rate: float,
    chart_items_limit: Optional[int]
) -> str:
    """
    File I/O phase: writes the Keynote file from a pre-computed payload.
    Uses a temp file as working copy — the final file is only moved into place
    at the very end, so no draft/partial file ever appears in the output directory.
    """
    product_name = payload["product_name"]
    p_len = payload["p_len"]
    stations_payload = payload["stations_payload"]

    # Work in a temp file so the output directory stays clean until we are done
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".key", prefix="_keynote_tmp_")
    os.close(tmp_fd)
    try:
        shutil.copyfile(template_path, tmp_path)

        subprocess.run(["open", "-a", "Keynote"], check=False)

        open_script = f"""use AppleScript version "2.4"
use scripting additions
set docPath to POSIX file "{tmp_path}"
tell application "Keynote"
    activate
    set doc to open docPath
    set baseCount to count of slides of doc
    return (id of doc) & "|" & (baseCount as string)
end tell"""
        open_res = _run_applescript(open_script)
        if "|" not in open_res:
            raise RuntimeError(f"Unexpected AppleScript open response: {repr(open_res)}")
        doc_id, base_count_str = open_res.split("|", 1)
        base_slide_count = int(base_count_str.strip())

        for st_info in stations_payload:
            chunks = st_info["issue_chunks"]
            first_chunk = chunks[0] if chunks else []

            body = _build_primary_slide_script(
                "doc", "slide 1 of doc", product_name, p_len,
                st_info, target_mp_rate, first_chunk
            )
            indented_body = "\n".join("    " + line for line in body.splitlines())
            _run_applescript(
                'use AppleScript version "2.4"\n'
                'use scripting additions\n'
                'tell application "Keynote"\n'
                f'    set doc to (first document whose id is "{doc_id}")\n'
                + indented_body + "\n"
                + 'end tell'
            )

            for _, chunk in enumerate(chunks[1:], start=1):
                cont_title = f"{product_name} | Retest breakdown_{st_info['station']}"
                overflow_body = _build_overflow_slide_script(
                    "doc", "slide 1 of doc", product_name, p_len, cont_title, chunk
                )
                indented_overflow = "\n".join("    " + line for line in overflow_body.splitlines())
                _run_applescript(
                    'use AppleScript version "2.4"\n'
                    'use scripting additions\n'
                    'tell application "Keynote"\n'
                    f'    set doc to (first document whose id is "{doc_id}")\n'
                    + indented_overflow + "\n"
                    + 'end tell'
                )

        finalize_script = f"""use AppleScript version "2.4"
use scripting additions
tell application "Keynote"
    set doc to (first document whose id is "{doc_id}")
    repeat {base_slide_count} times
        delete slide 1 of doc
    end repeat
    save doc
    close doc saving yes
    return "DONE"
end tell"""
        _run_applescript(finalize_script)

        # Update chart grids via protobuf (operates directly on the temp file)
        try:
            update_slide_charts(tmp_path, stations_payload, target_mp_rate,
                                chart_items_limit=chart_items_limit)
        except Exception as e:
            print(f"Warning: Chart grid update encountered error: {e}")

        # Atomic move: temp → final output path (appears only when fully ready)
        if os.path.exists(output_path):
            if os.path.isdir(output_path):
                shutil.rmtree(output_path)
            else:
                os.remove(output_path)
        shutil.move(tmp_path, output_path)
        return output_path

    except Exception:
        # Clean up temp file on failure
        try:
            if os.path.isdir(tmp_path):
                shutil.rmtree(tmp_path, ignore_errors=True)
            elif os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        raise


def generate_keynote_report(
    report_data: Dict[str, Any],
    template_path: str,
    output_path: str,
    target_mp_rate: float = 0.005,
    selected_stations: Optional[List[str]] = None,
    only_active: bool = True,
    chart_items_limit: Optional[int] = 5,
    table_items_limit: Optional[int] = None
) -> str:
    """Backward-compatible wrapper: compute payload then write file."""
    template_path = os.path.abspath(template_path)
    output_path   = os.path.abspath(output_path)

    payload = prepare_keynote_payload(
        report_data,
        selected_stations=selected_stations,
        table_items_limit=table_items_limit,
        chart_items_limit=chart_items_limit,
        only_active=only_active
    )
    return _write_keynote_file(payload, template_path, output_path,
                               target_mp_rate, chart_items_limit)
