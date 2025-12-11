# Hướng dẫn Quản lý Hộ nghèo (AI Assistant)

Dự án này là một AI Agent thông minh được phát triển bằng **Google ADK** và **Gemini 2.5 Flash**, giúp hỗ trợ người dùng ứng dụng "Quản lý Hộ nghèo". Agent có khả năng tự động chẩn đoán lỗi, cung cấp hướng dẫn bật định vị theo từng loại thiết bị (iOS/Android), và hướng dẫn cài đặt ứng dụng chi tiết kèm hình ảnh minh họa.

## ✨ Tính năng nổi bật

- 🤖 **AI Agent thông minh**: Sử dụng Gemini 2.5 Flash để hiểu ngôn ngữ tự nhiên và ngữ cảnh.
- 📱 **Tự động nhận diện thiết bị**: Xác định loại thiết bị (iOS/Android) dựa trên thông tin người dùng hoặc database.
- 🖼️ **Hướng dẫn trực quan**: Cung cấp hướng dẫn từng bước kèm hình ảnh minh họa được trích xuất tự động từ tài liệu gốc.
- 📂 **Xử lý tài liệu tự động**:
  - Tự động đọc và trích xuất dữ liệu từ file PDF (`Location_Instruction.pdf`).
  - Tự động trích xuất hướng dẫn cài đặt từ file Word (`HELP_RASOATHONGHEO_AI.docx`) khi cần thiết.
- 🔌 **Tích hợp Database**: Kết nối SQL Server để tra cứu thông tin thiết bị và trạng thái lỗi của người dùng.
- ⚡ **Local Image Server**: Tự động dựng server HTTP nội bộ để phục vụ hình ảnh minh họa trong phiên chat.

## 🛠️ Yêu cầu hệ thống

- **Python**: 3.10 trở lên
- **SQL Server**: (Hoặc quyền truy cập vào một database có sẵn)
- **Các thư viện hệ thống**:
  - ODBC Driver 17 for SQL Server

## 🚀 Cài đặt

1.  **Clone dự án:**
    ```bash
    git clone <repository_url>
    cd locate_instruction
    ```

2.  **Tạo môi trường ảo (Khuyên dùng):**
    ```bash
    python -m venv venv
    # Windows:
    venv\Scripts\activate
    # Linux/Mac:
    source venv/bin/activate
    ```

3.  **Cài đặt các thư viện Python:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Cấu hình môi trường:**
    Tạo file `.env` tại thư mục gốc và điền thông tin kết nối Database:
    ```env
    SERVER=your_server_address
    DATABASE=your_database_name
    UID=your_username
    PWD=your_password
    TABLE=your_table_name
    ```

## 🏃‍♂️ Chạy Agent

Sử dụng Google ADK để chạy agent:

```bash
# Chạy agent server
adk run agent:root_agent
```

Hoặc chạy với giao diện web debug:
```bash
adk web --port 8000
```

## 📖 Cách sử dụng

Sau khi khởi động agent, bạn có thể chat với nó bằng tiếng Việt. Một số kịch bản mẫu:

- **Hỏi về lỗi thiết bị**: "Tại sao tôi không bật được định vị?", "Tên đăng nhập của tôi là 'user123'".
- **Hỏi cài đặt ứng dụng**: "Cách tải app Hộ nghèo như thế nào?", "Hướng dẫn cài đặt ứng dụng".

Agent sẽ:
1.  Hỏi tên đăng nhập (nếu chưa có).
2.  Tra cứu thông tin thiết bị và lỗi từ Database.
3.  Hiển thị hướng dẫn sửa lỗi hoặc cài đặt kèm hình ảnh minh họa cụ thể.

