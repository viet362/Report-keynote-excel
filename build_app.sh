#!/bin/bash
# ==============================================================================
# Script đóng gói tự động 0.5%hopeless cho macOS (Bản Tích hợp Full AI)
# ==============================================================================
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "=========================================================="
echo "🚀 BẮT ĐẦU ĐÓNG GÓI 0.5%hopeless (FULL AI)..."
echo "=========================================================="

APP_NAME="0.5%hopeless"
SPEC_FILE="0.5%hopeless.spec"
PKG_NAME="0.5%hopeless_Mac_Full_AI"

# 1. Dọn dẹp bản build cũ
echo "1. Dọn dẹp thư mục build cũ..."
rm -rf build "dist/$APP_NAME" "dist/$APP_NAME.app" "dist/$PKG_NAME" "dist/$PKG_NAME.zip" "dist/$PKG_NAME.dmg"

# 2. Chạy PyInstaller
echo "2. Tiến hành đóng gói qua PyInstaller..."
pyinstaller --noconfirm "$SPEC_FILE"

# 3. Sao chép tài nguyên AI (Ollama + Models) vào trong .app bundle
echo "3. Nhúng toàn bộ engine Ollama (llama-server + libs) và Models AI vào app bundle..."
RESOURCES_DIR="dist/$APP_NAME.app/Contents/Resources"
mkdir -p "$RESOURCES_DIR"

OLLAMA_RES_DIR="$RESOURCES_DIR/ollama_bin"
mkdir -p "$OLLAMA_RES_DIR"

if [ -d "Ollama.app/Contents/Resources" ]; then
    echo "   -> Đang sao chép toàn bộ bộ máy Ollama + llama-server (~500MB)..."
    cp -a "Ollama.app/Contents/Resources/"* "$OLLAMA_RES_DIR/"
    chmod -R 755 "$OLLAMA_RES_DIR"
    # Đồng bộ cả ollama binary trực tiếp tại Resources/ollama để tương thích ngược
    cp -p "$OLLAMA_RES_DIR/ollama" "$RESOURCES_DIR/ollama"
    chmod +x "$RESOURCES_DIR/ollama"
    echo "   -> Đã nhúng toàn bộ engine AI Ollama + llama-server thành công."
fi

if [ -d "models" ]; then
    echo "   -> Đang nhúng thư mục models AI (~1.8GB)..."
    cp -R "models" "$RESOURCES_DIR/models"
    echo "   -> Đã nhúng models thành công."
fi

# 4. Ký mã ad-hoc cho toàn bộ app bundle và các binary phụ trợ
echo "4. Ký mã ad-hoc (Ad-hoc codesign)..."
for bin in "$OLLAMA_RES_DIR/ollama" "$OLLAMA_RES_DIR/llama-server" "$OLLAMA_RES_DIR/llama-quantize" "$RESOURCES_DIR/ollama"; do
    if [ -f "$bin" ]; then
        codesign -s - --force "$bin" 2>/dev/null || true
    fi
done
codesign -s - --force --deep "dist/$APP_NAME.app"

# 5. Tạo thư mục phát hành đóng gói kèm file kích hoạt 1-click
echo "5. Tạo gói phát hành hoàn chỉnh..."
PKG_DIR="dist/$PKG_NAME"
mkdir -p "$PKG_DIR"

mv "dist/$APP_NAME.app" "$PKG_DIR/"

# Tạo file Mo_App_Lan_Dau.command
cat << 'EOF' > "$PKG_DIR/Mo_App_Lan_Dau.command"
#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
APP_PATH="$DIR/0.5%hopeless.app"

echo "========================================================"
echo "   ĐANG KÍCH HOẠT VÀ MỞ ỨNG DỤNG 0.5%hopeless..."
echo "========================================================"

if [ -d "$APP_PATH" ]; then
    echo "1. Đang gỡ bỏ cờ Gatekeeper Quarantine của macOS..."
    xattr -cr "$APP_PATH" 2>/dev/null
    
    echo "2. Đang thiết lập quyền thực thi cho ứng dụng và bộ máy AI..."
    chmod -R 755 "$APP_PATH/Contents/MacOS" 2>/dev/null
    chmod -R 755 "$APP_PATH/Contents/Resources/ollama_bin" 2>/dev/null
    chmod 755 "$APP_PATH/Contents/Resources/ollama" 2>/dev/null
    
    echo "3. Đang mở ứng dụng..."
    open "$APP_PATH"
    echo ""
    echo "✅ KÍCH HOẠT THÀNH CÔNG!"
    echo "   Từ các lần sau, bạn có thể bấm đúp chuột trực tiếp vào icon 0.5%hopeless.app để mở!"
else
    echo "❌ Lỗi: Không tìm thấy 0.5%hopeless.app trong cùng thư mục!"
fi

sleep 2
exit 0
EOF
chmod +x "$PKG_DIR/Mo_App_Lan_Dau.command"

# Tạo file hướng dẫn sử dụng nhanh
cat << 'EOF' > "$PKG_DIR/Huong_Dan_Su_Dung.txt"
================================================================================
HƯỚNG DẪN MỞ VÀ SỬ DỤNG 0.5%hopeless (BẢN TÍCH HỢP FULL AI)
================================================================================

VÌ SAO MAC BÁO "KHÔNG THỂ MỞ VÌ NGHI NGỜ LÀ PHẦN MỀM ĐỘC HẠI"?
-> Đây là cơ chế bảo vệ mặc định Gatekeeper của macOS đối với các file tải về
   từ Google Drive/Slack/Internet chưa mua chứng chỉ Apple Developer $99/năm.
-> Ứng dụng hoàn toàn an toàn, chạy offline 100% không gửi dữ liệu ra ngoài.

CÁCH MỞ TRÊN MÁY KHÁC (CHỌN 1 TRONG CÁC CÁCH SAU):
--------------------------------------------------------------------------------
👉 CÁCH 1 (Đơn giản nhất bằng chuột - Khuyên dùng):
   1. Bấm CHUỘT PHẢI (hoặc giữ phím Control rồi bấm chuột) vào icon "0.5%hopeless.app".
   2. Chọn "Open" (Mở) từ menu.
   3. Hộp thoại hiện lên, bấm nút "Open" (Mở) để xác nhận.
   => XONG! macOS sẽ ghi nhớ vĩnh viễn, từ lần thứ 2 chỉ cần bấm đúp chuột bình thường.

👉 CÁCH 2 (Dành cho macOS Sequoia 15 / Sonoma 14 nếu Cách 1 không hiện nút Open):
   1. Bấm đúp vào "0.5%hopeless.app" (khi bị chặn thông báo phần mềm độc hại, bấm OK).
   2. Mở "Cài đặt hệ thống" (System Settings) -> Chọn "Quyền riêng tư & Bảo mật" (Privacy & Security).
   3. Cuộn xuống mục "Bảo mật" (Security), bạn sẽ thấy dòng thông báo bị chặn.
   4. Bấm nút "Vẫn mở" (Open Anyway) kế bên và nhập mật khẩu máy (hoặc Touch ID).
   => Ứng dụng sẽ mở lên ngay lập tức và được cấp quyền vĩnh viễn.

👉 CÁCH 3 (Lệnh Terminal 1 giây - Không cần quyền admin/sudo):
   1. Mở ứng dụng Terminal trên Mac.
   2. Gõ lệnh: xattr -cr (kèm 1 dấu cách).
   3. Kéo thả icon "0.5%hopeless.app" vào cửa sổ Terminal rồi bấm Enter.
   => Sau đó bấm đúp vào app là mở được ngay!

================================================================================
TÍNH NĂNG TÍCH HỢP:
- Phase 1: Tạo báo cáo Excel và Keynote chi tiết từng trạm.
- Phase 2: Đồng bộ FACA từ Excel sang Keynote + Dịch FACA sang Tiếng Anh chuẩn kỹ thuật
           bằng mô hình AI offline tích hợp sẵn (không cần Internet, không cần cài Ollama).
- Phase 3: Tự động tổng hợp và ghép nối slide hoàn chỉnh theo đúng thứ tự:
           Trang bìa Cover (Mẫu 3) -> Báo cáo tổng kết (Mẫu 2) -> Slide chi tiết gốc.
================================================================================
EOF

# 6. Tạo file nén ZIP chuẩn Mac (bảo toàn symlink và file permissions)
echo "6. Đang nén file phát hành ZIP: dist/$PKG_NAME.zip..."
cd dist
ditto -c -k --sequesterRsrc --keepParent "$PKG_NAME" "$PKG_NAME.zip"

# 7. Tạo file DMG
echo "7. Đang đóng gói file DMG: dist/$PKG_NAME.dmg..."
hdiutil create -volname "0.5%hopeless Full AI" -srcfolder "$PKG_NAME" -ov -format UDZO "$PKG_NAME.dmg"
cd "$DIR"

echo "=========================================================="
echo "🎉 ĐÓNG GÓI HOÀN TẤT THÀNH CÔNG!"
echo "📁 Thư mục phát hành: dist/$PKG_NAME/"
echo "📦 File nén gửi đi:   dist/$PKG_NAME.zip"
echo "💿 File đĩa DMG:      dist/$PKG_NAME.dmg"
echo "=========================================================="
