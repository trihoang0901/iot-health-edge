# Thông báo Telegram

Telegram là kênh thông báo **tùy chọn** và bị tắt mặc định. Edge chỉ gửi tóm
tắt cảnh báo; không gửi toàn bộ telemetry. Đây là prototype phi lâm sàng,
không phải hệ thống cấp cứu và Telegram không bảo đảm giao nhận.

## 1. Tạo bot và lấy Chat ID

1. Mở tài khoản chính thức [@BotFather](https://t.me/BotFather), chạy
   `/newbot` và lưu bot token **chỉ trên máy cá nhân**.
2. Mở bot vừa tạo, nhấn **Start** hoặc gửi một tin nhắn. Bot không thể tự bắt
   đầu cuộc trò chuyện riêng.
3. Trong PowerShell, nhập token bằng prompt để nó không nằm trực tiếp trong
   dòng lệnh đã gõ:

```powershell
$telegramToken = Read-Host 'Telegram bot token'
$updates = Invoke-RestMethod -Method Get -Uri (
    'https://api.telegram.org/bot{0}/getUpdates' -f $telegramToken
)
$updates.result |
    ForEach-Object { $_.message.chat } |
    Where-Object { $null -ne $_ } |
    Select-Object -Unique id, type, username, first_name, title
Remove-Variable telegramToken, updates
```

Giá trị cột `id` của cuộc trò chuyện riêng là `TELEGRAM_CHAT_ID`. Nếu chưa có
kết quả, gửi thêm một tin cho bot rồi chạy lại. Không chụp hoặc gửi cho người
khác toàn bộ phản hồi `getUpdates` vì nó có thể chứa nội dung tin nhắn.

## 2. Bật trong Docker

Mở `.env` cục bộ và thêm hoặc sửa các dòng sau. Không gửi các giá trị này qua
chat và không đưa `.env` vào Git:

```dotenv
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=<token-tu-BotFather>
TELEGRAM_CHAT_ID=<chat-id>
```

Các giới hạn vận hành đã có mặc định an toàn trong `.env.example`; chỉ cần đổi
khi đang kiểm thử có kiểm soát. Tạo lại edge container để nhận cấu hình:

```powershell
docker compose --env-file .\.env -f .\deploy\docker-compose.yml `
    --profile full up -d --build edge
```

Không đăng đầu ra `docker compose config` hoặc `docker inspect`, vì cấu hình
container có thể chứa token đã resolve.

## 3. Bật khi chạy Python trực tiếp

Ứng dụng không tự đọc `.env`. Đặt thêm ba biến trong đúng cửa sổ PowerShell
đang chạy Uvicorn:

```powershell
$env:TELEGRAM_ENABLED = 'true'
$env:TELEGRAM_BOT_TOKEN = '<token-tu-BotFather>'
$env:TELEGRAM_CHAT_ID = '<chat-id>'
python -m uvicorn edge.app:app --host 127.0.0.1 --port 8000
```

Đóng cửa sổ PowerShell hoặc xóa ba biến sau khi thử để token không tiếp tục tồn
tại trong môi trường của phiên đó.

## 4. Thử an toàn

Chạy một sự kiện ngã tổng hợp:

```powershell
python -m simulator --scenario fall --count 8
```

Kỳ vọng nhận một tin có nhãn cảnh báo demo, thiết bị, thời gian edge và cảnh
báo phi lâm sàng. Quy tắc gửi là:

- Ngưỡng SpO₂/nhịp tim: một tin khi alert mới mở; các telemetry tiếp theo chỉ
  cập nhật alert và không gửi thêm. Alert kết thúc rồi mở lại sẽ gửi tin mới.
- Nhiệt độ và độ ẩm DHT11 chỉ là dữ liệu môi trường, không tạo alert sức khỏe
  và không gửi Telegram. Mapping nhiệt độ cũ chỉ còn để trình bày lịch sử
  `surface_temp_demo`; migration chuyển alert cũ đang mở sang `resolved` và
  không đánh giá luật này cho telemetry mới.
- Ngã demo: mỗi `event_id` mới gửi một tin; bản MQTT phát lại cùng `event_id`
  không gửi lại.
- ACK và resolved không gửi tin.

## 5. Giới hạn và tắt

Worker dùng hàng đợi RAM giới hạn và retry hữu hạn. Mất Internet, queue đầy,
restart hoặc crash có thể làm mất tin; một timeout ngay sau khi Telegram đã
nhận tin cũng có thể tạo bản gửi lặp hiếm gặp. Các lỗi đó không chặn MQTT,
SQLite hoặc dashboard.

Để tắt, đặt `TELEGRAM_ENABLED=false` trong `.env` rồi tạo lại edge container.
Nếu token bị lộ, dùng BotFather thu hồi/tạo token mới trước khi chạy lại.

API sử dụng là [Telegram Bot API `sendMessage`](https://core.telegram.org/bots/api#sendmessage).
