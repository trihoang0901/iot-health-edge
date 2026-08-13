@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul

title IoT Health Edge - One Click Start
set "ROOT=%~dp0"
set "FINAL_CODE=0"
set "NO_PAUSE=0"
set "PUSHD_OK=0"
set "NODE_WARN=0"
set "UPLOAD_STARTED_UTC="
if /i "%~1"=="--no-pause" set "NO_PAUSE=1"

pushd "%ROOT%" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Khong mo duoc thu muc du an: "%ROOT%"
    set "FINAL_CODE=1"
    goto :finish
)
set "PUSHD_OK=1"

echo ============================================================
echo              IoT HEALTH EDGE - ONE CLICK START
echo ============================================================
echo.

echo [1/7] Kiem tra cau hinh cuc bo...
if not exist "%ROOT%.env" (
    echo [ERROR] Thieu .env. Tao tu .env.example va dien mat khau health_edge.
    set "FINAL_CODE=1"
    goto :finish
)
if not exist "%ROOT%deploy\mosquitto\generated\passwords" (
    echo [ERROR] Thieu password Mosquitto. Chay deploy\scripts\Initialize-Mosquitto.ps1 truoc.
    set "FINAL_CODE=1"
    goto :finish
)
if not exist "%ROOT%deploy\mosquitto\generated\acl" (
    echo [ERROR] Thieu ACL Mosquitto. Chay deploy\scripts\Initialize-Mosquitto.ps1 truoc.
    set "FINAL_CODE=1"
    goto :finish
)
if not exist "%ROOT%firmware\health-node\include\secrets.h" (
    echo [ERROR] Thieu firmware\health-node\include\secrets.h.
    set "FINAL_CODE=1"
    goto :finish
)

set "IOT_HEALTH_ROOT=%ROOT%"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $root=$env:IOT_HEALTH_ROOT; $envFile=Join-Path $root '.env'; $passwords=Join-Path $root 'deploy\mosquitto\generated\passwords'; $acl=Join-Path $root 'deploy\mosquitto\generated\acl'; $secrets=Join-Path $root 'firmware\health-node\include\secrets.h'; foreach($path in @($envFile,$passwords,$acl,$secrets)){if(!(Test-Path -LiteralPath $path) -or (Get-Item -LiteralPath $path).Length -eq 0){exit 10}}; $envText=[IO.File]::ReadAllText($envFile); $edge=[regex]::Match($envText,'(?m)^MQTT_PASSWORD=(.*)$'); if(!$edge.Success -or [string]::IsNullOrWhiteSpace($edge.Groups[1].Value) -or $edge.Groups[1].Value -match 'replace_with_local|placeholder|^\x3C.*\x3E$'){exit 11}; $secretText=[IO.File]::ReadAllText($secrets); $quote=[char]34; $required=@('WIFI_SSID','WIFI_PASSWORD','DEVICE_ID','MQTT_HOST','MQTT_USERNAME','MQTT_PASSWORD'); foreach($name in $required){$pattern='(?m)^\s*#define\s+'+[regex]::Escape($name)+'\s+'+$quote+'[^'+$quote+']+'+$quote; if($secretText -notmatch $pattern){exit 12}}; if($secretText -match 'your-hotspot-name|your-hotspot-password|replace-with-a-local-password|127\.0\.0\.1'){exit 13}; $hostMatch=[regex]::Match($secretText,'(?m)^\s*#define\s+MQTT_HOST\s+'+$quote+'([^'+$quote+']+)'+$quote); [Net.IPAddress]$mqttAddress=$null; if(!$hostMatch.Success -or ![Net.IPAddress]::TryParse($hostMatch.Groups[1].Value,[ref]$mqttAddress) -or $mqttAddress.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or [Net.IPAddress]::IsLoopback($mqttAddress)){exit 15}; $localIpv4=@(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop | Where-Object {$_.AddressState -eq 'Preferred' -and $_.IPAddress -ne '0.0.0.0' -and -not [Net.IPAddress]::IsLoopback([Net.IPAddress]::Parse($_.IPAddress))} | ForEach-Object {$_.IPAddress}); if($localIpv4 -notcontains $mqttAddress.IPAddressToString){exit 15}; $aclText=[IO.File]::ReadAllText($acl); if($aclText -match '__DEVICE_ID__|\{device_id\}'){exit 14}; exit 0"
set "CONFIG_RC=%ERRORLEVEL%"
if not "%CONFIG_RC%"=="0" (
    if "%CONFIG_RC%"=="11" echo [ERROR] MQTT_PASSWORD trong .env chua duoc cau hinh.
    if "%CONFIG_RC%"=="12" echo [ERROR] secrets.h thieu mot hoac nhieu #define bat buoc.
    if "%CONFIG_RC%"=="13" echo [ERROR] secrets.h van con gia tri mau. Hay dien Wi-Fi, IP MQTT va mat khau node.
    if "%CONFIG_RC%"=="14" echo [ERROR] ACL Mosquitto van con placeholder device_id.
    if "%CONFIG_RC%"=="15" echo [ERROR] MQTT_HOST trong firmware khong khop bat ky IPv4 cuc bo dang hoat dong. Hay cap nhat IP broker truoc khi nap firmware.
    if "%CONFIG_RC%"=="10" echo [ERROR] Mot tep cau hinh bat buoc dang rong.
    if not "%CONFIG_RC%"=="10" if not "%CONFIG_RC%"=="11" if not "%CONFIG_RC%"=="12" if not "%CONFIG_RC%"=="13" if not "%CONFIG_RC%"=="14" if not "%CONFIG_RC%"=="15" echo [ERROR] Khong kiem tra duoc cau hinh cuc bo.
    set "FINAL_CODE=1"
    goto :finish
)
echo [1/7] [OK] Cau hinh da san sang, khong hien thi gia tri bi mat.

echo [2/7] Kiem tra Docker Desktop...
where docker.exe >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Khong tim thay docker.exe. Hay cai va mo Docker Desktop.
    set "FINAL_CODE=1"
    goto :finish
)
docker compose version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker Compose khong san sang.
    set "FINAL_CODE=1"
    goto :finish
)
docker info >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker Desktop chua Running.
    set "FINAL_CODE=1"
    goto :finish
)
echo [2/7] [OK] Docker Desktop dang san sang.

set "PIO_EXE="
set "PIO_READY=0"
if exist "%ROOT%.platformio-venv\Scripts\pio.exe" set "PIO_EXE=%ROOT%.platformio-venv\Scripts\pio.exe"
if not defined PIO_EXE if exist "%ROOT%.venv\Scripts\pio.exe" set "PIO_EXE=%ROOT%.venv\Scripts\pio.exe"
if not defined PIO_EXE for %%P in (pio.exe platformio.exe) do if not defined PIO_EXE for /f "delims=" %%Q in ('where %%P 2^>nul') do if not defined PIO_EXE set "PIO_EXE=%%Q"
if defined PIO_EXE "%PIO_EXE%" --version >nul 2>&1
if defined PIO_EXE if not errorlevel 1 set "PIO_READY=1"
if "%PIO_READY%"=="1" (
    echo [2/7] [OK] PlatformIO da san sang.
) else (
    echo [2/7] [WARN] Khong tim thay PlatformIO hop le; chi can khi co NodeMCU de nap.
)

echo [3/7] Tim NodeMCU CH340...
set "COM_PORT="
for /f "usebackq delims=" %%P in (`powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "try{$numbers=New-Object 'System.Collections.Generic.List[int]'; foreach($device in @(Get-PnpDevice -Class Ports -PresentOnly -ErrorAction Stop)){if($device.FriendlyName -match 'CH340' -or $device.InstanceId -match 'VID_1A86.PID_7523'){ $m=[regex]::Match($device.FriendlyName,'COM(\d+)'); if($m.Success){$numbers.Add([int]$m.Groups[1].Value)}}}; $items=$numbers.ToArray(); [array]::Sort($items); if($items.Count -gt 0){'COM'+$items[0]}}catch{'__PROBE_ERROR__'}"`) do set "COM_PORT=%%P"
if "%COM_PORT%"=="__PROBE_ERROR__" (
    echo [3/7] [ERROR] PowerShell khong truy van duoc cong CH340.
    set "FINAL_CODE=1"
    goto :finish
)
if defined COM_PORT (
    echo [3/7] [OK] Da tim thay NodeMCU tai %COM_PORT%.
) else (
    echo [3/7] [WARN] Khong tim thay CH340. He thong van khoi dong, bo qua nap firmware.
)

echo [4/7] Khoi dong Mosquitto, edge API va dashboard...
docker compose --env-file "%ROOT%.env" -f "%ROOT%deploy\docker-compose.yml" --profile full up -d --build
if errorlevel 1 (
    echo [ERROR] Docker Compose khoi dong that bai.
    docker compose --env-file "%ROOT%.env" -f "%ROOT%deploy\docker-compose.yml" --profile full ps
    set "FINAL_CODE=1"
    goto :finish
)
echo [4/7] [OK] Docker full profile da khoi dong.

echo [5/7] Nap firmware neu co NodeMCU...
if not defined COM_PORT goto :skip_upload
if not "%PIO_READY%"=="1" (
    echo [ERROR] Da tim thay %COM_PORT% nhung PlatformIO khong san sang.
    set "FINAL_CODE=1"
    goto :finish
)
tasklist.exe /fi "IMAGENAME eq serial-monitor.exe" 2>nul | findstr.exe /i /c:"serial-monitor.exe" >nul
if not errorlevel 1 echo [5/7] [WARN] Dang dong cac cua so Arduino Serial Monitor de giai phong %COM_PORT%.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$monitor=Get-Process -Name 'serial-monitor' -ErrorAction SilentlyContinue; if($monitor){Stop-Process -InputObject $monitor -Force}" >nul 2>&1
for /f "usebackq delims=" %%T in (`powershell.exe -NoLogo -NoProfile -Command "[DateTimeOffset]::UtcNow.ToString('o')"`) do set "UPLOAD_STARTED_UTC=%%T"
if not defined UPLOAD_STARTED_UTC (
    echo [ERROR] Khong ghi duoc moc thoi gian truoc khi nap firmware.
    set "FINAL_CODE=1"
    goto :finish
)
"%PIO_EXE%" run -d "%ROOT%firmware\health-node" --target upload --upload-port "%COM_PORT%"
if errorlevel 1 (
    echo [ERROR] Khong nap duoc firmware qua %COM_PORT%.
    echo         Dong Serial Monitor/Arduino IDE neu dang giu cong, kiem tra cap va driver CH340.
    echo         Docker van dang chay; co the mo dashboard sau khi xu ly cong COM.
    set "FINAL_CODE=1"
    goto :finish
)
echo [5/7] [OK] Firmware da nap qua %COM_PORT%.
goto :after_upload

:skip_upload
echo [5/7] [SKIP] Khong co NodeMCU, bo qua nap firmware.

:after_upload
echo [6/7] Cho edge API healthy, toi da 90 giay...
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$deadline=(Get-Date).AddSeconds(90); do{try{$health=Invoke-RestMethod -Uri 'http://127.0.0.1:8000/healthz' -TimeoutSec 3; if($health.status -eq 'ok'){exit 0}}catch{}; Start-Sleep -Seconds 2}while((Get-Date) -lt $deadline); exit 1"
if errorlevel 1 (
    echo [ERROR] Edge API khong healthy sau 90 giay.
    docker compose --env-file "%ROOT%.env" -f "%ROOT%deploy\docker-compose.yml" --profile full ps
    set "FINAL_CODE=1"
    goto :finish
)
echo [6/7] [OK] Edge API healthy va MQTT worker da khoi dong.
if defined COM_PORT (
    echo [6/7] Cho telemetry moi tu NodeMCU, toi da 30 giay...
    powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$root=$env:IOT_HEALTH_ROOT; $culture=[Globalization.CultureInfo]::InvariantCulture; $styles=[Globalization.DateTimeStyles]([int][Globalization.DateTimeStyles]::AssumeUniversal -bor [int][Globalization.DateTimeStyles]::AdjustToUniversal); $started=[DateTimeOffset]::Parse($env:UPLOAD_STARTED_UTC,$culture,$styles); $text=[IO.File]::ReadAllText((Join-Path $root 'firmware\health-node\include\secrets.h')); $quote=[char]34; $match=[regex]::Match($text,'(?m)^\s*#define\s+DEVICE_ID\s+'+$quote+'([^'+$quote+']+)'+$quote); if(!$match.Success){exit 1}; $base='http://127.0.0.1:8000/api/v1/devices/'+[uri]::EscapeDataString($match.Groups[1].Value); $deadline=(Get-Date).AddSeconds(30); do{try{$device=Invoke-RestMethod -Uri $base -TimeoutSec 3; $latest=Invoke-RestMethod -Uri ($base+'/latest') -TimeoutSec 3; $received=[DateTimeOffset]::Parse($latest.received_at,$culture,$styles); $schema=if($latest.schema){$latest.schema}else{$latest.schema_version}; if($device.online -eq $true -and $received -ge $started -and $schema -eq 'health.telemetry.v3' -and $latest.system.fw -eq '0.3.1'){exit 0}}catch{}; Start-Sleep -Seconds 2}while((Get-Date) -lt $deadline); exit 1"
    if errorlevel 1 (
        echo [6/7] [WARN] Chua nhan telemetry moi. Kiem tra Wi-Fi 2.4 GHz, MQTT_HOST va mat khau health_node.
        set "NODE_WARN=1"
    ) else (
        echo [6/7] [OK] NodeMCU da gui telemetry moi toi edge.
    )
)

echo [7/7] Mo dashboard...
start "" "http://127.0.0.1:8000/"
echo [7/7] [OK] Da mo http://127.0.0.1:8000/
echo.
echo Hoan tat. Day la prototype phi lam sang, khong dung cho chan doan hoac cap cuu.

:finish
if "%PUSHD_OK%"=="1" popd >nul 2>&1
echo.
if "%FINAL_CODE%"=="0" (
    if "%NODE_WARN%"=="1" (
        echo [WARN] Dashboard da chay nhung ket noi NodeMCU chua duoc xac nhan.
    ) else (
        echo [OK] Quy trinh ket thuc thanh cong.
    )
) else (
    echo [ERROR] Quy trinh dung voi ma loi %FINAL_CODE%.
)
if "%NO_PAUSE%"=="0" pause
endlocal & exit /b %FINAL_CODE%
