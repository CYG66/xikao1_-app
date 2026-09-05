# xline_car_app

A new Flutter project.

## Getting Started

This project is a starting point for a Flutter application.

A few resources to get you started if this is your first Flutter project:

- [Learn Flutter](https://docs.flutter.dev/get-started/learn-flutter)
- [Write your first Flutter app](https://docs.flutter.dev/get-started/codelab)
- [Flutter learning resources](https://docs.flutter.dev/reference/learning-resources)

For help getting started with Flutter development, view the
[online documentation](https://docs.flutter.dev/), which offers tutorials,
samples, guidance on mobile development, and a full API reference.
# X-LINE2 前端 App

## 预览模式

本项目支持通过 `XLINE_LAYOUT_PREVIEW` 构建仅用于页面布局检查的预览 APK。预览模式会模拟小车在线、定位、地图、轨迹和设备状态，并拦截真实连接、移动、喷墨及任务执行请求。

在 Windows 命令行构建预览版：

```bat
cd /d D:\xikao\xikao1_-app\xikao1_-app
D:\flutter\bin\flutter.bat clean
D:\flutter\bin\flutter.bat pub get --offline
D:\flutter\bin\flutter.bat build apk --release --dart-define=XLINE_LAYOUT_PREVIEW=true
```

输出文件：

```text
build\app\outputs\flutter-apk\app-release.apk
```

构建真实小车版时显式关闭预览：

```bat
D:\flutter\bin\flutter.bat build apk --release --dart-define=XLINE_LAYOUT_PREVIEW=false
```
