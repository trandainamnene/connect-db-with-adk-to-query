# Hướng Dẫn Bật Định Vị Điện Thoại

Dự án hỗ trợ hướng dẫn người dùng cách bật chế độ định vị trên điện thoại dựa trên loại thiết bị và phiên bản hệ điều hành. Đây là một phần của dự án hỗ trợ hộ nghèo, giúp người dùng dễ dàng kích hoạt định vị trên thiết bị của mình.

## 🎯 Mục đích

Dự án này được thiết kế để:
- Nhận thông tin về loại điện thoại và phiên bản hệ điều hành của người dùng
- Tự động tìm kiếm hướng dẫn phù hợp datasource
- Cung cấp hướng dẫn chi tiết, dễ hiểu về cách bật chế độ định vị trên thiết bị cụ thể

## ✨ Tính năng

- 🤖 **AI Agent**: Sử dụng Google Gemini để xử lý và phân tích thông tin
- 💾 **Kết nối Database**: Lấy thông tin hướng dẫn từ SQL Server

## 🛠️ Công nghệ sử dụng

- **Python 3.13+**
- **Google ADK (Agent Development Kit)**: Framework để xây dựng AI Agent
- **Gemini 2.5 Flash**: Model AI để xử lý và trả lời
- **SQL Server**: Cơ sở dữ liệu lưu trữ thông tin hướng dẫn
- **pyodbc**: Thư viện kết nối SQL Server

## 📋 Yêu cầu hệ thống

- Python 3.13 hoặc cao hơn
- SQL Server (hoặc SQL Server Express)
- ODBC Driver 17 for SQL Server
- Tài khoản Google (để sử dụng Gemini API)

## 🚀 Cài đặt

### 1. Clone repository

```bash
git clone <repository-url>
cd locate_instruction
```

### 2. Tạo virtual environment

```bash
python -m venv venv
```

### 3. Kích hoạt virtual environment

**Windows:**
```bash
venv\Scripts\activate
```

**Linux/Mac:**
```bash
source venv/bin/activate
```

### 4. Cài đặt dependencies

```bash
pip install -r requirements.txt
```

### 5. Cấu hình môi trường

Tạo file `.env` trong thư mục gốc của dự án với nội dung:

```env
SERVER=your_server_name
DATABASE=your_database_name
UID=your_username
PWD=your_password
TABLE=your_table_name
```

**Ví dụ:**
```env
SERVER=localhost\SQLEXPRESS
DATABASE=LocationGuideDB
UID=sa
PWD=your_secure_password
TABLE=SysOption
```

### 6. Cài đặt ODBC Driver

Đảm bảo đã cài đặt **ODBC Driver 17 for SQL Server**:

## 📖 Cấu trúc dự án

```
locate_instruction/
├── __init__.py          # Module initialization
├── agent.py             # Định nghĩa AI Agent
├── db.py                # Kết nối và quản lý database
├── tools.py             # Các công cụ/tool cho agent
├── test.py              # File test
├── requirements.txt     # Dependencies
├── .env                 # Cấu hình môi trường (không commit)
└── README.md           # Tài liệu hướng dẫn
```

### Cách hoạt động

1. **Người dùng cung cấp thông tin**: Loại điện thoại và phiên bản hệ điều hành
2. **Agent xử lý**: AI Agent phân tích thông tin và tìm kiếm hướng dẫn phù hợp
3. **Truy vấn Database**: Agent sử dụng tool `query_SysOption` để lấy thông tin từ SQL Server
4. **Trả về hướng dẫn**: Agent cung cấp hướng dẫn chi tiết về cách bật định vị

## 📝 Cấu trúc Database

Cơ sở dữ liệu chứa thông tin hướng dẫn về cách bật định vị cho các loại điện thoại và phiên bản hệ điều hành khác nhau.

Bảng trong database cần có các cột chứa:
- Thông tin về loại điện thoại
- Phiên bản hệ điều hành


