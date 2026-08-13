# Chế độ mạng và bảo mật

## Phân loại đúng chế độ mạng

### A. Laptop và NodeMCU cùng hotspot/router

```text
NodeMCU --Wi-Fi--> hotspot/router --LAN--> broker trên laptop
```

Đây là chế độ bring-up tốt nhất. Nếu hai thiết bị là peer cùng WLAN, gói MQTT có thể được chuyển nội bộ và không đi qua mạng di động, dù điện thoại hiện biểu tượng 5G. Báo cáo phải gọi đây là **demo LAN qua hotspot**, không tuyên bố đã đo backhaul 5G.

NodeMCU ESP8266 chỉ dùng Wi-Fi **2,4 GHz**. Hãy đặt băng tần hotspot/router
thành 2,4 GHz và dùng chế độ bảo mật tương thích WPA2 nếu chế độ WPA3-only
không kết nối được. “5G” trong tài liệu này là mạng di động thế hệ 5, hoàn toàn
khác với băng tần Wi-Fi “5 GHz”.

Một số điện thoại bật client isolation, làm NodeMCU không truy cập được laptop. Khi đó dùng router cho phép peer-to-peer hoặc chế độ USB tether + Mobile Hotspot dưới đây.

### B. Broker/edge ở đầu xa

```text
NodeMCU -> hotspot 5G -> Internet -> broker/edge từ xa
```

Chỉ chế độ này mới phù hợp để đo backhaul 5G, với điều kiện có bằng chứng tuyến dữ liệu và broker thực sự ở mạng khác. Ghi lại nhà mạng/chế độ mạng, IP/đầu cuối, thời gian thử, RTT và mất gói; so sánh cùng một tải với baseline Wi-Fi nếu nghiên cứu hiệu năng.

Docker Compose trong repo chỉ mở MQTT plaintext 1883 cho LAN. Không đưa cấu hình đó lên VPS hoặc forward cổng từ Internet. Trong MVP hiện tại, nếu chưa kiểm chứng TLS và CA trên cả firmware lẫn edge, hãy đặt broker từ xa sau VPN/private overlay do nhóm kiểm soát. Không tuyên bố “MQTT an toàn qua TLS” chỉ vì đã bật một cờ ở một phía.

### C. USB tether điện thoại → laptop → Windows Mobile Hotspot

```text
Internet 5G -> USB tether -> laptop
                               \-> Windows Mobile Hotspot -> NodeMCU
```

Windows thường đặt IP laptop ở adapter Mobile Hotspot là `192.168.137.1`, nhưng đây không phải cam kết; luôn kiểm tra `ipconfig`. Firmware dùng IP thực tế đó làm broker local.

Nếu broker vẫn chạy trên laptop, MQTT từ NodeMCU tới laptop vẫn là lưu lượng cục bộ và chưa chứng minh qua 5G. Chỉ lưu lượng từ NodeMCU/laptop tới broker đầu xa mới đi tiếp qua USB tether 5G.

## Kiểm tra reachability

1. Xác định đúng adapter và IPv4 bằng `ipconfig`.
2. Broker phải nghe `0.0.0.0:1883`; Docker map cổng `1883:1883`.
3. Windows network profile nên là Private.
4. Chỉ mở firewall TCP 1883 cho subnet cần thiết.
5. Không dùng `localhost`/`127.0.0.1` trong firmware.
6. Nếu IP thay đổi sau mỗi lần bật hotspot, cập nhật `MQTT_HOST` trong
   `firmware/health-node/include/secrets.h` **và nạp lại firmware**, hoặc dùng
   DHCP reservation/DNS nội bộ phù hợp.
7. Xác nhận hotspot có SSID 2,4 GHz mà ESP8266 nhìn thấy; không nhầm 5G di động với Wi-Fi 5 GHz.

Trong workflow broker local, `START-IOT-HEALTH-EDGE.bat` fail-closed nếu
`MQTT_HOST` không phải IPv4 non-loopback đang hoạt động trên laptop. Gate này
chạy trước Docker/upload và chỉ báo trạng thái, không in credential. Nó cố ý
không áp dụng cho broker đầu xa; triển khai remote phải dùng quy trình riêng và
đáp ứng yêu cầu TLS/VPN bên dưới, không vô hiệu hóa gate bằng một địa chỉ giả.

## Mô hình bảo mật MVP

- `allow_anonymous false`.
- Tài khoản edge và node khác nhau; ACL node chỉ cho ghi device ID của chính nó.
- Mật khẩu không nằm trong Git, ảnh chụp màn hình, log hay tham số shell.
- Status retain nhưng telemetry/event không retain.
- Không đưa PII vào topic/payload.
- Port 1883 chỉ dành cho LAN tin cậy: username/password và dữ liệu vẫn đi dạng plaintext.
- Không dùng tài khoản node chung cho nhiều thiết bị ở bản triển khai thật.
- Xoay vòng tài khoản bằng generator, cập nhật edge/firmware rồi khởi động lại có kiểm soát.

## Telegram và dữ liệu đi ra bên thứ ba

Khi `TELEGRAM_ENABLED=true`, edge tạo kết nối HTTPS ra Telegram Bot API và gửi
tóm tắt gồm device ID, thông điệp alert, giá trị tham khảo nếu có và thời gian
edge. Không có raw telemetry, mật khẩu MQTT hoặc token trong nội dung tin.

Bot token tương đương quyền điều khiển bot: chỉ lưu trong `.env` cục bộ, không
đưa vào Git/log/ảnh chụp và thu hồi ngay bằng BotFather nếu bị lộ. Cấu hình
container vẫn có thể được quản trị viên máy đọc qua Docker; không chia sẻ đầu
ra `docker inspect` hoặc `docker compose config` đã resolve.

Việc bật Telegram đồng nghĩa chấp nhận chuyển tóm tắt cảnh báo tới dịch vụ bên
thứ ba. Hãy dùng device ID không chứa PII và chỉ bật khi người vận hành đồng ý.
Telegram là kênh best-effort, không phải cơ chế báo động hoặc cấp cứu bảo đảm.

## TLS và ESP8266

Kết nối Internet trực tiếp phải có mã hóa, xác minh hostname/CA và quản lý chứng chỉ. ESP8266 có RAM hạn chế; TLS có thể làm giảm heap và gây reset nếu ghép với buffer cảm biến/MQTT lớn. Vì vậy cần kiểm thử trên đúng firmware, không dùng chế độ bỏ kiểm tra chứng chỉ và không coi VPN là thay thế cho kiểm soát ACL. Nếu chưa hoàn tất bài test này, giữ broker trong LAN/VPN riêng và ghi rõ giới hạn.
