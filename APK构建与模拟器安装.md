# APK 构建与安卓模拟器安装

本文档适用于当前 XLine Flutter App 工程。

## 1. 当前环境路径

| 项目 | 路径或名称 |
| --- | --- |
| App 工程 | `D:\xikao\test1` |
| Flutter | `D:\flutter\bin\flutter.bat` |
| Java | `D:\java` |
| Android SDK | `D:\ai\android` |
| ADB | `D:\ai\android\platform-tools\adb.exe` |
| 模拟器设备 ID | `emulator-5554` |
| Android 包名 | `com.example.xline_car_app` |

## 2. 检查模拟器连接

先启动安卓模拟器，然后在 PowerShell 中执行：

```powershell
& 'D:\ai\android\platform-tools\adb.exe' devices -l
```

正常情况下会看到类似输出：

```text
List of devices attached
emulator-5554    device
```

如果状态是 `offline`，可以重启 ADB：

```powershell
& 'D:\ai\android\platform-tools\adb.exe' kill-server
& 'D:\ai\android\platform-tools\adb.exe' start-server
& 'D:\ai\android\platform-tools\adb.exe' devices -l
```

## 3. 获取 Flutter 依赖

首次构建或修改 `pubspec.yaml` 后执行：

```powershell
Set-Location 'D:\xikao\test1'
& 'D:\flutter\bin\flutter.bat' pub get
```

网络受限但依赖已经存在时，可以跳过此步骤，并在构建时使用 `--no-pub`。

## 4. 构建 Debug APK

推荐先使用 Flutter 命令：

```powershell
Set-Location 'D:\xikao\test1'
$env:JAVA_HOME = 'D:\java'
& 'D:\flutter\bin\flutter.bat' build apk --debug --no-pub
```

构建成功后，APK 位于：

```text
D:\xikao\test1\build\app\outputs\flutter-apk\app-debug.apk
```

可以检查 APK 的生成时间和大小：

```powershell
Get-Item 'D:\xikao\test1\build\app\outputs\flutter-apk\app-debug.apk' |
    Select-Object FullName, Length, LastWriteTime
```

必须确认 `LastWriteTime` 是本次构建时间，避免安装旧 APK。

## 5. Flutter 命令异常时直接使用 Gradle

如果 Flutter 构建长时间没有输出，可以直接执行 Android Gradle 构建：

```powershell
Set-Location 'D:\xikao\test1\android'
$env:JAVA_HOME = 'D:\java'
& 'D:\xikao\test1\android\gradlew.bat' assembleDebug --no-daemon --console=plain
```

首次运行时，Gradle 可能需要下载并解压发行包，因此会明显较慢。不要同时启动多个构建命令，否则多个 Java/Gradle 进程会争抢 CPU、内存和文件锁。

查看 Gradle/Java 是否仍在工作：

```powershell
Get-Process java -ErrorAction SilentlyContinue |
    Select-Object Id, CPU, WorkingSet, StartTime
```

即使命令窗口超时，只要 Java 进程仍在运行且 CPU 数值继续增加，后台构建可能尚未结束。此时应先等待，并定期检查 APK 的 `LastWriteTime`。

## 6. 覆盖安装到模拟器

使用 `install -r` 覆盖已有 App，并保留原有应用数据：

```powershell
& 'D:\ai\android\platform-tools\adb.exe' -s emulator-5554 install -r `
    'D:\xikao\test1\build\app\outputs\flutter-apk\app-debug.apk'
```

安装成功会显示：

```text
Performing Streamed Install
Success
```

不要在需要保留登录信息、API 配置和设备配置时执行 `adb uninstall`，因为卸载会清除该 App 的本地数据。

## 7. 启动 App

先停止旧进程，再启动新安装的 App：

```powershell
& 'D:\ai\android\platform-tools\adb.exe' -s emulator-5554 `
    shell am force-stop com.example.xline_car_app

& 'D:\ai\android\platform-tools\adb.exe' -s emulator-5554 `
    shell monkey -p com.example.xline_car_app `
    -c android.intent.category.LAUNCHER 1
```

## 8. 验证 App 是否正常运行

检查应用进程：

```powershell
& 'D:\ai\android\platform-tools\adb.exe' -s emulator-5554 `
    shell pidof com.example.xline_car_app
```

如果返回一个数字 PID，说明应用进程正在运行。

检查前台 Activity：

```powershell
& 'D:\ai\android\platform-tools\adb.exe' -s emulator-5554 `
    shell dumpsys activity activities |
    Select-String 'topResumedActivity|com.example.xline_car_app'
```

正常情况下应看到：

```text
com.example.xline_car_app/.MainActivity
```

## 9. 一次完成构建、安装和启动

确认模拟器已经启动后，可以依次执行：

```powershell
Set-Location 'D:\xikao\test1'
$env:JAVA_HOME = 'D:\java'

& 'D:\flutter\bin\flutter.bat' build apk --debug --no-pub

if ($LASTEXITCODE -ne 0) {
    throw 'APK 构建失败，停止安装。'
}

$adb = 'D:\ai\android\platform-tools\adb.exe'
$apk = 'D:\xikao\test1\build\app\outputs\flutter-apk\app-debug.apk'

& $adb -s emulator-5554 install -r $apk

if ($LASTEXITCODE -ne 0) {
    throw 'APK 安装失败，停止启动。'
}

& $adb -s emulator-5554 shell am force-stop com.example.xline_car_app
& $adb -s emulator-5554 shell monkey `
    -p com.example.xline_car_app `
    -c android.intent.category.LAUNCHER 1
```

## 10. 常见问题

### 找不到模拟器

先确认模拟器已经完全启动，再运行 `adb devices -l`。如果设备 ID 不是 `emulator-5554`，将文档命令中的设备 ID 替换成实际值。

### 安装提示签名不一致

如果旧 App 与新 APK 的签名不同，`install -r` 无法覆盖。只有在确认允许清空 App 本地数据后，才能卸载旧版本再安装：

```powershell
& 'D:\ai\android\platform-tools\adb.exe' -s emulator-5554 `
    uninstall com.example.xline_car_app
```

### 构建速度很慢

首次构建需要下载 Gradle、初始化缓存并编译 Flutter 引擎相关产物。后续增量构建通常更快。除非确实需要，不要执行 `flutter clean`，因为它会删除可复用的构建产物。

### App 启动后立即退出

查看错误日志：

```powershell
& 'D:\ai\android\platform-tools\adb.exe' -s emulator-5554 logcat `
    -d -t 300 |
    Select-String 'FATAL EXCEPTION|AndroidRuntime|flutter'
```

