#!/bin/bash
# ==============================================================================
# Script tự động chuẩn bị tài nguyên AI (Ollama.app & models) để đóng gói Full AI
# Dành cho kỹ sư sau khi clone repo từ GitHub về máy
# ==============================================================================
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "=========================================================="
echo "🤖 CHUẨN BỊ TÀI NGUYÊN AI ĐỂ ĐÓNG GÓI 0.5%hopeless..."
echo "=========================================================="

# 1. Kiểm tra và chuẩn bị Ollama.app
if [ -d "Ollama.app" ]; then
    echo "✅ Đã có thư mục Ollama.app trong dự án."
else
    if [ -d "/Applications/Ollama.app" ]; then
        echo "📦 Đang sao chép /Applications/Ollama.app vào thư mục dự án..."
        cp -R "/Applications/Ollama.app" "$DIR/Ollama.app"
        echo "✅ Đã sao chép Ollama.app thành công."
    else
        echo "⚠️ Không tìm thấy /Applications/Ollama.app trên máy."
        echo "   Vui lòng tải Ollama tại https://ollama.com hoặc chạy:"
        echo "   brew install --cask ollama"
    fi
fi

# 2. Kiểm tra và chuẩn bị mô hình Qwen2.5:3b
if [ -d "models" ] && [ -d "models/blobs" ]; then
    echo "✅ Đã có thư mục models AI trong dự án."
else
    OLLAMA_USER_MODELS="$HOME/.ollama/models"
    if [ -d "$OLLAMA_USER_MODELS" ] && [ -d "$OLLAMA_USER_MODELS/blobs" ]; then
        echo "📦 Đang sao chép models từ $OLLAMA_USER_MODELS vào dự án (~1.8GB)..."
        cp -R "$OLLAMA_USER_MODELS" "$DIR/models"
        echo "✅ Đã sao chép models thành công."
    else
        echo "⚠️ Chưa tìm thấy model qwen2.5:3b trong máy."
        echo "   Vui lòng tải model bằng lệnh terminal:"
        echo "   ollama pull qwen2.5:3b"
        echo "   Sau đó chạy lại script này: ./prepare_ai_assets.sh"
    fi
fi

echo "=========================================================="
if [ -d "Ollama.app" ] && [ -d "models" ]; then
    echo "🎉 HOÀN TẤT! Bạn đã có thể chạy ./build_app.sh để đóng gói Full AI."
else
    echo "ℹ️ Vui lòng hoàn thành các bước cảnh báo ở trên trước khi build."
fi
echo "=========================================================="
