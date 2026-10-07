import os
import sys
import subprocess
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
from tkinterdnd2 import TkinterDnD, DND_FILES
from typing import Optional, List, Dict, Any

from src.data_processor import build_report_data, is_datetime_or_date
from src.excel_generator import build_excel_workbook, generate_excel_report
from src.keynote_generator import prepare_keynote_payload, _write_keynote_file, generate_keynote_report
from src.faca_sync import run_phase2_faca_sync
from src.local_ai import is_ollama_running, ensure_ollama_running, is_model_available
from src.phase3_summary import generate_phase3_executive_keynote
from src.utils import get_resource_path


def get_rr_tier(rate: float, target_rate: float = 0.005) -> Dict[str, Any]:
    """Returns color styling, label and tier for a given retest rate."""
    if rate >= 0.03:
        return {
            "tier": "CRITICAL",
            "text": "CRITICAL",
            "fg": ("#991b1b", "#fca5a5"),
            "bg": ("#fee2e2", "#450a0a"),
            "accent": "#ef4444",
            "border": ("#f87171", "#b91c1c")
        }
    elif rate >= 0.02:
        return {
            "tier": "HIGH",
            "text": "HIGH",
            "fg": ("#9a3412", "#fdba74"),
            "bg": ("#ffedd5", "#431407"),
            "accent": "#f97316",
            "border": ("#fb923c", "#c2410c")
        }
    elif rate >= target_rate:
        return {
            "tier": "WARN",
            "text": "WARN",
            "fg": ("#854d0e", "#fde047"),
            "bg": ("#fef9c3", "#422006"),
            "accent": "#eab308",
            "border": ("#facc15", "#a16207")
        }
    else:
        return {
            "tier": "PASS",
            "text": "PASS",
            "fg": ("#166534", "#86efac"),
            "bg": ("#dcfce7", "#052e16"),
            "accent": "#22c55e",
            "border": ("#4ade80", "#15803d")
        }


class FileDropCard(ctk.CTkFrame):
    """
    Dropzone card supporting drag & drop and browse file dialog.
    Displays only the concise filename and file size — avoids cluttered full paths.
    """
    def __init__(self, master, label_text, required=False, placeholder="Kéo thả file vào đây hoặc bấm Chọn file...", on_change=None, filetypes=None, dialog_title=None):
        super().__init__(master, fg_color="transparent")
        self.pack(fill="x", padx=12, pady=3)
        self.on_change = on_change
        self.file_path = ""
        self.placeholder_text = placeholder
        self.filetypes = filetypes if filetypes else [("CSV files", "*.csv"), ("All files", "*.*")]
        self.dialog_title = dialog_title if dialog_title else "Chọn file"

        # Header title
        top_row = ctk.CTkFrame(self, fg_color="transparent")
        top_row.pack(fill="x", pady=(0, 2))
        lbl_text = f"{label_text} *" if required else label_text
        ctk.CTkLabel(
            top_row,
            text=lbl_text,
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w"
        ).pack(side="left")

        # Drop container card
        self.container = ctk.CTkFrame(
            self,
            fg_color=("gray92", "gray22"),
            corner_radius=8,
            border_width=1,
            border_color=("gray75", "gray35")
        )
        self.container.pack(fill="x")

        # Status text (shows only filename + size, or placeholder)
        self.status_lbl = ctk.CTkLabel(
            self.container,
            text=self.placeholder_text,
            text_color="gray",
            font=ctk.CTkFont(size=11),
            anchor="w"
        )
        self.status_lbl.pack(side="left", fill="x", expand=True, padx=10, pady=5)

        # Clear button (✕)
        self.btn_clear = ctk.CTkButton(
            self.container,
            text="✕",
            width=24,
            height=24,
            fg_color="transparent",
            text_color=("gray40", "gray60"),
            hover_color=("gray80", "gray30"),
            command=self.clear
        )

        # Browse button
        self.btn_browse = ctk.CTkButton(
            self.container,
            text="Chọn file...",
            width=80,
            height=26,
            command=self._browse
        )
        self.btn_browse.pack(side="right", padx=(4, 6), pady=4)

        # Register Drag & Drop
        self.container.drop_target_register(DND_FILES)
        self.container.dnd_bind("<<Drop>>", self._on_drop)
        self.status_lbl.drop_target_register(DND_FILES)
        self.status_lbl.dnd_bind("<<Drop>>", self._on_drop)

    def _browse(self):
        f = filedialog.askopenfilename(
            title=self.dialog_title,
            filetypes=self.filetypes
        )
        if f:
            self.set_file(f)

    def _on_drop(self, event):
        paths = self.winfo_toplevel().tk.splitlist(event.data)
        if paths:
            self.set_file(paths[0])

    def set_file(self, path):
        if not path or not os.path.exists(path):
            self.clear()
            return
        self.file_path = os.path.abspath(path)
        fname = os.path.basename(self.file_path)
        try:
            sz = os.path.getsize(self.file_path) / 1024
            sz_str = f"{sz:.1f} KB" if sz < 1024 else f"{sz/1024:.2f} MB"
        except Exception:
            sz_str = ""

        display_txt = f"✓ {fname}" + (f"  ({sz_str})" if sz_str else "")
        self.status_lbl.configure(
            text=display_txt,
            text_color=("#107c41", "#34d399"),
            font=ctk.CTkFont(size=11, weight="bold")
        )
        self.container.configure(border_color=("#107c41", "#059669"))
        self.btn_clear.pack(side="right", padx=(0, 4), pady=4)
        if self.on_change:
            self.on_change(self.file_path)

    def clear(self):
        self.file_path = ""
        self.status_lbl.configure(
            text=self.placeholder_text,
            text_color="gray",
            font=ctk.CTkFont(size=11)
        )
        self.container.configure(border_color=("gray75", "gray35"))
        self.btn_clear.pack_forget()
        if self.on_change:
            self.on_change("")


class ReportApp(ctk.CTk, TkinterDnD.DnDWrapper):
    """
    Main Factory Retest Studio Application.
    Features a modern real-time Analytics Dashboard & Instant Drilldown.
    """
    def __init__(self):
        super().__init__()
        self.TkdndVersion = TkinterDnD._require(self)

        self.title("0.5%hopeless")
        self.geometry("1260x860")
        self.minsize(1050, 720)

        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        self.base_dir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
        self.default_output_dir = os.path.join(self.base_dir, "Sample output")

        # Variables
        self.use_unit_var = tk.BooleanVar(value=False)
        # Output folders are chosen by the user (no silent default inside the app folder)
        self.out_dir_var = tk.StringVar(value="")
        self._last_output_dir = os.path.expanduser("~/Documents")

        self.product_name_var = tk.StringVar(value="")
        self.target_rate_var = tk.StringVar(value="0.50")
        self.station_filter_var = tk.StringVar(value="has_issues")
        self.grouping_mode_var = tk.StringVar(value="3_levels")
        self.chart_item_mode_var = tk.StringVar(value="top5")
        self.chart_item_custom_var = tk.StringVar(value="5")
        self.table_item_mode_var = tk.StringVar(value="top5")
        self.table_item_custom_var = tk.StringVar(value="5")
        self.search_var = tk.StringVar(value="")

        # Phase 2: Auto-Input FACA Variables
        self.p2_project_var = tk.StringVar(value="")
        self.p2_out_dir_var = tk.StringVar(value="")
        self.p2_merge_mode_var = tk.StringVar(value="excel_priority")
        self.p2_save_as_new_var = tk.BooleanVar(value=True)
        self.p2_convert_english_var = tk.BooleanVar(value=False)

        # Phase 3: Executive Summary Variables
        self.p3_project_var = tk.StringVar(value="")
        self.p3_out_dir_var = tk.StringVar(value="")
        self.p3_target_rate_var = tk.StringVar(value="0.5")

        # Data Cache
        self.report_data: Optional[Dict[str, Any]] = None
        self.selected_station: Optional[str] = None
        self.station_row_widgets: Dict[str, ctk.CTkFrame] = {}
        self.option_to_station_map: Dict[str, str] = {}
        self.station_to_option_map: Dict[str, str] = {}
        self._initialized = False

        # Build Interface
        self._build_ui()
        self._initialized = True

        # Variable Tracing for Instant Reactivity
        self.target_rate_var.trace_add("write", lambda *_: self._on_target_rate_changed())
        self.product_name_var.trace_add("write", lambda *_: self._on_product_name_changed())
        self.search_var.trace_add("write", lambda *_: self._on_search_changed())

        # Auto-load initial data
        self.after(50, self._load_live_data)

    def _build_ui(self):
        # ── 1. Top Executive Navigation Header ──────────────────────────────
        self._build_top_header()

        # ── 2. Main Two-Column Split Layout ─────────────────────────────────
        self.body_container = ctk.CTkFrame(self, fg_color="transparent")
        self.body_container.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        # Left Column: Configuration & Controls (Fixed width sidebar)
        self._build_left_panel()

        # Right Column: Live Insights & Real-Time Analytics Dashboard
        self._build_right_dashboard()

    def _build_top_header(self):
        header_frame = ctk.CTkFrame(self, height=54, corner_radius=0, fg_color=("gray92", "gray14"))
        header_frame.pack(fill="x", pady=(0, 8))
        header_frame.pack_propagate(False)

        # Brand Title
        brand_row = ctk.CTkFrame(header_frame, fg_color="transparent")
        brand_row.pack(side="left", padx=16, pady=6)

        ctk.CTkLabel(
            brand_row,
            text="⚡ 0.5%hopeless",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=("#0066cc", "#38bdf8")
        ).pack(side="left")

        ctk.CTkLabel(
            brand_row,
            text=" |  Hệ thống Phân tích Retest Trực tiếp & Tự động Báo cáo",
            font=ctk.CTkFont(size=12),
            text_color=("gray50", "gray65")
        ).pack(side="left", padx=(4, 0))

        # Right status badge & theme switcher
        right_box = ctk.CTkFrame(header_frame, fg_color="transparent")
        right_box.pack(side="right", padx=16, pady=8)

        self.lbl_global_status = ctk.CTkLabel(
            right_box,
            text="⚪ Đang khởi tạo...",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="gray"
        )
        self.lbl_global_status.pack(side="left", padx=(0, 15))

        self.theme_btn = ctk.CTkSegmentedButton(
            right_box,
            values=["System", "Dark", "Light"],
            command=self._on_theme_changed,
            height=26,
            font=ctk.CTkFont(size=11)
        )
        self.theme_btn.set("System")
        self.theme_btn.pack(side="left")

    def _build_left_panel(self):
        self.left_panel = ctk.CTkScrollableFrame(
            self.body_container,
            width=410,
            corner_radius=10,
            fg_color=("gray95", "gray18")
        )
        self.left_panel.pack(side="left", fill="y", padx=(0, 8), pady=0)

        # ── 3-Phase Navigation Bar ──────────────────────────────────────────
        phase_nav_frame = ctk.CTkFrame(self.left_panel, corner_radius=8, fg_color=("gray90", "gray22"))
        phase_nav_frame.pack(fill="x", pady=(2, 6), padx=2)

        self.phase_selector = ctk.CTkSegmentedButton(
            phase_nav_frame,
            values=["Phase 1: Trích Xuất", "Phase 2: Nhập Tự Động", "Phase 3: Tổng Hợp"],
            command=self._on_phase_changed,
            height=32,
            font=ctk.CTkFont(size=11, weight="bold")
        )
        self.phase_selector.set("Phase 1: Trích Xuất")
        self.phase_selector.pack(fill="x", padx=6, pady=6)

        # ── Phase Containers ────────────────────────────────────────────────
        self.phase1_container = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        self._build_phase1_view()

        self.phase2_container = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        self._build_phase2_view()

        self.phase3_container = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        self._build_phase3_view()

        # Phase 1 is visible by default
        self.phase1_container.pack(fill="x", expand=True)

    def _on_phase_changed(self, selected_phase: str):
        self.phase1_container.pack_forget()
        self.phase2_container.pack_forget()
        self.phase3_container.pack_forget()

        if "Phase 1" in selected_phase:
            self.phase1_container.pack(fill="x", expand=True)
        elif "Phase 2" in selected_phase:
            self.phase2_container.pack(fill="x", expand=True)
        elif "Phase 3" in selected_phase:
            self.phase3_container.pack(fill="x", expand=True)

    def _build_phase1_view(self):
        # SECTION 1: Input Files
        s1_frame = ctk.CTkFrame(self.phase1_container, corner_radius=8, fg_color=("gray90", "gray22"))
        s1_frame.pack(fill="x", pady=(2, 8), padx=2)

        ctk.CTkLabel(
            s1_frame,
            text="1. File Dữ Liệu Đầu Vào (Input Files)",
            font=ctk.CTkFont(size=13, weight="bold")
        ).pack(anchor="w", padx=12, pady=(8, 4))

        # Multi-file Dropzone
        drop_banner = ctk.CTkFrame(
            s1_frame,
            fg_color=("gray85", "gray16"),
            corner_radius=6,
            border_width=1,
            border_color=("#0066cc", "#3b82f6")
        )
        drop_banner.pack(fill="x", padx=12, pady=(0, 6))

        drop_lbl = ctk.CTkLabel(
            drop_banner,
            text="📥 Kéo & thả file CSV vào đây — Tự động nhận diện",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("#0066cc", "#60a5fa")
        )
        drop_lbl.pack(pady=6)
        drop_banner.drop_target_register(DND_FILES)
        drop_banner.dnd_bind("<<Drop>>", self._on_global_drop)
        drop_lbl.drop_target_register(DND_FILES)
        drop_lbl.dnd_bind("<<Drop>>", self._on_global_drop)

        # File Drop Cards
        self.perf_card = FileDropCard(
            s1_frame,
            label_text="Performance-Breakdown.csv",
            required=True,
            on_change=lambda _: self._on_files_changed()
        )

        self.symptoms_card = FileDropCard(
            s1_frame,
            label_text="Retest-Symptoms.csv",
            required=True,
            on_change=lambda _: self._on_files_changed()
        )

        unit_row = ctk.CTkFrame(s1_frame, fg_color="transparent")
        unit_row.pack(fill="x", padx=12, pady=(4, 2))
        self.unit_cb = ctk.CTkCheckBox(
            unit_row,
            text="Kèm unitTestDetails.csv (lấy SN vào Excel)",
            variable=self.use_unit_var,
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._on_toggle_unit_details
        )
        self.unit_cb.pack(side="left")

        self.unit_card = FileDropCard(
            s1_frame,
            label_text="unitTestDetails.csv",
            required=False,
            on_change=lambda _: self._on_files_changed()
        )
        self._on_toggle_unit_details()

        # SECTION 2: Configuration & Real-Time Filters
        s2_frame = ctk.CTkFrame(self.phase1_container, corner_radius=8, fg_color=("gray90", "gray22"))
        s2_frame.pack(fill="x", pady=6, padx=2)

        ctk.CTkLabel(
            s2_frame,
            text="2. Cấu Hình & Bộ Lọc Tức Thời (Live Filters)",
            font=ctk.CTkFont(size=13, weight="bold")
        ).pack(anchor="w", padx=12, pady=(8, 4))

        # Product name and Target rate
        grid_params = ctk.CTkFrame(s2_frame, fg_color="transparent")
        grid_params.pack(fill="x", padx=12, pady=(2, 6))

        ctk.CTkLabel(grid_params, text="Product:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=0, column=0, sticky="w", pady=2)
        prod_entry = ctk.CTkEntry(grid_params, textvariable=self.product_name_var, placeholder_text="Tên SP...", width=100, height=26, font=ctk.CTkFont(size=11))
        prod_entry.grid(row=0, column=1, sticky="w", padx=(6, 12), pady=2)

        ctk.CTkLabel(grid_params, text="Target MP (%):", font=ctk.CTkFont(size=11, weight="bold")).grid(row=0, column=2, sticky="w", pady=2)
        rate_entry = ctk.CTkEntry(grid_params, textvariable=self.target_rate_var, width=65, height=26, font=ctk.CTkFont(size=11))
        rate_entry.grid(row=0, column=3, sticky="w", padx=(6, 0), pady=2)

        # Filter Stations Radio Buttons
        ctk.CTkLabel(
            s2_frame,
            text="Bộ Lọc Hiển Thị Trạm:",
            font=ctk.CTkFont(size=11, weight="bold")
        ).pack(anchor="w", padx=12, pady=(4, 2))

        filter_box = ctk.CTkFrame(s2_frame, fg_color="transparent")
        filter_box.pack(fill="x", padx=12, pady=(0, 4))

        ctk.CTkRadioButton(
            filter_box, text="Chỉ trạm có lỗi",
            variable=self.station_filter_var, value="has_issues",
            font=ctk.CTkFont(size=11), command=self._on_station_filter_changed
        ).pack(anchor="w", pady=1)

        ctk.CTkRadioButton(
            filter_box, text="Chỉ trạm Retest > Target",
            variable=self.station_filter_var, value="high_only",
            font=ctk.CTkFont(size=11), command=self._on_station_filter_changed
        ).pack(anchor="w", pady=1)

        ctk.CTkRadioButton(
            filter_box, text="Tất cả các trạm trong file",
            variable=self.station_filter_var, value="all",
            font=ctk.CTkFont(size=11), command=self._on_station_filter_changed
        ).pack(anchor="w", pady=1)

        # Grouping Mode Radio Buttons
        ctk.CTkLabel(
            s2_frame,
            text="Cấp Độ Phân Loại Lỗi (Issue Grouping):",
            font=ctk.CTkFont(size=11, weight="bold")
        ).pack(anchor="w", padx=12, pady=(6, 2))

        grp_box = ctk.CTkFrame(s2_frame, fg_color="transparent")
        grp_box.pack(fill="x", padx=12, pady=(0, 6))

        ctk.CTkRadioButton(
            grp_box, text="Test + Sub-test + Sub-sub (3 cấp, mặc định)",
            variable=self.grouping_mode_var, value="3_levels",
            font=ctk.CTkFont(size=11), command=self._on_grouping_mode_changed
        ).pack(anchor="w", pady=1)

        ctk.CTkRadioButton(
            grp_box, text="Test + Sub-test (2 cấp, bỏ Sub-sub)",
            variable=self.grouping_mode_var, value="2_levels",
            font=ctk.CTkFont(size=11), command=self._on_grouping_mode_changed
        ).pack(anchor="w", pady=1)

        ctk.CTkRadioButton(
            grp_box, text="Chỉ Test (1 cấp, gộp toàn bộ theo Test)",
            variable=self.grouping_mode_var, value="1_level",
            font=ctk.CTkFont(size=11), command=self._on_grouping_mode_changed
        ).pack(anchor="w", pady=1)

        # Top Items Limit
        ctk.CTkLabel(
            s2_frame,
            text="Số Lượng Item Bảng Issue:",
            font=ctk.CTkFont(size=11, weight="bold")
        ).pack(anchor="w", padx=12, pady=(4, 2))

        item_row = ctk.CTkFrame(s2_frame, fg_color="transparent")
        item_row.pack(fill="x", padx=12, pady=(0, 6))

        ctk.CTkRadioButton(
            item_row, text="Top 5 (Mặc định)", variable=self.table_item_mode_var,
            value="top5", font=ctk.CTkFont(size=11), command=self._on_table_mode_changed
        ).pack(side="left", padx=(0, 10))

        ctk.CTkRadioButton(
            item_row, text="Tất cả", variable=self.table_item_mode_var,
            value="all", font=ctk.CTkFont(size=11), command=self._on_table_mode_changed
        ).pack(side="left", padx=(0, 10))

        ctk.CTkRadioButton(
            item_row, text="Tùy chọn:", variable=self.table_item_mode_var,
            value="custom", font=ctk.CTkFont(size=11), command=self._on_table_mode_changed
        ).pack(side="left", padx=(0, 4))

        self.table_custom_entry = ctk.CTkEntry(item_row, textvariable=self.table_item_custom_var, width=45, height=24, font=ctk.CTkFont(size=11))
        self.table_custom_entry.pack(side="left")
        self.table_custom_entry.configure(state="disabled")

        # Output Directory row
        out_row = ctk.CTkFrame(s2_frame, fg_color="transparent")
        out_row.pack(fill="x", padx=12, pady=(4, 8))
        self.out_dir_lbl = ctk.CTkLabel(
            out_row,
            text="",
            font=ctk.CTkFont(size=11, weight="bold"),
            anchor="w"
        )
        self.out_dir_lbl.pack(side="left", fill="x", expand=True)
        self._refresh_dir_label(self.out_dir_lbl, self.out_dir_var.get())

        ctk.CTkButton(
            out_row, text="Chọn thư mục...", width=95, height=24,
            font=ctk.CTkFont(size=10), command=self._choose_output_dir
        ).pack(side="right")

        # SECTION 3: Action Buttons
        s3_frame = ctk.CTkFrame(self.phase1_container, corner_radius=8, fg_color=("gray90", "gray22"))
        s3_frame.pack(fill="x", pady=6, padx=2)

        ctk.CTkLabel(
            s3_frame,
            text="3. Xuất Báo Cáo (Export Actions)",
            font=ctk.CTkFont(size=13, weight="bold")
        ).pack(anchor="w", padx=12, pady=(8, 6))

        self.btn_gen_excel = ctk.CTkButton(
            s3_frame,
            text="📗 Xuất File Excel",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=34,
            fg_color="#107c41",
            hover_color="#0b5c30",
            command=lambda: self._start_generation(gen_excel=True, gen_keynote=False)
        )
        self.btn_gen_excel.pack(fill="x", padx=12, pady=3)

        self.btn_gen_keynote = ctk.CTkButton(
            s3_frame,
            text="📊 Xuất Slide Keynote",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=34,
            fg_color="#0066cc",
            hover_color="#004d99",
            command=lambda: self._start_generation(gen_excel=False, gen_keynote=True)
        )
        self.btn_gen_keynote.pack(fill="x", padx=12, pady=3)

        self.btn_gen_all = ctk.CTkButton(
            s3_frame,
            text="⚡ Xuất Cả Hai (Excel + Keynote)",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=38,
            fg_color="#d97706",
            hover_color="#b45309",
            command=lambda: self._start_generation(gen_excel=True, gen_keynote=True)
        )
        self.btn_gen_all.pack(fill="x", padx=12, pady=(3, 10))

        # Progress bar
        self.progress_bar = ctk.CTkProgressBar(s3_frame, height=8)
        self.progress_bar.pack(fill="x", padx=12, pady=(0, 6))
        self.progress_bar.set(0)

        # Log Section
        self.log_container = ctk.CTkFrame(self.phase1_container, corner_radius=8, fg_color=("gray90", "gray22"))
        self.log_container.pack(fill="x", pady=6, padx=2)

        log_head_row = ctk.CTkFrame(self.log_container, fg_color="transparent")
        log_head_row.pack(fill="x", padx=12, pady=(6, 2))
        ctk.CTkLabel(
            log_head_row,
            text="Nhật Ký Tiến Trình (Logs):",
            font=ctk.CTkFont(size=11, weight="bold")
        ).pack(side="left")

        self.log_text = ctk.CTkTextbox(
            self.log_container,
            height=95,
            font=ctk.CTkFont(family="Courier", size=10)
        )
        self.log_text.pack(fill="x", padx=10, pady=(2, 8))

    def _build_phase2_view(self):
        # Header banner
        header_card = ctk.CTkFrame(self.phase2_container, corner_radius=8, fg_color=("gray90", "gray22"))
        header_card.pack(fill="x", pady=(2, 6), padx=2)

        ctk.CTkLabel(
            header_card,
            text="⚡ PHASE 2: NHẬP DỮ LIỆU TỰ ĐỘNG (FACA SYNC)",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=("#0066cc", "#38bdf8")
        ).pack(anchor="w", padx=12, pady=(10, 2))

        ctk.CTkLabel(
            header_card,
            text="Tự động đồng bộ nội dung FACA từ file Excel sang file Keynote\nkhớp chính xác theo từng Trạm và Tên Hạng Mục Lỗi.",
            font=ctk.CTkFont(size=11),
            text_color=("gray45", "gray65"),
            justify="left"
        ).pack(anchor="w", padx=12, pady=(0, 10))

        # SECTION 1: Input Files
        s1_frame = ctk.CTkFrame(self.phase2_container, corner_radius=8, fg_color=("gray90", "gray22"))
        s1_frame.pack(fill="x", pady=4, padx=2)

        ctk.CTkLabel(
            s1_frame,
            text="1. File Dữ Liệu Phase 1 (Input Files)",
            font=ctk.CTkFont(size=12, weight="bold")
        ).pack(anchor="w", padx=12, pady=(8, 4))

        # Drop banner for Phase 2
        p2_drop_banner = ctk.CTkFrame(
            s1_frame,
            fg_color=("gray85", "gray16"),
            corner_radius=6,
            border_width=1,
            border_color=("#0066cc", "#3b82f6")
        )
        p2_drop_banner.pack(fill="x", padx=12, pady=(0, 6))

        p2_drop_lbl = ctk.CTkLabel(
            p2_drop_banner,
            text="📥 Kéo & thả file Excel (.xlsx) và Keynote (.key) vào đây",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("#0066cc", "#60a5fa")
        )
        p2_drop_lbl.pack(pady=6)
        p2_drop_banner.drop_target_register(DND_FILES)
        p2_drop_banner.dnd_bind("<<Drop>>", self._on_p2_global_drop)
        p2_drop_lbl.drop_target_register(DND_FILES)
        p2_drop_lbl.dnd_bind("<<Drop>>", self._on_p2_global_drop)

        self.p2_excel_card = FileDropCard(
            s1_frame,
            label_text="File Excel đã ghi FACA (.xlsx)",
            required=True,
            placeholder="Kéo thả file .xlsx vào đây hoặc bấm Chọn file...",
            filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")],
            dialog_title="Chọn file Excel có FACA (.xlsx)"
        )

        self.p2_keynote_card = FileDropCard(
            s1_frame,
            label_text="File Keynote cần nhập FACA (.key)",
            required=True,
            placeholder="Kéo thả file .key vào đây hoặc bấm Chọn file...",
            filetypes=[("Keynote files", "*.key"), ("All files", "*.*")],
            dialog_title="Chọn file Keynote (.key)"
        )

        # SECTION 2: Conflict & Merge Strategy
        s2_frame = ctk.CTkFrame(self.phase2_container, corner_radius=8, fg_color=("gray90", "gray22"))
        s2_frame.pack(fill="x", pady=6, padx=2)

        ctk.CTkLabel(
            s2_frame,
            text="2. Chế Độ Hợp Nhất FACA (3 Lựa Chọn)",
            font=ctk.CTkFont(size=12, weight="bold")
        ).pack(anchor="w", padx=12, pady=(8, 4))

        merge_box = ctk.CTkFrame(s2_frame, fg_color="transparent")
        merge_box.pack(fill="x", padx=12, pady=(0, 6))

        # Option 1: Excel priority
        ctk.CTkRadioButton(
            merge_box,
            text="Ưu tiên dữ liệu Excel (Ghi đè FACA từ Excel sang Keynote)",
            variable=self.p2_merge_mode_var,
            value="excel_priority",
            font=ctk.CTkFont(size=11, weight="bold")
        ).pack(anchor="w", pady=(2, 1))
        ctk.CTkLabel(
            merge_box,
            text="   Ghi đè FACA từ Excel sang; nếu Excel trống thì giữ Keynote.",
            font=ctk.CTkFont(size=10),
            text_color=("gray45", "gray60")
        ).pack(anchor="w", pady=(0, 4))

        # Option 2: Keynote priority
        ctk.CTkRadioButton(
            merge_box,
            text="Ưu tiên dữ liệu Keynote (Chỉ điền ô trống từ Excel)",
            variable=self.p2_merge_mode_var,
            value="keynote_priority",
            font=ctk.CTkFont(size=11, weight="bold")
        ).pack(anchor="w", pady=(2, 1))
        ctk.CTkLabel(
            merge_box,
            text="   Giữ nguyên nếu Keynote đã có FACA; chỉ điền nếu Keynote trống.",
            font=ctk.CTkFont(size=10),
            text_color=("gray45", "gray60")
        ).pack(anchor="w", pady=(0, 4))

        # Option 3: Merge both
        ctk.CTkRadioButton(
            merge_box,
            text="Gộp dữ liệu cả hai ([Keynote] + [Excel])",
            variable=self.p2_merge_mode_var,
            value="merge_both",
            font=ctk.CTkFont(size=11, weight="bold")
        ).pack(anchor="w", pady=(2, 1))
        ctk.CTkLabel(
            merge_box,
            text="   Nối cả 2 bằng dòng mới; nếu 2 bên giống hệt nhau sẽ không lặp.",
            font=ctk.CTkFont(size=10),
            text_color=("gray45", "gray60")
        ).pack(anchor="w", pady=(0, 6))

        # Save as new file & English convert options
        save_row = ctk.CTkFrame(s2_frame, fg_color="transparent")
        save_row.pack(fill="x", padx=12, pady=(2, 4))
        ctk.CTkCheckBox(
            save_row,
            text="Xuất ra file Keynote mới (*_FACA_Updated.key)",
            variable=self.p2_save_as_new_var,
            font=ctk.CTkFont(size=11, weight="bold")
        ).pack(anchor="w", pady=(0, 4))
        ctk.CTkCheckBox(
            save_row,
            text="🌐 Tạo thêm 1 file convert sang Tiếng Anh (*_FACA_English.key)",
            variable=self.p2_convert_english_var,
            font=ctk.CTkFont(size=11, weight="bold")
        ).pack(anchor="w")

        # Project & Output folder configuration for Phase 2
        p2_cfg_frame = ctk.CTkFrame(s2_frame, fg_color="transparent")
        p2_cfg_frame.pack(fill="x", padx=12, pady=(4, 6))

        p2_proj_row = ctk.CTkFrame(p2_cfg_frame, fg_color="transparent")
        p2_proj_row.pack(fill="x", pady=2)
        ctk.CTkLabel(p2_proj_row, text="Project:", font=ctk.CTkFont(size=11, weight="bold")).pack(side="left")
        ctk.CTkEntry(
            p2_proj_row,
            textvariable=self.p2_project_var,
            placeholder_text="Tên Project (tùy chọn)...",
            width=160,
            height=26,
            font=ctk.CTkFont(size=11)
        ).pack(side="left", padx=8)

        # Output Directory row for Phase 2
        p2_out_row = ctk.CTkFrame(p2_cfg_frame, fg_color="transparent")
        p2_out_row.pack(fill="x", pady=(4, 2))
        self.p2_out_dir_lbl = ctk.CTkLabel(
            p2_out_row,
            text="",
            font=ctk.CTkFont(size=11, weight="bold"),
            anchor="w"
        )
        self.p2_out_dir_lbl.pack(side="left", fill="x", expand=True)
        self._refresh_dir_label(self.p2_out_dir_lbl, self.p2_out_dir_var.get())

        ctk.CTkButton(
            p2_out_row, text="Chọn thư mục...", width=95, height=24,
            font=ctk.CTkFont(size=10), command=self._choose_p2_output_dir
        ).pack(side="right")

        # SECTION 3: Action Buttons
        s3_frame = ctk.CTkFrame(self.phase2_container, corner_radius=8, fg_color=("gray90", "gray22"))
        s3_frame.pack(fill="x", pady=6, padx=2)

        ctk.CTkLabel(
            s3_frame,
            text="3. Thực Thi Đồng Bộ (Execution)",
            font=ctk.CTkFont(size=12, weight="bold")
        ).pack(anchor="w", padx=12, pady=(8, 4))

        self.btn_p2_run = ctk.CTkButton(
            s3_frame,
            text="🚀 Bắt Đầu Đồng Bộ FACA Sang Keynote",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=38,
            fg_color="#0066cc",
            hover_color="#004d99",
            command=self._start_phase2_sync
        )
        self.btn_p2_run.pack(fill="x", padx=12, pady=4)

        self.p2_progress_bar = ctk.CTkProgressBar(s3_frame, height=8)
        self.p2_progress_bar.pack(fill="x", padx=12, pady=(2, 8))
        self.p2_progress_bar.set(0)

        # Log Section for Phase 2
        p2_log_container = ctk.CTkFrame(self.phase2_container, corner_radius=8, fg_color=("gray90", "gray22"))
        p2_log_container.pack(fill="x", pady=6, padx=2)

        p2_log_head = ctk.CTkFrame(p2_log_container, fg_color="transparent")
        p2_log_head.pack(fill="x", padx=12, pady=(6, 2))
        ctk.CTkLabel(
            p2_log_head,
            text="Nhật Ký Đồng Bộ (Phase 2 Logs):",
            font=ctk.CTkFont(size=11, weight="bold")
        ).pack(side="left")

        self.p2_log_text = ctk.CTkTextbox(
            p2_log_container,
            height=110,
            font=ctk.CTkFont(family="Courier", size=10)
        )
        self.p2_log_text.pack(fill="x", padx=10, pady=(2, 8))

    def _on_p2_global_drop(self, event):
        paths = self.winfo_toplevel().tk.splitlist(event.data)
        for p in paths:
            ext = os.path.splitext(p)[1].lower()
            if ext in [".xlsx", ".xlsm"]:
                self.p2_excel_card.set_file(p)
            elif ext == ".key":
                self.p2_keynote_card.set_file(p)

    def _log_p2(self, msg: str):
        if hasattr(self, "p2_log_text"):
            self.p2_log_text.insert("end", f"{msg}\n")
            self.p2_log_text.see("end")

    def _start_phase2_sync(self):
        xl_path = self.p2_excel_card.file_path
        kn_path = self.p2_keynote_card.file_path

        if not xl_path or not os.path.exists(xl_path):
            messagebox.showwarning("Thiếu File Excel", "Vui lòng chọn hoặc kéo thả file Excel (.xlsx) đã ghi FACA!")
            return
        if not kn_path or not os.path.exists(kn_path):
            messagebox.showwarning("Thiếu File Keynote", "Vui lòng chọn hoặc kéo thả file Keynote (.key) đích!")
            return

        save_as_new = self.p2_save_as_new_var.get()
        if save_as_new or self.p2_convert_english_var.get():
            # A new file will be written -> the user must choose where
            out_dir = self._ensure_output_dir(
                self.p2_out_dir_var, self.p2_out_dir_lbl,
                "Chọn thư mục lưu báo cáo Phase 2", self._log_p2
            )
            if not out_dir:
                return
        else:
            # Overwrite in place: no new file is created
            out_dir = os.path.dirname(os.path.abspath(kn_path))

        self.btn_p2_run.configure(state="disabled")
        self.p2_progress_bar.configure(mode="indeterminate")
        self.p2_progress_bar.start()

        def log_fn(msg):
            self.after(0, lambda: self._log_p2(msg))

        def worker():
            try:
                mode = self.p2_merge_mode_var.get()
                p2_proj = self.p2_project_var.get().strip()

                res = run_phase2_faca_sync(
                    excel_path=xl_path,
                    keynote_path=kn_path,
                    output_dir=out_dir,
                    mode=mode,
                    save_as_new=save_as_new,
                    project_name=p2_proj if p2_proj else None,
                    create_english_copy=self.p2_convert_english_var.get(),
                    log_cb=log_fn
                )

                self.after(0, lambda: self._on_phase2_finished(res))
            except Exception as e:
                err_msg = str(e)
                self.after(0, lambda: self._on_phase2_error(err_msg))

        threading.Thread(target=worker, daemon=True).start()

    def _on_phase2_finished(self, res: Dict[str, Any]):
        self.btn_p2_run.configure(state="normal")
        self.p2_progress_bar.stop()
        self.p2_progress_bar.configure(mode="determinate")
        self.p2_progress_bar.set(1.0)

        out_path = res["output_path"]
        en_path = res.get("english_output_path")
        scanned = res["total_scanned"]
        matched = res["matched_with_excel"]
        updated = res["updated_cells"]

        msg = (
            f"🎉 ĐỒNG BỘ FACA THÀNH CÔNG!\n\n"
            f"• Số mục lỗi quét trên Keynote: {scanned}\n"
            f"• Số mục lỗi khớp với Excel: {matched}\n"
            f"• Số ô FACA đã cập nhật mới: {updated}\n\n"
            f"📁 File Keynote đồng bộ:\n{out_path}"
        )
        if en_path:
            msg += f"\n\n🌐 File Keynote dịch Tiếng Anh (*_FACA_English.key):\n{en_path}"
            msg += f"\n\n💡 Gợi ý: Bạn có thể mở kiểm tra, chỉnh sửa file Tiếng Anh này theo ý muốn, sau đó sang Phase 3 tải file lên để tạo Executive Summary."

        if messagebox.askyesno("Thành công", f"{msg}\n\nBạn có muốn mở file Keynote kết quả ngay không?"):
            target_to_open = en_path if en_path else out_path
            subprocess.run(["open", target_to_open])

    def _on_phase2_error(self, err_msg: str):
        self.btn_p2_run.configure(state="normal")
        self.p2_progress_bar.stop()
        self.p2_progress_bar.configure(mode="determinate")
        self.p2_progress_bar.set(0)
        self._log_p2(f"❌ LỖI: {err_msg}")
        messagebox.showerror("Lỗi Đồng Bộ", f"Không thể đồng bộ FACA:\n\n{err_msg}")

    def _build_phase3_view(self):
        # Header banner
        header_card = ctk.CTkFrame(self.phase3_container, corner_radius=8, fg_color=("gray90", "gray22"))
        header_card.pack(fill="x", pady=(2, 6), padx=2)

        ctk.CTkLabel(
            header_card,
            text="📈 PHASE 3: TỔNG HỢP EXECUTIVE REPORT",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=("#16a34a", "#4ade80")
        ).pack(anchor="w", padx=12, pady=(10, 2))

        ctk.CTkLabel(
            header_card,
            text="Tải lên file Keynote Tiếng Anh (sau khi bạn đã hiệu chỉnh từ Phase 2),\ngom nhóm lỗi theo Category, tính tổng % và tạo slide tổng hợp theo mẫu Sample-keynote2.",
            font=ctk.CTkFont(size=11),
            text_color=("gray45", "gray65"),
            justify="left"
        ).pack(anchor="w", padx=12, pady=(0, 10))

        # ── Step 1: Input Files (Keynote & Optional Performance CSV) ──────────
        p3_s1_frame = ctk.CTkFrame(self.phase3_container, corner_radius=8, fg_color=("gray90", "gray22"))
        p3_s1_frame.pack(fill="x", pady=4, padx=2)

        ctk.CTkLabel(
            p3_s1_frame,
            text="1. Chọn File Đầu Vào (Input Files):",
            font=ctk.CTkFont(size=12, weight="bold")
        ).pack(anchor="w", padx=12, pady=(8, 4))

        self.p3_keynote_card = FileDropCard(
            p3_s1_frame,
            label_text="File Keynote Tiếng Anh (Phase 2) - Bắt buộc:",
            required=True,
            placeholder="Kéo thả file Keynote Tiếng Anh (.key) vào đây hoặc bấm Chọn file...",
            filetypes=[("Keynote files", "*.key"), ("All files", "*.*")],
            dialog_title="Chọn file Keynote Tiếng Anh đã chỉnh sửa"
        )
        self.p3_keynote_card.pack(fill="x", padx=12, pady=(2, 6))

        self.p3_perf_card = FileDropCard(
            p3_s1_frame,
            label_text="File Performance-Breakdown.csv (Chính / Hiện tại) - Tùy chọn:",
            required=False,
            placeholder="Kéo thả Performance-Breakdown.csv vào đây (lấy danh mục trạm; ưu tiên % từ Keynote nếu trùng trạm)...",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            dialog_title="Chọn file Performance-Breakdown.csv (Chính)"
        )
        self.p3_perf_card.pack(fill="x", padx=12, pady=(2, 6))

        self.p3_perf_benchmark_card = FileDropCard(
            p3_s1_frame,
            label_text="File Performance-Breakdown.csv (Đối chứng / MP) - Tùy chọn:",
            required=False,
            placeholder="Kéo thả file Performance đối chứng (lấy % vào cột 2 nằm giữa tên và %)...",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            dialog_title="Chọn file Performance-Breakdown.csv (Đối chứng / MP)"
        )
        self.p3_perf_benchmark_card.pack(fill="x", padx=12, pady=(2, 8))

        # ── Step 2: Executive Report Settings ──────────────────────────────
        cfg_card = ctk.CTkFrame(self.phase3_container, corner_radius=8, fg_color=("gray90", "gray22"))
        cfg_card.pack(fill="x", pady=4, padx=2)

        ctk.CTkLabel(
            cfg_card,
            text="2. Cấu Hình Báo Cáo Tổng Hợp:",
            font=ctk.CTkFont(size=12, weight="bold")
        ).pack(anchor="w", padx=12, pady=(8, 4))

        # Reassurance Note
        note_row = ctk.CTkFrame(cfg_card, fg_color="transparent")
        note_row.pack(fill="x", padx=12, pady=(2, 6))

        ctk.CTkLabel(
            note_row,
            text="✨ Dữ liệu FACA Tiếng Anh đã chỉnh sửa từ Phase 2 sẽ được bảo lưu nguyên vẹn 100% khi gom nhóm vào slide.",
            font=ctk.CTkFont(size=11),
            text_color=("gray30", "gray70"),
            wraplength=380,
            justify="left"
        ).pack(anchor="w")

        # Project Name & Target MP Rate Row
        cfg_grid = ctk.CTkFrame(cfg_card, fg_color="transparent")
        cfg_grid.pack(fill="x", padx=12, pady=(2, 4))

        ctk.CTkLabel(cfg_grid, text="Project:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=0, column=0, sticky="w", pady=2)
        self.p3_project_entry = ctk.CTkEntry(
            cfg_grid,
            textvariable=self.p3_project_var,
            placeholder_text="Tên Project (VD: PVT)...",
            width=130,
            height=26,
            font=ctk.CTkFont(size=11)
        )
        self.p3_project_entry.grid(row=0, column=1, sticky="w", padx=(6, 12), pady=2)

        ctk.CTkLabel(cfg_grid, text="Target MP (%):", font=ctk.CTkFont(size=11, weight="bold")).grid(row=0, column=2, sticky="w", pady=2)
        self.p3_target_entry = ctk.CTkEntry(
            cfg_grid,
            textvariable=self.p3_target_rate_var,
            width=65,
            height=26,
            font=ctk.CTkFont(size=11)
        )
        self.p3_target_entry.grid(row=0, column=3, sticky="w", padx=(6, 0), pady=2)

        # Output Directory row for Phase 3
        p3_out_row = ctk.CTkFrame(cfg_card, fg_color="transparent")
        p3_out_row.pack(fill="x", padx=12, pady=(4, 8))
        self.p3_out_dir_lbl = ctk.CTkLabel(
            p3_out_row,
            text="",
            font=ctk.CTkFont(size=11, weight="bold"),
            anchor="w"
        )
        self.p3_out_dir_lbl.pack(side="left", fill="x", expand=True)
        self._refresh_dir_label(self.p3_out_dir_lbl, self.p3_out_dir_var.get())

        ctk.CTkButton(
            p3_out_row, text="Chọn thư mục...", width=95, height=24,
            font=ctk.CTkFont(size=10), command=self._choose_p3_output_dir
        ).pack(side="right")

        # ── Step 3: Action & Real-time Console ──────────────────────────────
        act_card = ctk.CTkFrame(self.phase3_container, corner_radius=8, fg_color=("gray90", "gray22"))
        act_card.pack(fill="x", pady=6, padx=2)

        ctk.CTkLabel(
            act_card,
            text="3. Thực Thi Tổng Hợp Báo Cáo:",
            font=ctk.CTkFont(size=12, weight="bold")
        ).pack(anchor="w", padx=12, pady=(8, 4))

        self.btn_phase3_run = ctk.CTkButton(
            act_card,
            text="🚀 Xuất Slide Keynote Tổng Hợp (Executive Report)",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=38,
            fg_color="#16a34a",
            hover_color="#15803d",
            command=self._on_phase3_run_clicked
        )
        self.btn_phase3_run.pack(fill="x", padx=12, pady=(4, 6))

        self.p3_progress_bar = ctk.CTkProgressBar(act_card, height=6)
        self.p3_progress_bar.pack(fill="x", padx=12, pady=(2, 6))
        self.p3_progress_bar.set(0)

        self.p3_log_box = ctk.CTkTextbox(
            act_card,
            height=90,
            font=ctk.CTkFont(family="Courier", size=10),
            state="disabled"
        )
        self.p3_log_box.pack(fill="x", padx=12, pady=(0, 10))

    def _log_p3(self, msg: str):
        def _append():
            self.p3_log_box.configure(state="normal")
            self.p3_log_box.insert("end", f"{msg}\n")
            self.p3_log_box.see("end")
            self.p3_log_box.configure(state="disabled")
        self.after(0, _append)

    def _on_phase3_run_clicked(self):
        """Executes Phase 3 Executive Keynote generation in background thread."""
        keynote_path = self.p3_keynote_card.file_path
        if not keynote_path or not os.path.exists(keynote_path):
            messagebox.showwarning(
                "Thiếu File Keynote",
                "Vui lòng chọn hoặc kéo thả file Keynote đã dịch Tiếng Anh từ Phase 2 (*.key) ở Bước 1!"
            )
            return

        try:
            target_mp = float(self.p3_target_rate_var.get().strip()) / 100.0
        except ValueError:
            target_mp = 0.005

        template_key = get_resource_path("Sample output/Sample-keynote2.key")
        cover_template = get_resource_path("Sample output/Sample-keynote3.key")
        if not os.path.exists(template_key):
            messagebox.showerror(
                "Không tìm thấy template",
                f"Không tìm thấy file mẫu: {template_key}"
            )
            return

        out_dir = self._ensure_output_dir(
            self.p3_out_dir_var, self.p3_out_dir_lbl,
            "Chọn thư mục lưu báo cáo Phase 3", self._log_p3
        )
        if not out_dir:
            return
        base_name = os.path.splitext(os.path.basename(keynote_path))[0]
        clean_name = base_name.replace("_FACA_English", "").replace("_FACA_Updated", "")
        proj_name = self.p3_project_var.get().strip()
        final_file_name = f"{proj_name}_Executive_Summary.key" if proj_name else f"{clean_name}_Executive_Summary.key"
        out_path = os.path.join(out_dir, final_file_name)

        self.btn_phase3_run.configure(state="disabled")
        self.p3_progress_bar.configure(mode="indeterminate")
        self.p3_progress_bar.start()
        self.p3_log_box.configure(state="normal")
        self.p3_log_box.delete("1.0", "end")
        self.p3_log_box.configure(state="disabled")

        def worker():
            try:
                perf_csv = self.p3_perf_card.file_path
                if not perf_csv and hasattr(self, "perf_card") and self.perf_card.file_path and os.path.exists(self.perf_card.file_path):
                    perf_csv = self.perf_card.file_path

                bench_csv = self.p3_perf_benchmark_card.file_path if (hasattr(self, "p3_perf_benchmark_card") and self.p3_perf_benchmark_card.file_path and os.path.exists(self.p3_perf_benchmark_card.file_path)) else None

                final_key_path = generate_phase3_executive_keynote(
                    input_keynote_path=keynote_path,
                    output_keynote_path=out_path,
                    template_keynote_path=template_key,
                    cover_template_path=cover_template,
                    performance_csv_path=perf_csv if perf_csv else None,
                    benchmark_performance_csv_path=bench_csv,
                    target_mp_rate=target_mp,
                    project_name=proj_name if proj_name else None,
                    log_cb=self._log_p3
                )
                self.after(0, lambda: self._on_phase3_finished(final_key_path, keynote_path))
            except Exception as e:
                self.after(0, lambda err=str(e): self._on_phase3_error(err))

        threading.Thread(target=worker, daemon=True).start()

    def _on_phase3_finished(self, out_path: str, source_keynote: str = ""):
        self.btn_phase3_run.configure(state="normal")
        self.p3_progress_bar.stop()
        self.p3_progress_bar.configure(mode="determinate")
        self.p3_progress_bar.set(1.0)

        source_name = os.path.basename(source_keynote) if source_keynote else "File gốc"
        msg = (
            f"🎉 XUẤT BÁO CÁO TỔNG KẾT EXECUTIVE THÀNH CÔNG!\n\n"
            f"• Cấu trúc file đã ghép nối hoàn chỉnh theo thứ tự:\n"
            f"   1. Trang bìa Cover Slide (Mẫu 3 - Đã cập nhật Tên Project chuẩn font & màu)\n"
            f"   2. Báo cáo tổng kết Executive Summary (Mẫu 2 - Đầy đủ tỷ lệ & mũi tên xu hướng)\n"
            f"   3. Chi tiết trạm từ file gốc ({source_name})\n"
            f"• Bảo toàn nguyên vẹn FACA Tiếng Anh đã sửa: 100%\n\n"
            f"📁 File kết quả:\n{out_path}"
        )
        if messagebox.askyesno("Thành công", f"{msg}\n\nBạn có muốn mở file Keynote này ngay không?"):
            subprocess.run(["open", out_path])

    def _on_phase3_error(self, err_msg: str):
        self.btn_phase3_run.configure(state="normal")
        self.p3_progress_bar.stop()
        self.p3_progress_bar.configure(mode="determinate")
        self.p3_progress_bar.set(0)
        self._log_p3(f"❌ LỖI: {err_msg}")
        messagebox.showerror("Lỗi Tổng Hợp Phase 3", f"Không thể tạo báo cáo tổng hợp:\n\n{err_msg}")

    def _build_right_dashboard(self):
        self.right_panel = ctk.CTkFrame(
            self.body_container,
            corner_radius=10,
            fg_color=("gray95", "gray18")
        )
        self.right_panel.pack(side="left", fill="both", expand=True, padx=(0, 0), pady=0)

        # ── Dashboard Header Bar ────────────────────────────────────────────
        dash_header = ctk.CTkFrame(self.right_panel, fg_color="transparent")
        dash_header.pack(fill="x", padx=14, pady=(10, 6))

        title_box = ctk.CTkFrame(dash_header, fg_color="transparent")
        title_box.pack(side="left")

        ctk.CTkLabel(
            title_box,
            text="📊 BẢNG ĐIỀU KHIỂN & PHÂN TÍCH THỰC TẾ (LIVE INSIGHTS)",
            font=ctk.CTkFont(size=15, weight="bold")
        ).pack(anchor="w")

        self.dashboard_sub_chip = ctk.CTkLabel(
            title_box,
            text="Đang tải dữ liệu...",
            font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray65")
        )
        self.dashboard_sub_chip.pack(anchor="w")

        btn_refresh = ctk.CTkButton(
            dash_header,
            text="🔄 Làm mới",
            width=85,
            height=26,
            font=ctk.CTkFont(size=11),
            fg_color=("gray80", "gray28"),
            text_color=("gray10", "gray90"),
            hover_color=("gray70", "gray35"),
            command=self._load_live_data
        )
        btn_refresh.pack(side="right")

        # ── KPI Cards Grid (4 Scorecards) ──────────────────────────────────
        self.kpi_frame = ctk.CTkFrame(self.right_panel, fg_color="transparent")
        self.kpi_frame.pack(fill="x", padx=12, pady=(0, 6))
        self.kpi_frame.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="kpi")

        self.card_active = self._create_kpi_card(
            self.kpi_frame, col=0, icon="🏭", title="TRẠM HOẠT ĐỘNG",
            val_text="--", sub_text="--", accent=("#0284c7", "#38bdf8")
        )
        self.card_high = self._create_kpi_card(
            self.kpi_frame, col=1, icon="⚠️", title="TRẠM VƯỢT TARGET",
            val_text="--", sub_text="--", accent=("#e11d48", "#fb7185")
        )
        self.card_tested = self._create_kpi_card(
            self.kpi_frame, col=2, icon="📦", title="TỔNG INPUT TEST",
            val_text="--", sub_text="--", accent=("#475569", "#94a3b8")
        )
        self.card_rr = self._create_kpi_card(
            self.kpi_frame, col=3, icon="🎯", title="RETEST RATE TB",
            val_text="--", sub_text="--", accent=("#d97706", "#fbbf24")
        )

        # ── Station Performance Matrix (Middle Section) ─────────────────────
        matrix_header = ctk.CTkFrame(self.right_panel, fg_color="transparent")
        matrix_header.pack(fill="x", padx=14, pady=(6, 2))

        ctk.CTkLabel(
            matrix_header,
            text="🏢 Ma Trận Trạm Kiểm Tra (Click vào trạm để xem chi tiết lỗi bên dưới):",
            font=ctk.CTkFont(size=12, weight="bold")
        ).pack(side="left")

        self.station_count_badge = ctk.CTkLabel(
            matrix_header,
            text="0 trạm",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=("gray85", "gray28"),
            corner_radius=6,
            padx=8, pady=2
        )
        self.station_count_badge.pack(side="left", padx=8)

        # Quick Search Bar
        search_box = ctk.CTkFrame(matrix_header, fg_color="transparent")
        search_box.pack(side="right")
        ctk.CTkLabel(search_box, text="🔍", font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 4))
        self.search_entry = ctk.CTkEntry(
            search_box,
            textvariable=self.search_var,
            placeholder_text="Tìm tên trạm...",
            width=135,
            height=24,
            font=ctk.CTkFont(size=11)
        )
        self.search_entry.pack(side="left")

        # Table Column Headers
        st_col_head = ctk.CTkFrame(self.right_panel, height=24, fg_color=("gray88", "gray25"), corner_radius=6)
        st_col_head.pack(fill="x", padx=14, pady=(2, 2))

        ctk.CTkLabel(st_col_head, text="  #", width=36, anchor="w", font=ctk.CTkFont(size=10, weight="bold")).pack(side="left")
        ctk.CTkLabel(st_col_head, text="Tên Trạm Kiểm Tra", width=220, anchor="w", font=ctk.CTkFont(size=10, weight="bold")).pack(side="left")
        ctk.CTkLabel(st_col_head, text="Input", width=70, anchor="center", font=ctk.CTkFont(size=10, weight="bold")).pack(side="left")
        ctk.CTkLabel(st_col_head, text="Retest", width=65, anchor="center", font=ctk.CTkFont(size=10, weight="bold")).pack(side="left")
        ctk.CTkLabel(st_col_head, text="Retest Rate", width=95, anchor="center", font=ctk.CTkFont(size=10, weight="bold")).pack(side="left")
        ctk.CTkLabel(st_col_head, text="Số Lỗi", width=70, anchor="center", font=ctk.CTkFont(size=10, weight="bold")).pack(side="left")
        ctk.CTkLabel(st_col_head, text="Đánh Giá", width=90, anchor="center", font=ctk.CTkFont(size=10, weight="bold")).pack(side="left")

        # Station List Container
        self.station_scroll = ctk.CTkScrollableFrame(self.right_panel, height=210, corner_radius=6, fg_color=("gray92", "gray20"))
        self.station_scroll.pack(fill="both", expand=True, padx=14, pady=(0, 6))

        # ── Selected Station Drilldown (Bottom Section) ─────────────────────
        drill_header = ctk.CTkFrame(self.right_panel, fg_color="transparent")
        drill_header.pack(fill="x", padx=14, pady=(6, 2))

        self.drilldown_title_lbl = ctk.CTkLabel(
            drill_header,
            text="🔍 Phân Tích Top 5 Lỗi Trạm:",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.drilldown_title_lbl.pack(side="left")

        self.station_option_menu = ctk.CTkOptionMenu(
            drill_header,
            values=["-- Chưa có dữ liệu --"],
            command=self._on_station_dropdown_selected,
            width=280,
            height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
            dropdown_font=ctk.CTkFont(size=11),
            dynamic_resizing=False
        )
        self.station_option_menu.pack(side="left", padx=(8, 12))

        self.drilldown_stats_chip = ctk.CTkLabel(
            drill_header,
            text="",
            font=ctk.CTkFont(size=11),
            text_color=("#0066cc", "#60a5fa")
        )
        self.drilldown_stats_chip.pack(side="left", padx=4)

        # Issues Table Column Headers
        iss_col_head = ctk.CTkFrame(self.right_panel, height=24, fg_color=("gray88", "gray25"), corner_radius=6)
        iss_col_head.pack(fill="x", padx=14, pady=(2, 2))

        ctk.CTkLabel(iss_col_head, text="  #", width=36, anchor="w", font=ctk.CTkFont(size=10, weight="bold")).pack(side="left")
        ctk.CTkLabel(iss_col_head, text="Tên Lỗi (Issue Description)", width=320, anchor="w", font=ctk.CTkFont(size=10, weight="bold")).pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(iss_col_head, text="Số Lượng (Q'ty)", width=95, anchor="center", font=ctk.CTkFont(size=10, weight="bold")).pack(side="left")
        ctk.CTkLabel(iss_col_head, text="Item RR (%)", width=85, anchor="center", font=ctk.CTkFont(size=10, weight="bold")).pack(side="left")
        ctk.CTkLabel(iss_col_head, text="Tỷ Trọng Trong Trạm", width=145, anchor="center", font=ctk.CTkFont(size=10, weight="bold")).pack(side="left")

        # Issues List Container
        self.issues_scroll = ctk.CTkScrollableFrame(self.right_panel, height=210, corner_radius=6, fg_color=("gray92", "gray20"))
        self.issues_scroll.pack(fill="both", expand=True, padx=14, pady=(0, 10))

    def _create_kpi_card(self, parent, col: int, icon: str, title: str, val_text: str, sub_text: str, accent: tuple) -> Dict[str, Any]:
        card = ctk.CTkFrame(parent, corner_radius=8, fg_color=("gray90", "gray22"), border_width=1, border_color=("gray80", "gray30"))
        card.grid(row=0, column=col, padx=4, pady=2, sticky="nsew")

        top_row = ctk.CTkFrame(card, fg_color="transparent")
        top_row.pack(fill="x", padx=10, pady=(6, 0))

        ctk.CTkLabel(top_row, text=icon, font=ctk.CTkFont(size=14)).pack(side="left")
        ctk.CTkLabel(
            top_row,
            text=f" {title}",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=("gray50", "gray65")
        ).pack(side="left")

        val_lbl = ctk.CTkLabel(
            card,
            text=val_text,
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=accent,
            anchor="w"
        )
        val_lbl.pack(fill="x", padx=10, pady=(2, 0))

        sub_lbl = ctk.CTkLabel(
            card,
            text=sub_text,
            font=ctk.CTkFont(size=10),
            text_color=("gray45", "gray60"),
            anchor="w"
        )
        sub_lbl.pack(fill="x", padx=10, pady=(0, 6))

        return {"card": card, "val_lbl": val_lbl, "sub_lbl": sub_lbl, "accent": accent}

    # ── Live Reactive Data Engine ───────────────────────────────────────────
    def _load_live_data(self):
        """Builds in-memory report_data and refreshes dashboard immediately."""
        if not getattr(self, "_initialized", False):
            return
        perf_path = getattr(self, "perf_card", None)
        perf_path = perf_path.file_path if perf_path else ""
        symptoms_path = getattr(self, "symptoms_card", None)
        symptoms_path = symptoms_path.file_path if symptoms_path else ""
        unit_card = getattr(self, "unit_card", None)
        unit_path = unit_card.file_path if (unit_card and self.use_unit_var.get() and os.path.exists(unit_card.file_path)) else None

        if not os.path.exists(perf_path) or not os.path.exists(symptoms_path):
            self.report_data = None
            self._render_empty_state("Vui lòng kéo thả hoặc chọn 2 file: Performance-Breakdown.csv và Retest-Symptoms.csv")
            self.lbl_global_status.configure(text="⚪ Chờ file dữ liệu", text_color="gray")
            return

        grouping_level = self.grouping_mode_var.get()
        raw_prod = self.product_name_var.get().strip().strip("[]").strip() or "Ruby"

        try:
            self.report_data = build_report_data(
                perf_file=perf_path,
                symptoms_file=symptoms_path,
                unit_details_file=unit_path,
                product_name=raw_prod,
                grouping_level=grouping_level,
                top_n=5
            )
            total_st = len(self.report_data.get("stations", []))
            active_st = sum(1 for s in self.report_data.get("stations", []) if s.get("input", 0) > 0)
            self.lbl_global_status.configure(
                text=f"🟢 {active_st}/{total_st} Trạm hoạt động",
                text_color=("#16a34a", "#4ade80")
            )
            # Default to the station with highest retest rate whenever fresh data is loaded
            self.selected_station = None
            self._update_dashboard()
        except Exception as e:
            self.report_data = None
            self._render_empty_state(f"Lỗi đọc file: {str(e)}")
            self.lbl_global_status.configure(text="🔴 Lỗi dữ liệu", text_color=("#dc2626", "#f87171"))

    def _update_dashboard(self):
        """Calculates live metrics, updates scorecards, station matrix and issue drilldown."""
        if not self.report_data:
            return

        try:
            target_rate = float(self.target_rate_var.get().strip()) / 100.0
        except ValueError:
            target_rate = 0.005

        filter_mode = self.station_filter_var.get()
        search_query = self.search_var.get().strip().lower()
        raw_prod = self.product_name_var.get().strip() or "Ruby"

        stations = self.report_data.get("stations", [])
        valid_stations = [s for s in stations if not is_datetime_or_date(s.get("station", ""))]
        active_stations = [s for s in valid_stations if s.get("input", 0) > 0]

        # ── Unique-SN totals & Average Retest Rate ────────────────────────────
        # A single SN flows through many stations → summing per-station inputs
        # over-counts. Use max(input) as the best proxy for unique devices.
        total_input = max((s.get("input", 0) for s in valid_stations), default=0)

        # Retest Rate TB: trung bình cộng retest rate của tất cả các trạm hoạt động
        stations_for_avg = active_stations if active_stations else valid_stations
        avg_rr = (sum(s.get("retest_pct", 0.0) for s in stations_for_avg) / len(stations_for_avg)) if stations_for_avg else 0.0

        # Số lượng retest tương đối tính theo tỷ lệ trung bình
        relative_retest = int(round(total_input * avg_rr))

        high_stations = [s for s in valid_stations if s.get("retest_pct", 0) > target_rate and s.get("input", 0) > 0]

        # Station filtering
        if filter_mode == "has_issues":
            filtered = [s for s in valid_stations if s.get("issues")]
        elif filter_mode == "high_only":
            filtered = [s for s in valid_stations if s.get("retest_pct", 0) > target_rate and s.get("issues")]
        else:
            filtered = valid_stations

        if search_query:
            filtered = [s for s in filtered if search_query in s.get("station", "").lower()]

        # Sort filtered by retest_pct descending
        filtered.sort(key=lambda s: s.get("retest_pct", 0), reverse=True)

        # 1. Update Subtitle Chip
        self.dashboard_sub_chip.configure(
            text=f"🏷️ {raw_prod}  •  Hiển thị: {len(filtered)}/{len(valid_stations)} trạm  •  Target: {target_rate*100:.2f}%"
        )
        self.station_count_badge.configure(text=f"{len(filtered)} trạm")

        # 2. Render 4 KPI Scorecards
        self.card_active["val_lbl"].configure(text=f"{len(active_stations)} / {len(valid_stations)}")
        pct_active = (len(active_stations) / max(1, len(valid_stations))) * 100
        self.card_active["sub_lbl"].configure(text=f"{pct_active:.1f}% trạm có dữ liệu test")

        self.card_high["val_lbl"].configure(text=f"{len(high_stations)} trạm")
        self.card_high["sub_lbl"].configure(text=f"Retest Rate > {target_rate*100:.2f}%")
        high_color = ("#e11d48", "#fb7185") if len(high_stations) > 0 else ("#16a34a", "#4ade80")
        self.card_high["val_lbl"].configure(text_color=high_color)

        self.card_tested["val_lbl"].configure(text=f"{total_input:,}")
        self.card_tested["sub_lbl"].configure(text=f"{relative_retest:,} đơn vị Retest")

        self.card_rr["val_lbl"].configure(text=f"{avg_rr*100:.2f}%")
        highest_st = max(valid_stations, key=lambda s: s.get("retest_pct", 0)) if valid_stations else None
        if highest_st:
            h_name = highest_st.get("station", "")
            h_rate = highest_st.get("retest_pct", 0) * 100
            self.card_rr["sub_lbl"].configure(text=f"Cao nhất: {h_name[:12]} ({h_rate:.2f}%)")
        else:
            self.card_rr["sub_lbl"].configure(text="Chưa có dữ liệu")

        # 3. Ensure a valid selected station & update dropdown menu
        self.option_to_station_map = {}
        self.station_to_option_map = {}
        if filtered:
            option_values = []
            for idx, st in enumerate(filtered, start=1):
                st_name = st.get("station", "")
                st_rate = st.get("retest_pct", 0.0)
                display_str = f"#{idx} {st_name}  ({st_rate*100:.2f}%)"
                self.option_to_station_map[display_str] = st_name
                self.station_to_option_map[st_name] = display_str
                option_values.append(display_str)

            self.station_option_menu.configure(values=option_values, state="normal")

            # Default to highest station (filtered[0]) if not set or invalid
            if not self.selected_station or self.selected_station not in self.station_to_option_map:
                self.selected_station = filtered[0]["station"]

            current_display = self.station_to_option_map.get(self.selected_station, option_values[0])
            self.station_option_menu.set(current_display)
        else:
            self.selected_station = None
            self.station_option_menu.configure(values=["-- Không có trạm phù hợp --"], state="disabled")
            self.station_option_menu.set("-- Không có trạm phù hợp --")

        # 4. Render Station Performance Matrix
        self._render_station_matrix(filtered, target_rate)

        # 5. Render Issues Drilldown
        self._render_issues_drilldown()

    def _render_station_matrix(self, stations: List[Dict[str, Any]], target_rate: float):
        for widget in self.station_scroll.winfo_children():
            widget.destroy()

        self.station_row_widgets = {}

        if not stations:
            empty_lbl = ctk.CTkLabel(
                self.station_scroll,
                text="Không có trạm nào khớp với bộ lọc hiện tại.",
                font=ctk.CTkFont(size=12),
                text_color="gray"
            )
            empty_lbl.pack(pady=30)
            return

        for idx, st in enumerate(stations, start=1):
            st_name = st.get("station", "")
            inp = st.get("input", 0)
            retest = st.get("retest", 0)
            rate = st.get("retest_pct", 0.0)
            issue_count = len(st.get("issues", []))
            tier_info = get_rr_tier(rate, target_rate)

            is_sel = (st_name == self.selected_station)

            row_frame = ctk.CTkFrame(
                self.station_scroll,
                height=32,
                corner_radius=6,
                fg_color=("#bfdbfe", "#1e3a5f") if is_sel else ("gray96", "gray22"),
                border_width=2 if is_sel else 1,
                border_color=("#2563eb", "#60a5fa") if is_sel else ("gray85", "gray30")
            )
            row_frame.pack(fill="x", pady=2, padx=2)
            row_frame.pack_propagate(False)
            self.station_row_widgets[st_name] = row_frame

            # Rank #
            lbl_rank = ctk.CTkLabel(row_frame, text=f"  #{idx}", width=36, anchor="w", font=ctk.CTkFont(size=11, weight="bold"))
            lbl_rank.pack(side="left")

            # Station Name
            lbl_name = ctk.CTkLabel(
                row_frame, text=st_name, width=220, anchor="w",
                font=ctk.CTkFont(size=11, weight="bold" if is_sel else "normal")
            )
            lbl_name.pack(side="left")

            # Input
            lbl_inp = ctk.CTkLabel(row_frame, text=f"{inp:,}", width=70, anchor="center", font=ctk.CTkFont(size=11))
            lbl_inp.pack(side="left")

            # Retest
            lbl_ret = ctk.CTkLabel(row_frame, text=f"{retest:,}", width=65, anchor="center", font=ctk.CTkFont(size=11))
            lbl_ret.pack(side="left")

            # Rate Badge
            rate_badge = ctk.CTkLabel(
                row_frame,
                text=f"{rate*100:.2f}%",
                width=80,
                corner_radius=4,
                fg_color=tier_info["bg"],
                text_color=tier_info["fg"],
                font=ctk.CTkFont(size=11, weight="bold")
            )
            rate_badge.pack(side="left", padx=7)

            # Issue count
            lbl_cnt = ctk.CTkLabel(row_frame, text=f"{issue_count} lỗi", width=70, anchor="center", font=ctk.CTkFont(size=11))
            lbl_cnt.pack(side="left")

            # Tier Evaluation Tag
            lbl_tier = ctk.CTkLabel(
                row_frame,
                text=tier_info["text"],
                width=85,
                anchor="center",
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color=tier_info["accent"]
            )
            lbl_tier.pack(side="left")

            # Click & Hover bindings across all subwidgets
            for w in [row_frame, lbl_rank, lbl_name, lbl_inp, lbl_ret, rate_badge, lbl_cnt, lbl_tier]:
                w.bind("<Button-1>", lambda e, s=st_name: self._select_station(s))

    def _select_station(self, st_name: str):
        if not st_name:
            return
        if self.selected_station == st_name:
            if hasattr(self, "station_option_menu") and st_name in self.station_to_option_map:
                self.station_option_menu.set(self.station_to_option_map[st_name])
            return
        self.selected_station = st_name

        # Synchronize select-option dropdown
        if hasattr(self, "station_option_menu") and st_name in self.station_to_option_map:
            self.station_option_menu.set(self.station_to_option_map[st_name])

        # Update visuals of all rows
        for name, frame in self.station_row_widgets.items():
            if name == st_name:
                frame.configure(
                    fg_color=("#bfdbfe", "#1e3a5f"),
                    border_width=2,
                    border_color=("#2563eb", "#60a5fa")
                )
            else:
                frame.configure(
                    fg_color=("gray96", "gray22"),
                    border_width=1,
                    border_color=("gray85", "gray30")
                )

        self._render_issues_drilldown()

    def _on_station_dropdown_selected(self, choice_text: str):
        st_name = self.option_to_station_map.get(choice_text, choice_text)
        if st_name and st_name != self.selected_station:
            self._select_station(st_name)

    def _render_issues_drilldown(self):
        for widget in self.issues_scroll.winfo_children():
            widget.destroy()

        if not self.report_data or not self.selected_station:
            self.drilldown_title_lbl.configure(text="🔍 Phân Tích Chi Tiết Top Lỗi Trạm:")
            self.drilldown_stats_chip.configure(text="Chưa chọn trạm")
            return

        station_obj = None
        for s in self.report_data.get("stations", []):
            if s.get("station") == self.selected_station:
                station_obj = s
                break

        if not station_obj:
            return

        st_name = station_obj.get("station", "")
        inp = station_obj.get("input", 0)
        retest = station_obj.get("retest", 0)
        rate = station_obj.get("retest_pct", 0.0)
        issues = station_obj.get("issues", [])

        # Mỗi trạm chỉ lấy top 5 lỗi cao nhất
        table_mode = self.table_item_mode_var.get()
        if table_mode == "all":
            disp_issues = issues[:5] # Vẫn giới hạn tối đa top 5 theo yêu cầu
        elif table_mode == "custom":
            try:
                c_lim = int(self.table_item_custom_var.get().strip())
                disp_issues = issues[:c_lim] if c_lim > 0 else issues[:5]
            except ValueError:
                disp_issues = issues[:5]
        else:
            disp_issues = issues[:5]

        self.drilldown_title_lbl.configure(text=f"🔍 Phân Tích Top {len(disp_issues)} Lỗi Trạm:")
        self.drilldown_stats_chip.configure(
            text=f"Input: {inp:,}  |  Retest: {retest:,}  |  Rate: {rate*100:.2f}%  |  Top {len(disp_issues)} lỗi cao nhất"
        )

        if not disp_issues:
            ctk.CTkLabel(
                self.issues_scroll,
                text="Trạm này không ghi nhận lỗi retest nào (100% Pass).",
                font=ctk.CTkFont(size=12),
                text_color="gray"
            ).pack(pady=25)
            return

        for idx, iss in enumerate(disp_issues, start=1):
            iss_name = iss.get("issue_name", "")
            qty = iss.get("item_qty", 0)
            item_rr = iss.get("item_rr", 0.0)

            # Impact ratio inside station
            pct_of_station = (qty / max(1, retest)) * 100.0

            i_row = ctk.CTkFrame(
                self.issues_scroll,
                height=30,
                corner_radius=4,
                fg_color=("gray96", "gray22"),
                border_width=1,
                border_color=("gray85", "gray30")
            )
            i_row.pack(fill="x", pady=2, padx=2)
            i_row.pack_propagate(False)

            # Rank #
            ctk.CTkLabel(i_row, text=f"  #{idx}", width=36, anchor="w", font=ctk.CTkFont(size=11, weight="bold")).pack(side="left")

            # Issue Description
            ctk.CTkLabel(
                i_row,
                text=iss_name,
                width=320,
                anchor="w",
                font=ctk.CTkFont(size=11)
            ).pack(side="left", fill="x", expand=True)

            # Q'ty
            ctk.CTkLabel(i_row, text=f"{qty:,}", width=95, anchor="center", font=ctk.CTkFont(size=11, weight="bold")).pack(side="left")

            # Item RR%
            ctk.CTkLabel(i_row, text=f"{item_rr*100:.2f}%", width=85, anchor="center", font=ctk.CTkFont(size=11)).pack(side="left")

            # Mini Progress Bar + % Label
            impact_box = ctk.CTkFrame(i_row, width=145, fg_color="transparent")
            impact_box.pack(side="left", padx=4)
            impact_box.pack_propagate(False)

            pb = ctk.CTkProgressBar(impact_box, width=70, height=8)
            pb.pack(side="left", padx=(4, 6))
            pb.set(min(1.0, max(0.0, pct_of_station / 100.0)))

            if idx == 1:
                pb.configure(progress_color="#ef4444")
            elif idx <= 3:
                pb.configure(progress_color="#f97316")
            else:
                pb.configure(progress_color="#3b82f6")

            ctk.CTkLabel(
                impact_box,
                text=f"{pct_of_station:.1f}%",
                width=45,
                anchor="w",
                font=ctk.CTkFont(size=10, weight="bold")
            ).pack(side="left")

    def _render_empty_state(self, message: str):
        self.selected_station = None
        self.option_to_station_map = {}
        self.station_to_option_map = {}
        self.dashboard_sub_chip.configure(text="Chưa có dữ liệu")
        self.station_count_badge.configure(text="0 trạm")
        self.drilldown_title_lbl.configure(text="🔍 Phân Tích Top 5 Lỗi Trạm:")
        if hasattr(self, "station_option_menu"):
            self.station_option_menu.configure(values=["-- Chưa có dữ liệu --"], state="disabled")
            self.station_option_menu.set("-- Chưa có dữ liệu --")
        self.drilldown_stats_chip.configure(text="")

        for k in [self.card_active, self.card_high, self.card_tested, self.card_rr]:
            k["val_lbl"].configure(text="--", text_color=k["accent"])
            k["sub_lbl"].configure(text="--")

        for w in self.station_scroll.winfo_children():
            w.destroy()
        for w in self.issues_scroll.winfo_children():
            w.destroy()

        ctk.CTkLabel(
            self.station_scroll,
            text=f"📂 {message}",
            font=ctk.CTkFont(size=12),
            text_color="gray"
        ).pack(pady=40)

    # ── Instant Event Listeners ─────────────────────────────────────────────
    def _on_station_filter_changed(self):
        """Immediately filters the station list."""
        self._update_dashboard()

    def _on_grouping_mode_changed(self):
        """Immediately recalculates data with new grouping and refreshes dashboard."""
        self._load_live_data()

    def _on_target_rate_changed(self):
        """Immediately recalculates target threshold metrics."""
        self._update_dashboard()

    def _on_product_name_changed(self):
        """Updates product header immediately and syncs default project to Phase 2/3 if unset."""
        prod = self.product_name_var.get().strip().strip("[]").strip()
        if prod:
            if not self.p2_project_var.get().strip():
                self.p2_project_var.set(prod)
            if not self.p3_project_var.get().strip():
                self.p3_project_var.set(prod)
        self._update_dashboard()

    def _on_search_changed(self):
        """Filters station list live as user types."""
        self._update_dashboard()

    def _on_files_changed(self):
        """Reloads live data whenever a file is chosen or cleared."""
        if hasattr(self, "p3_perf_card") and not self.p3_perf_card.file_path:
            if hasattr(self, "perf_card") and self.perf_card.file_path and os.path.exists(self.perf_card.file_path):
                self.p3_perf_card.set_file(self.perf_card.file_path)
        self._load_live_data()

    def _on_theme_changed(self, mode: str):
        ctk.set_appearance_mode(mode)

    def _on_table_mode_changed(self):
        if self.table_item_mode_var.get() == "custom":
            self.table_custom_entry.configure(state="normal")
            self.table_custom_entry.focus_set()
        else:
            self.table_custom_entry.configure(state="disabled")
        self._render_issues_drilldown()

    def _on_toggle_unit_details(self):
        if self.use_unit_var.get():
            self.unit_card.pack(fill="x", padx=12, pady=3)
        else:
            self.unit_card.pack_forget()
        self._load_live_data()

    # ── Output folder selection (shared by Phase 1/2/3) ─────────────────────
    def _refresh_dir_label(self, lbl, d: str):
        if d:
            home = os.path.expanduser("~")
            shown = ("~" + d[len(home):]) if d.startswith(home) else d
            lbl.configure(text=f"📁 {shown}", text_color=("#0066cc", "#60a5fa"))
        else:
            lbl.configure(text="📁 Chưa chọn thư mục lưu",
                          text_color=("#c2410c", "#fb923c"))

    def _ask_output_dir(self, var, lbl, title: str, log_fn) -> Optional[str]:
        init = var.get() if var.get() and os.path.isdir(var.get()) else self._last_output_dir
        if not os.path.isdir(init):
            init = os.path.expanduser("~")
        d = filedialog.askdirectory(title=title, initialdir=init, mustexist=False)
        if not d:
            return None
        var.set(d)
        self._last_output_dir = d
        self._refresh_dir_label(lbl, d)
        log_fn(f"-> {title}: {d}")
        return d

    def _ensure_output_dir(self, var, lbl, title: str, log_fn) -> Optional[str]:
        """Returns a writable output folder, asking the user if none was chosen yet."""
        d = var.get().strip()
        if not d:
            d = self._ask_output_dir(var, lbl, title, log_fn)
            if not d:
                messagebox.showinfo("Chưa chọn thư mục", "Vui lòng chọn thư mục lưu file để tiếp tục.")
                return None
        try:
            os.makedirs(d, exist_ok=True)
        except OSError as e:
            messagebox.showerror("Không thể ghi thư mục", f"Không tạo/ghi được thư mục:\n{d}\n\n{e}")
            return None
        if not os.access(d, os.W_OK):
            messagebox.showerror("Không có quyền ghi", f"Không có quyền ghi vào thư mục:\n{d}\nVui lòng chọn thư mục khác.")
            return None
        return os.path.abspath(d)

    def _choose_output_dir(self):
        self._ask_output_dir(self.out_dir_var, self.out_dir_lbl, "Chọn thư mục lưu báo cáo Phase 1", self.log)

    def _choose_p2_output_dir(self):
        self._ask_output_dir(self.p2_out_dir_var, self.p2_out_dir_lbl, "Chọn thư mục lưu báo cáo Phase 2", self._log_p2)

    def _choose_p3_output_dir(self):
        self._ask_output_dir(self.p3_out_dir_var, self.p3_out_dir_lbl, "Chọn thư mục lưu báo cáo Phase 3", self._log_p3)

    def _on_global_drop(self, event):
        paths = self.tk.splitlist(event.data)
        for p in paths:
            if not os.path.exists(p):
                continue
            fname_lower = os.path.basename(p).lower()
            if "performance" in fname_lower:
                self.perf_card.set_file(p)
                if hasattr(self, "p3_perf_card") and not self.p3_perf_card.file_path:
                    self.p3_perf_card.set_file(p)
                self.log(f"-> Nhận diện Performance-Breakdown: {os.path.basename(p)}")
            elif "symptom" in fname_lower or "retest" in fname_lower:
                self.symptoms_card.set_file(p)
                self.log(f"-> Nhận diện Retest-Symptoms: {os.path.basename(p)}")
            elif "unit" in fname_lower or "detail" in fname_lower:
                self.use_unit_var.set(True)
                self._on_toggle_unit_details()
                self.unit_card.set_file(p)
                self.log(f"-> Nhận diện unitTestDetails: {os.path.basename(p)}")
            elif p.endswith(".csv"):
                if not self.perf_card.file_path:
                    self.perf_card.set_file(p)
                elif not self.symptoms_card.file_path:
                    self.symptoms_card.set_file(p)
        self._load_live_data()

    def log(self, message: str):
        def _append():
            if hasattr(self, "log_text") and self.log_text:
                self.log_text.insert("end", message + "\n")
                self.log_text.see("end")
        self.after(0, _append)

    def _set_progress(self, val: float):
        self.after(0, lambda: self.progress_bar.set(val))

    # ── Report Generation Thread ────────────────────────────────────────────
    def _start_generation(self, gen_excel: bool, gen_keynote: bool):
        perf_path = self.perf_card.file_path
        symptoms_path = self.symptoms_card.file_path

        if not os.path.exists(perf_path):
            messagebox.showerror("Lỗi", "Vui lòng chọn hoặc kéo thả file Performance-Breakdown.csv hợp lệ!")
            return
        if not os.path.exists(symptoms_path):
            messagebox.showerror("Lỗi", "Vui lòng chọn hoặc kéo thả file Retest-Symptoms.csv hợp lệ!")
            return

        unit_path = self.unit_card.file_path if (self.use_unit_var.get() and os.path.exists(self.unit_card.file_path)) else None

        template_key = get_resource_path("Sample output/Sample-keynote1.key")
        if not os.path.exists(template_key):
            cand = get_resource_path("Sample-keynote1.key")
            if os.path.exists(cand):
                template_key = cand

        if gen_keynote and not os.path.exists(template_key):
            messagebox.showerror("Lỗi", f"Không tìm thấy file Keynote Template mẫu: {template_key}")
            return

        out_dir = self._ensure_output_dir(
            self.out_dir_var, self.out_dir_lbl,
            "Chọn thư mục lưu báo cáo Phase 1", self.log
        )
        if not out_dir:
            return

        raw_prod = self.product_name_var.get().strip().strip("[]").strip() or "Ruby"
        try:
            target_rate = float(self.target_rate_var.get().strip()) / 100.0
        except ValueError:
            target_rate = 0.005

        filter_mode = self.station_filter_var.get()
        chart_mode = self.chart_item_mode_var.get()
        chart_limit = 5 if chart_mode == "top5" else None

        table_mode = self.table_item_mode_var.get()
        if table_mode == "top5":
            table_limit = 5
        elif table_mode == "custom":
            try:
                table_limit = int(self.table_item_custom_var.get().strip())
                if table_limit <= 0:
                    table_limit = None
            except ValueError:
                table_limit = 5
        else:
            table_limit = None

        grouping_level = self.grouping_mode_var.get()

        self.btn_gen_excel.configure(state="disabled")
        self.btn_gen_keynote.configure(state="disabled")
        self.btn_gen_all.configure(state="disabled")
        self.progress_bar.set(0.1)

        t = threading.Thread(
            target=self._run_generation_thread,
            args=(
                perf_path, symptoms_path, unit_path, template_key, out_dir,
                gen_excel, gen_keynote, raw_prod, target_rate, filter_mode,
                chart_limit, table_limit, grouping_level
            ),
            daemon=True
        )
        t.start()

    def _run_generation_thread(
        self,
        perf_path: str,
        symptoms_path: str,
        unit_path: Optional[str],
        template_key: str,
        out_dir: str,
        gen_excel: bool,
        gen_keynote: bool,
        raw_prod: str,
        target_rate: float,
        filter_mode: str,
        chart_limit: Optional[int],
        table_limit: Optional[int],
        grouping_level: str
    ):
        try:
            self.log("--- BẮT ĐẦU XỬ LÝ BÁO CÁO ---")
            self.log(f"Sản phẩm: {raw_prod}")

            # Phase 1: Đọc CSV
            self._set_progress(0.15)
            report_data = build_report_data(
                perf_file=perf_path,
                symptoms_file=symptoms_path,
                unit_details_file=unit_path,
                product_name=raw_prod,
                grouping_level=grouping_level,
                top_n=5
            )
            total_st = len(report_data.get("stations", []))
            active_st = sum(1 for s in report_data.get("stations", []) if s.get("input", 0) > 0)
            self.log(f"-> Đọc xong {total_st} trạm ({active_st} trạm có dữ liệu test).")

            # Xác định danh sách trạm xuất báo cáo
            selected_st: Optional[List[str]] = None
            if filter_mode == "has_issues":
                selected_st = [
                    s["station"] for s in report_data.get("stations", [])
                    if s.get("issues") and not is_datetime_or_date(s.get("station", ""))
                ]
            elif filter_mode == "high_only":
                selected_st = [
                    s["station"] for s in report_data.get("stations", [])
                    if s.get("retest_pct", 0) > target_rate and s.get("issues")
                    and not is_datetime_or_date(s.get("station", ""))
                ]
            else:
                selected_st = [
                    s["station"] for s in report_data.get("stations", [])
                    if not is_datetime_or_date(s.get("station", ""))
                ]

            # Phase 2: Tính toán trong bộ nhớ (In-memory compute)
            self._set_progress(0.35)
            excel_wb = None
            keynote_payload = None

            if gen_excel:
                self.log("Đang tính toán cấu trúc Excel trong bộ nhớ...")
                excel_wb = build_excel_workbook(
                    report_data,
                    table_items_limit=table_limit,
                    selected_stations=selected_st,
                    target_mp_rate=target_rate
                )
                self.log("-> Bảng tính Excel sẵn sàng.")

            self._set_progress(0.50)
            if gen_keynote:
                self.log("Đang chuẩn bị payload slide Keynote trong bộ nhớ...")
                keynote_payload = prepare_keynote_payload(
                    report_data,
                    selected_stations=selected_st,
                    table_items_limit=table_limit,
                    chart_items_limit=chart_limit
                )
                n_slides = sum(
                    1 + p.get("num_overflow_slides", 0)
                    for p in keynote_payload["stations_payload"]
                )
                self.log(f"-> Payload Keynote sẵn sàng ({n_slides} slides).")

            # Phase 3: Ghi file nguyên tử (Write-Last)
            self._set_progress(0.65)
            if gen_excel and excel_wb is not None:
                if table_limit == 5:
                    excel_prefix = "RR_Top5_Issue"
                elif table_limit is not None and table_limit > 0:
                    excel_prefix = f"RR_Top{table_limit}_Issue"
                else:
                    excel_prefix = "RR_All_Issue"
                excel_out_path = os.path.join(out_dir, f"{excel_prefix}_{raw_prod}.xlsx")
                self.log(f"Đang ghi file Excel: {os.path.basename(excel_out_path)}...")
                excel_wb.save(excel_out_path)
                self.log(f"-> Xuất Excel thành công: {excel_out_path}")

            self._set_progress(0.80)
            if gen_keynote and keynote_payload is not None:
                key_out_path = os.path.join(out_dir, f"Retest_Breakdown_{raw_prod}.key")
                self.log("Đang sinh slide Keynote qua AppleScript (làm việc trên file tạm)...")
                _write_keynote_file(
                    keynote_payload,
                    template_path=os.path.abspath(template_key),
                    output_path=key_out_path,
                    target_mp_rate=target_rate,
                    chart_items_limit=chart_limit
                )
                self.log(f"-> Xuất Keynote thành công: {key_out_path}")

            self._set_progress(1.0)
            self.log("=== HOÀN TẤT TẠO BÁO CÁO THÀNH CÔNG ===")
            self.after(0, lambda: messagebox.showinfo("Thành công", f"Đã xuất báo cáo thành công vào thư mục:\n{out_dir}"))

        except Exception as e:
            err_msg = str(e)
            self.log(f"LỖI: {err_msg}")
            self.after(0, lambda m=err_msg: messagebox.showerror("Lỗi Xử Lý", f"Đã có lỗi xảy ra:\n{m}"))

        finally:
            def _reset_btn():
                self.btn_gen_excel.configure(state="normal")
                self.btn_gen_keynote.configure(state="normal")
                self.btn_gen_all.configure(state="normal")
            self.after(0, _reset_btn)


def run_app():
    app = ReportApp()
    app.mainloop()
