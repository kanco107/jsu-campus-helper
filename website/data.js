/* ============================================================
   校园网助手官网 · 内容数据
   由 admin.html 生成 · 2026/9/7 20:50:12
   ============================================================ */
window.SITE_DATA = {
  "meta": {
    "title": "校园网助手 · 吉首大学",
    "description": "专为吉首大学校园网环境开发的一键检测与修复工具,支持 Windows 与 Android。",
    "version": "v1.2.3",
    "brand": "校园网助手",
    "brandTag": "吉首大学 · v1.2.3"
  },
  "nav": {
    "links": [
      {
        "label": "功能",
        "href": "#features"
      },
      {
        "label": "检测项",
        "href": "#checks"
      },
      {
        "label": "平台对比",
        "href": "#compare"
      },
      {
        "label": "下载",
        "href": "#download"
      },
      {
        "label": "FAQ",
        "href": "#faq"
      }
    ],
    "ctaText": "下载"
  },
  "hero": {
    "eyebrow": "吉首大学 · 校园网工具",
    "title": "校园网连不上?<br>点一下就行。",
    "lead": "检测、修复校园网常见问题。",
    "primaryBtn": {
      "text": "下载",
      "href": "#download"
    },
    "secondaryBtn": {
      "text": "看功能",
      "href": "#features"
    },
    "meta": [
      "v1.2.3",
      "Windows · Android",
      "免费 · 离线"
    ]
  },
  "heroCard": {
    "title": "下载",
    "subtitle": "选你的平台",
    "platforms": [
      {
        "key": "win",
        "label": "Windows",
        "specs": [
          [
            "版本",
            "v1.2.3"
          ],
          [
            "大小",
            "≈ 378 MB（完整版）"
          ],
          [
            "系统要求",
            "Windows 10 (10240+)"
          ],
          [
            "架构",
            "x64"
          ],
          [
            "附带",
            ".NET 4.8 + WebView2 离线包"
          ],
          [
            "权限",
            "管理员(修复网络需)"
          ]
        ],
        "fileName": "Windows_v1.2.3_setup.exe",
        "btnText": "下载 Windows 安装包",
        "btnStyle": "primary",
        "downloadUrl": "https://github.com/kanco107/jsu-campus-helper/releases/download/v1.2.3/Windows_v1.2.3_setup.exe",
        "netdisk": { "label": "天翼云盘", "url": "https://cloud.189.cn/web/share?code=qANJ3mbqyqqm", "code": "j62g" }
      },
      {
        "key": "android",
        "label": "Android",
        "specs": [
          [
            "版本",
            "v1.2.3 (code 5)"
          ],
          [
            "大小",
            "≈ 3.1 MB"
          ],
          [
            "系统要求",
            "Android 10 (API 29)+"
          ],
          [
            "架构",
            "通用(arm64/arm/x86)"
          ],
          [
            "功能",
            "检测 + 校园网登录"
          ],
          [
            "权限",
            "仅网络权限,无系统修改"
          ]
        ],
        "fileName": "Android_v1.2.3.apk",
        "btnText": "下载 Android APK",
        "btnStyle": "accent",
        "downloadUrl": "https://github.com/kanco107/jsu-campus-helper/releases/download/v1.2.3/Android_v1.2.3.apk",
        "netdisk": { "label": "天翼云盘", "url": "https://cloud.189.cn/web/share?code=Qb6feyvqqUje", "code": "6jev" }
      }
    ]
  },
  "features": {
    "eyebrow": "功能",
    "title": "能干什么",
    "items": [
      {
        "icon": "brand",
        "title": "一键检测",
        "desc": "查 9 项网络指标,约 30 秒出报告。"
      },
      {
        "icon": "success",
        "title": "一键修复",
        "desc": "续 DHCP、重置 DNS、清代理,处理大部分上不了网的情况。"
      },
      {
        "icon": "warn",
        "title": "撤销更改",
        "desc": "改完出问题可以全部撤销,恢复原始故障。"
      },
      {
        "icon": "accent",
        "title": "校园网登录",
        "desc": "不用再开浏览器输网址,工具内能直接登录。"
      },
      {
        "icon": "danger",
        "title": "非校园网提醒",
        "desc": "连接非校园网时会进行提示并禁用修复,免得破坏其他网络配置。"
      },
      {
        "icon": "brand",
        "title": "高级工具",
        "desc": "手动重置 DHCP、指定 DNS、看适配器原始状态。"
      }
    ]
  },
  "checks": {
    "eyebrow": "9 项",
    "eyebrowStyle": "accent",
    "title": "检测哪 9 项",
    "items": [
      {
        "num": "01",
        "name": "网络连通",
        "desc": "能否 ping 通公网域名"
      },
      {
        "num": "02",
        "name": "WiFi 状态",
        "desc": "是否已连接、SSID 名称"
      },
      {
        "num": "03",
        "name": "信号强度",
        "desc": "dBm 数值,优/中/弱"
      },
      {
        "num": "04",
        "name": "内网网关",
        "desc": "能否到达校园网关"
      },
      {
        "num": "05",
        "name": "外网连通",
        "desc": "是否真正出校联网"
      },
      {
        "num": "06",
        "name": "认证状态",
        "desc": "drcom 是否已登录"
      },
      {
        "num": "07",
        "name": "DNS 解析",
        "desc": "域名能否正常解析"
      },
      {
        "num": "08",
        "name": "代理配置",
        "desc": "系统代理/PAC 是否异常"
      },
      {
        "num": "09",
        "name": "DHCP 状态",
        "desc": "169.254 失败 / IP 正常"
      }
    ]
  },
  "compare": {
    "eyebrow": "两个版本",
    "title": "Windows 和 Android",
    "subtitle": "Windows 版功能全,Android 版只检测。",
    "cards": [
      {
        "badge": "完整版",
        "badgeStyle": "brand",
        "title": "Windows 桌面版",
        "features": [
          "9 项网络检测",
          "一键自动修复(DHCP/DNS/代理)",
          "撤销所有更改",
          "校园网账号登录",
          "认证状态实时查询",
          "WiFi 信号强度评估",
          "随机 MAC 地址检测",
          "高级工具(手动重置/指定 DNS)",
          "诊断报告导出"
        ],
        "foot": "Windows10及以上设备适用"
      },
      {
        "badge": "轻量版",
        "badgeStyle": "accent",
        "title": "Android 检测版",
        "features": [
          "9 项网络检测",
          "校园网账号登录",
          "认证状态实时查询",
          "WiFi 信号强度评估",
          "非校园网环境提醒",
          {
            "text": "系统修复(Android 受限)",
            "disabled": true
          },
          {
            "text": "撤销更改",
            "disabled": true
          },
          {
            "text": "高级工具",
            "disabled": true
          }
        ],
        "foot": "Android10及以上设备适用"
      }
    ]
  },
  "steps": {
    "eyebrow": "用法",
    "eyebrowStyle": "success",
    "title": "怎么用",
    "items": [
      {
        "num": "1",
        "title": "下载安装",
        "desc": "下载对应平台的包,Windows 双击 setup,Android 装 APK。"
      },
      {
        "num": "2",
        "title": "点检测",
        "desc": "打开程序,点一键检测。等 30 秒看报告。"
      },
      {
        "num": "3",
        "title": "点修复",
        "desc": "有问题就点一键修复,完了再检测一次确认。"
      }
    ]
  },
  "download": {
    "eyebrow": "下载",
    "title": "下载 v1.2.3",
    "cards": [
      {
        "title": "Windows 完整版",
        "intro": "安装包里带了 .NET 4.8 和 WebView2 离线包,装的时候不用联网,适合新装机或不确定有没有运行库的电脑。",
        "specs": [
          "版本 v1.2.3",
          "文件大小 ≈ 378 MB(含运行时)",
          "支持 Windows 10 及以上",
          "需要管理员权限"
        ],
        "fileName": "Windows_v1.2.3_setup.exe",
        "btnText": "下载完整版",
        "btnStyle": "primary",
        "downloadUrl": "https://github.com/kanco107/jsu-campus-helper/releases/download/v1.2.3/Windows_v1.2.3_setup.exe",
        "netdisk": { "label": "天翼云盘", "url": "https://cloud.189.cn/web/share?code=qANJ3mbqyqqm", "code": "j62g" }
      },
      {
        "title": "Windows 精简版",
        "intro": "不含 .NET 4.8 和 WebView2 离线包,只有约 16 MB。系统已自带这两个运行库、或能联网安装时选这个。",
        "specs": [
          "版本 v1.2.3",
          "文件大小 ≈ 16 MB(不含运行时)",
          "支持 Windows 10 及以上",
          "需要管理员权限"
        ],
        "fileName": "Windows_v1.2.3_lite_setup.exe",
        "btnText": "下载精简版",
        "btnStyle": "primary",
        "downloadUrl": "https://github.com/kanco107/jsu-campus-helper/releases/download/v1.2.3/Windows_v1.2.3_lite_setup.exe",
        "netdisk": { "label": "天翼云盘", "url": "https://cloud.189.cn/web/share?code=ZbYBFnfAjyui", "code": "8map" }
      },
      {
        "title": "Android 检测版",
        "intro": "只检测不改系统,只要网络权限。装时可能提示\"未知来源\",允许就行。",
        "specs": [
          "版本 v1.2.3 (versionCode 5)",
          "文件大小 ≈ 3.1 MB",
          "支持 Android 10 及以上",
          "无需 root,无需特殊权限"
        ],
        "fileName": "Android_v1.2.3.apk",
        "btnText": "下载",
        "btnStyle": "accent",
        "downloadUrl": "https://github.com/kanco107/jsu-campus-helper/releases/download/v1.2.3/Android_v1.2.3.apk",
        "netdisk": { "label": "天翼云盘", "url": "https://cloud.189.cn/web/share?code=Qb6feyvqqUje", "code": "6jev" }
      }
    ],
    "warnBanner": {
      "icon": "⚠️",
      "html": "<b>注意:</b> 修复功能只针对吉首大学校园网。其他网络环境会红色提示并禁用修复,免得破坏其他网络使用。检测功能在什么网络下都能用。"
    }
  },
  "faq": {
    "eyebrow": "常见问题",
    "title": "FAQ",
    "items": [
      {
        "q": "这是学校官方软件吗?",
        "a": "不是,学生自己写的,跟学校信息中心没关系。校园网设备出现问题导致断网得找学校的信息中心。"
      },
      {
        "q": "为什么要管理员权限?",
        "a": "Windows 版改网络设置(IP、DNS、代理这些)得管理员权限。所有改动都有记录,可以一键撤销。Android 版只检测,不动系统。"
      },
      {
        "q": "安装包 378MB 太大了吧?",
        "a": "完整版因为带了 .NET 4.8 和 WebView2 离线包,装的时候不用联网,适合新装机。你电脑要是已经有这两样(Win10 较新版本一般自带),下载 16MB 的精简版就行,程序本体只有几十 MB。"
      },
      {
        "q": "支持别的学校吗?",
        "a": "默认是吉首大学的配置(WiFi 关键字 DORM、drcom 认证)。其他用 drcom 的学校理论上改配置文件能适配,但得自己折腾,不保证。"
      },
      {
        "q": "APK 安装提示\"未知来源\"?",
        "a": "正常,Android 对非应用商店来源都这样。设置里允许\"安装未知应用\"就行,只给这一个应用授权,不影响系统安全。"
      },
      {
        "q": "修完还是上不了网?",
        "a": "先点\"撤销所有更改\"回到动手前的状态,再检测一次。还是不行的话,可能是校园网本身的问题,或者网卡驱动的事,检测报告里会有提示，需要将提示内容发送给网络管理员。"
      },
      {
        "q": "会收集个人信息吗?",
        "a": "不会,完全离线运行,不上传任何数据。账号密码只在登录时发给校园网认证服务器,不经过第三方。"
      }
    ]
  },
  "cta": {
    "title": "有问题就反馈",
    "subtitle": "遇到 bug 或者有建议,可以通过下面方式联系。",
    "contacts": [
      {
        "type": "QQ群",
        "label": "QQ 群",
        "value": "点击加入 QQ 群",
        "href": "https://qm.qq.com/q/R7BFLAgPo6",
        "icon": "chat"
      },
      {
        "type": "邮箱",
        "label": "邮箱",
        "value": "2781362178@qq.com",
        "href": "mailto:2781362178@qq.com",
        "icon": "mail"
      },
      {
        "type": "GitHub",
        "label": "GitHub",
        "value": "Issues 反馈",
        "href": "https://github.com/kanco107/jsu-campus-helper/issues",
        "icon": "github"
      },
      {
        "type": "信息中心",
        "label": "网络信息中心",
        "value": "nic.jsu.edu.cn",
        "href": "https://nic.jsu.edu.cn/xwgg/tzgg/227b7dfe9e4741f99e6918b8c37c7a98.htm",
        "icon": "globe"
      }
    ]
  },
  "footer": {
    "columns": [
      {
        "title": "产品",
        "links": [
          {
            "label": "功能介绍",
            "href": "#features"
          },
          {
            "label": "检测项",
            "href": "#checks"
          },
          {
            "label": "平台对比",
            "href": "#compare"
          },
          {
            "label": "下载",
            "href": "#download"
          }
        ]
      },
      {
        "title": "帮助",
        "links": [
          {
            "label": "常见问题",
            "href": "#faq"
          },
          {
            "label": "使用教程",
            "href": "#"
          },
          {
            "label": "问题反馈",
            "href": "#cta"
          }
        ]
      },
      {
        "title": "关于",
        "links": [
          {
            "label": "项目说明",
            "href": "#"
          },
          {
            "label": "免责声明",
            "href": "#"
          },
          {
            "label": "隐私政策",
            "href": "#"
          }
        ]
      }
    ],
    "copyright": "© 2026 校园网助手"
  }
};
