# XLine 划线小车 App 架构图

```mermaid
flowchart LR
    user["操作人员"]

    subgraph flutterApp ["Flutter Android App"]
        direction TB
        pages["页面层：首页、任务、设置"]
        components["组件层：状态卡、控制器、地图"]
        appState["状态层：连接、设备、任务"]
        messages["通信层：ROS Bridge JSON"]
        webSocket["WebSocket 客户端"]
        pages --> components --> appState --> messages --> webSocket
    end

    subgraph fastApi ["Python FastAPI Bridge"]
        direction TB
        wsApi["WebSocket / HTTP 接口"]
        dispatcher["指令解析与路由"]
        robotState["小车状态快照"]
        rosAdapter["rclpy 适配层"]
        wsApi --> dispatcher
        dispatcher --> robotState
        dispatcher --> rosAdapter
        robotState --> wsApi
    end

    subgraph ros2System ["Ubuntu ROS2 Humble"]
        direction TB
        topics["ROS2 Topics：/cmd_vel、/imu、/robot_pose"]
        services["ROS2 Services：喷码机、LN150"]
        nodes["XLine ROS2 Nodes：底盘、定位、路径、任务"]
        topics <--> nodes
        services <--> nodes
    end

    subgraph hardware ["小车硬件"]
        direction TB
        base["底盘与电机"]
        ln150["LN150 全站仪"]
        printer["喷码机"]
        sensors["IMU 与定位传感器"]
    end

    user -->|"触摸操作"| pages
    webSocket <-->|"JSON WebSocket"| wsApi
    rosAdapter -->|"发布 / 订阅"| topics
    rosAdapter -->|"调用服务"| services
    nodes --> base
    nodes --> ln150
    nodes --> printer
    sensors --> nodes
```

Mermaid 原始文件：`App架构图.mmd`

PNG 图片：`App架构图.png`


cd /d D:\xikao\test1
D:\flutter\bin\flutter.bat clean
D:\flutter\bin\flutter.bat pub get --offline
D:\flutter\bin\flutter.bat test
D:\flutter\bin\flutter.bat build apk --release
D:\ai\android\platform-tools\adb.exe -s emulator-5554 install -r D:\xikao\test1\build\app\outputs\flutter-apk\app-release.apk