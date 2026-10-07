# SỔ TAY HƯỚNG DẪN CÀI ĐẶT VÀ SỬ DỤNG 0.5%hopeless 📖

> **0.5%hopeless** là phần mềm tự động hoá phân tích dữ liệu thử nghiệm phần cứng (Hardware Test Retest Report Automation), xuất báo cáo bảng tính Excel, đồng bộ và định dạng FACA (Root Cause / Corrective Action / Check Point), dịch thuật kỹ thuật bằng AI Offline và ghép nối bài thuyết trình Keynote chuẩn công nghiệp sản xuất (Foxconn / Apple OEM).

---

## 📑 MỤC LỤC
1. [Dành cho Người Dùng Cuối (Mở File .dmg / .zip / .app)](#1-dành-cho-người-dùng-cuối-mở-bản-đóng-gói-app--dmg)
2. [Xử lý Cảnh báo Gatekeeper trên macOS](#2-xử-lý-cảnh-báo-gatekeeper-trên-macos)
3. [Dành cho Kỹ sư & Lập trình viên (Cài đặt từ Mã Nguồn)](#3-dành-cho-kỹ-sư--lập-trình-viên-cài-đặt-từ-mã-nguồn)
4. [Hướng dẫn Chi Tiết Sử Dụng 3 Phase](#4-hướng-dẫn-chi-tiết-sử-dụng-3-phase)
   - [Phase 1: Phân tích Log & Tạo Báo Cáo Ban Đầu](#phase-1-phân-tích-log--tạo-báo-cáo-ban-đầu)
   - [Phase 2: Đồng Bộ FACA & Dịch Tiếng Anh Bằng AI Offline](#phase-2-đồng-bộ-faca--dịch-tiếng-anh-bằng-ai-offline)
   - [Phase 3: Tạo Executive Summary & Ghép Slide Hoàn Chỉnh](#phase-3-tạo-executive-summary--ghép-slide-hoàn-chỉnh)
5. [Câu Hỏi Thường Gặp & Xử Lý Sự Cố (FAQ)](#5-câu-hỏi-thường-gặp--xử-lý-sự-cố-faq)

---

## 1. DÀNH CHO NGƯỜI DÙNG CUỐI (Mở bản đóng gói .app / .dmg)

Nếu bạn nhận được tệp phát hành từ đồng nghiệp, bạn sẽ nhận được một trong hai định dạng:
- **Tệp đĩa cài đặt:** `0.5%hopeless_Mac_Full_AI.dmg`
- **Tệp nén:** `0.5%hopeless_Mac_Full_AI.zip`

### Các bước mở ứng dụng:
1. **Nếu là file `.dmg`:** Bấm đúp vào file `.dmg` để mở ổ đĩa ảo ➔ Kéo thả biểu tượng `0.5%hopeless.app` vào thư mục `Applications` (hoặc kéo ra Desktop).
2. **Nếu là file `.zip`:** Bấm đúp để giải nén ➔ Bạn sẽ nhận được thư mục chứa `0.5%hopeless.app` và file `Mo_App_Lan_Dau.command`.

---

## 2. XỬ LÝ CẢNH BÁO GATEKEEPER TRÊN MACOS

### ⚠️ Vì sao macOS báo "Không thể mở vì nghi ngờ phần mềm độc hại"?
Đây là tính năng bảo vệ an toàn mặc định (Gatekeeper) của macOS đối với các phần mềm tải về từ nội bộ (qua Google Drive, Zalo, Slack,...) chưa mua chứng chỉ Apple Developer $99/năm.  
Ứng dụng **chạy 100% offline**, không kết nối ra ngoài Internet và an toàn tuyệt đối.

### 👉 Bạn chỉ cần chọn 1 trong các cách sau để mở lần đầu:

#### Cách 1 (Nhanh nhất - Chạy file kích hoạt đi kèm):
- Trong thư mục giải nén, bấm đúp chuột vào file **`Mo_App_Lan_Dau.command`**.
- Cửa sổ Terminal sẽ tự động chạy trong 1 giây để gỡ bỏ cờ cách ly (`quarantine`), cấp quyền thực thi cho ứng dụng và bộ máy AI, sau đó tự động mở ứng dụng lên.
- *Từ lần sau, bạn chỉ cần bấm đúp trực tiếp vào `0.5%hopeless.app` để mở.*

#### Cách 2 (Dùng chuột phải - Chuẩn macOS):
1. Bấm **chuột phải** (hoặc giữ phím `Control` rồi click) vào biểu tượng `0.5%hopeless.app`.
2. Chọn **Open** (Mở) từ menu ngữ cảnh.
3. Hộp thoại hiện lên, bấm nút **Open** (Mở) để xác nhận.

#### Cách 3 (Dành cho macOS Sequoia 15 / Sonoma 14):
1. Bấm đúp vào app (khi bị chặn thông báo, bấm **OK**).
2. Vào **Cài đặt hệ thống** (System Settings) ➔ **Quyền riêng tư & Bảo mật** (Privacy & Security).
3. Cuộn xuống mục **Bảo mật** (Security) ➔ Bấm nút **Vẫn mở** (Open Anyway) và xác thực vân tay / mật khẩu.

#### Cách 4 (Dùng lệnh Terminal 1 dòng):
Mở ứng dụng Terminal và dán lệnh sau rồi bấm Enter:
```bash
xattr -cr /path/to/0.5%hopeless.app
```
*(Mẹo: Bạn chỉ cần gõ `xattr -cr ` rồi kéo thả app vào cửa sổ Terminal).*

---

## 3. DÀNH CHO KỸ SƯ & LẬP TRÌNH VIÊN (Cài đặt từ mã nguồn)

Nếu bạn muốn chạy trực tiếp từ mã nguồn Python hoặc chỉnh sửa, đóng góp tính năng:

### Yêu cầu hệ thống:
- Hệ điều hành: **macOS 12.0 trở lên** (Hỗ trợ cả Apple Silicon M1-M4 và Intel).
- Đã cài đặt **Python 3.10 trở lên** (Khuyên dùng Python 3.10 hoặc 3.11).
- Đã cài đặt phần mềm **Keynote.app** của Apple.

### Các bước cài đặt:

```bash
# 1. Di chuyển vào thư mục dự án
cd "Report keynote:excel"

# 2. Tạo môi trường ảo Python
python3 -m venv venv

# 3. Kích hoạt môi trường ảo
source venv/bin/activate

# 4. Nâng cấp pip và cài đặt thư viện phụ thuộc
pip install --upgrade pip
pip install -r requirements.txt

# 5. Khởi chạy ứng dụng
python3 main.py
```

### Cách đóng gói ra bản .app / .dmg:
Khi muốn đóng gói toàn bộ app kèm AI Offline để gửi cho người khác:
```bash
chmod +x build_app.sh
./build_app.sh
```
File đóng gói hoàn chỉnh sẽ xuất hiện tại thư mục `dist/0.5%hopeless_Mac_Full_AI.dmg`.

---

## 4. HƯỚNG DẪN CHI TIẾT SỬ DỤNG 3 PHASE

Giao diện ứng dụng được chia thành 3 tab tương ứng với 3 giai đoạn của quy trình làm việc:

---

### Phase 1: Phân tích Log & Tạo Báo Cáo Ban Đầu

**Mục tiêu:** Đọc file raw log test, tính Retest Rate, tìm Top 5 Issue của từng trạm và tạo bộ khung file Excel + Keynote chi tiết.

1. **Bước 1 (Chọn File Đầu Vào):**
   - Bấm **"Chọn File Log Test"** hoặc **kéo thả** file `.csv` hoặc `.xlsx` log test vào khung tiếp nhận.
2. **Bước 2 (Điền Thông Tin Dự Án):**
   - Nhập **Tên Dự Án (Project Name)** (ví dụ: `B589`, `N104`,...).
   - Nhập **Giai đoạn Build** (ví dụ: `PVT`, `EVT`, `MP`).
3. **Bước 3 (Chọn Thư Mục Xuất):**
   - Chọn thư mục nơi bạn muốn lưu các file báo cáo đầu ra.
4. **Bước 4 (Thực Hiện):**
   - Bấm nút **"🚀 Chạy Phân Tích & Tạo Báo Cáo"**.
   - Theo dõi thanh tiến trình và nhật ký xử lý.
   - Khi hoàn tất, app sẽ tự động tạo:
     - `..._Top5_Issue.xlsx`: File Excel thống kê chi tiết từng trạm, có 2 cột trống **Category (Cột L)** và **FACA (Cột M)**.
     - `..._Detail_Report.key`: File bài thuyết trình Keynote chứa các bảng lỗi chi tiết theo từng slide trạm test.

---

### Phase 2: Đồng Bộ FACA & Dịch Tiếng Anh Bằng AI Offline

**Mục tiêu:** Sau khi kỹ sư điền thông tin nguyên nhân lỗi (Root Cause) và hành động khắc phục (Corrective Action) vào file Excel, Phase 2 sẽ đưa toàn bộ dữ liệu này vào đúng các slide Keynote và dịch tự động sang Tiếng Anh kỹ thuật.

1. **Bước 1 (Điền Dữ Liệu Vào Excel):**
   - Mở file Excel tạo ra từ Phase 1.
   - Điền nguyên nhân lỗi vào cột **Category (L)** (ví dụ: `Fixture`, `Operator`, `Component`,...).
   - Điền chi tiết nguyên nhân và hành động vào cột **FACA (M)** (có thể viết bằng tiếng Việt hoặc tiếng Trung).
   - Lưu và đóng file Excel.
2. **Bước 2 (Nạp File Vào Ứng Dụng):**
   - Tại Tab Phase 2, chọn hoặc kéo thả file **Excel nguồn** (đã điền FACA).
   - Chọn hoặc kéo thả file **Keynote đích** (file chi tiết từ Phase 1).
3. **Bước 3 (Thiết Lập Chế Độ Đồng Bộ):**
   - **Ưu tiên Excel (Mặc định):** Ghi đè dữ liệu mới từ Excel vào Keynote.
   - **Ưu tiên Keynote:** Giữ lại các ô Keynote đã có, chỉ bổ sung những ô còn trống.
   - **Hợp nhất cả hai:** Ghép nối nội dung cả hai nếu có xung đột.
4. **Bước 4 (Dịch Tiếng Anh Bằng AI Offline):**
   - Tích chọn ô vuông **"🌐 Tạo bản sao Tiếng Anh (*_FACA_English.key)"**.
   - Bộ máy AI nội bộ (Qwen2.5 3B) sẽ tự động nạp vào Metal GPU và chuyển đổi toàn bộ FACA sang chuẩn:
     ```text
     {Mô tả Root Cause}. CA: {Hành động Corrective Action}. CP: {Thời điểm Check Point hoặc Daily}
     ```
5. **Bước 5 (Thực Hiện):**
   - Bấm nút **"🔄 Đồng Bộ & Dịch FACA"**.
   - Ứng dụng sẽ sinh ra 2 tệp Keynote:
     - `..._FACA_Updated.key`: Bản tiếng gốc đã đồng bộ.
     - `..._FACA_English.key`: Bản tiếng Anh chuẩn mực sẵn sàng cho báo cáo khách hàng/quốc tế.

---

### Phase 3: Tạo Executive Summary & Ghép Slide Hoàn Chỉnh

**Mục tiêu:** Tự động quét toàn bộ bài thuyết trình chi tiết, tính tỷ lệ Retest toàn dự án, tạo slide Trang bìa (Cover - Mẫu 3) và slide Báo cáo điều hành (Executive Summary - Mẫu 2), ghép nối tất cả thành một bài thuyết trình hoàn chỉnh duy nhất.

1. **Bước 1 (Nạp File Keynote):**
   - Chọn file Keynote chi tiết đã hoàn thiện từ Phase 2 (`..._FACA_English.key` hoặc `..._FACA_Updated.key`).
2. **Bước 2 (Điền Thông Tin Header & Build):**
   - Nhập **Tên Dự Án** (Project): ví dụ `J517`.
   - Nhập **Giai đoạn Build**: ví dụ `PVT Retest Daily Report`.
   - Chọn **Ngày báo cáo** (Date): ví dụ `2026-10-07`.
3. **Bước 3 (File Performance - Tùy chọn):**
   - Nếu có file kiểm tra hiệu năng hệ thống test, tải lên tại mục này (không bắt buộc, nếu không có app vẫn tổng hợp đầy đủ số liệu).
4. **Bước 4 (Thực Hiện):**
   - Bấm nút **"📊 Tạo Executive Summary & Ghép Slide Hoàn Chỉnh"**.
   - Hệ thống sẽ tự động trích xuất chính xác Retest Rate từng trạm, đối chiếu chéo số lượng test, dựng bảng tổng kết Mẫu 2, dựng bìa Mẫu 3 và ghép nối lại.
   - File kết quả cuối cùng: `..._Executive_Summary_Final.key` sẵn sàng để bạn đem trình chiếu.

---

## 5. CÂU HỎI THƯỜNG GẶP & XỬ LÝ SỰ CỐ (FAQ)

### ❓ Câu hỏi 1: Lỗi "Keynote gặp lỗi AppleScript -600"?
- **Nguyên nhân:** Ứng dụng Keynote chưa được bật hoặc macOS chưa cấp quyền cho `0.5%hopeless` gửi Apple Events tới Keynote.
- **Cách khắc phục:**
  1. Mở sẵn ứng dụng Keynote trên máy.
  2. Vào `Cài đặt hệ thống` ➔ `Quyền riêng tư & Bảo mật` ➔ `Tự động hoá` (Automation) ➔ Đảm bảo đã bật công tắc cho phép ứng dụng điều khiển **Keynote**.

### ❓ Câu hỏi 2: Gửi cho người khác máy họ không dịch sang Tiếng Anh được?
- **Nguyên nhân:** Người nhận giải nén và mở bằng công cụ của bên thứ ba khiến các file nhị phân của AI (`ollama`, `llama-server`) bị tước quyền thực thi hoặc bị Gatekeeper cách ly.
- **Cách khắc phục:**
  - Hướng dẫn người nhận chạy file **`Mo_App_Lan_Dau.command`** trong thư mục ứng dụng để cấp quyền đầy đủ 100%.

### ❓ Câu hỏi 3: Tỷ lệ Retest ở Phase 3 có bị hiển thị nhầm 0.00% không?
- **Trả lời:** Không. Bộ phân tích `_parse_rate` của ứng dụng đã được trang bị cơ chế tự động nhận diện thông minh đa vùng:
  - Hỗ trợ dấu phẩy thập phân kiểu Việt Nam/Châu Âu (`0,0127`).
  - Hỗ trợ dấu chấm thập phân kiểu Mỹ (`1.27%`).
  - Hỗ trợ tỷ số số lượng (`34R / 5343T`).
  - Tự động đối chiếu chéo số lượng mẫu để đảm bảo không bao giờ bị rơi về 0.00% ngoài ý muốn.

### ❓ Câu hỏi 4: Máy tính không có Internet có dùng được tính năng dịch AI không?
- **Trả lời:** **Có, hoàn toàn 100% offline.** 
  Mô hình ngôn ngữ lớn Qwen2.5 3B đã được nhúng sẵn cùng với engine suy luận GPU Metal bên trong bộ cài. Máy tính không cần kết nối mạng hay cài thêm bất cứ phần mềm AI nào khác.

---

*Tài liệu được cập nhật tự động đồng bộ theo phiên bản mới nhất của dự án 0.5%hopeless.*
