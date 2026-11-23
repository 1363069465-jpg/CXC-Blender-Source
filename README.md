# CXC Blender 插件

## 显隐管理 1.1.0
维护者：艺哥HOW雕鸭。记录、更新和恢复小眼睛、显示器、相机三项状态。

## 首次发布
1. 将本目录文件提交到仓库 main 分支。
2. 仓库 Settings → Pages → Source 选择 GitHub Actions。
3. Actions → Publish Blender repository → Run workflow。
4. 等待成功后，在 Blender 偏好设置 → 获取扩展 → 仓库中添加：
   https://1363069465-jpg.github.io/CXC-Blender-Source/index.json
5. 允许 Blender 联网，从此仓库安装“显隐管理”。

## 从旧版迁移
先保存 .blend 并备份；停用旧版 product_visibility_manager，重启 Blender，再安装扩展。保留原 Object.pvm_data 和 Scene.pvm_target 数据字段；勿同时启用旧版和扩展版。安装后打开备份工程核对记录。

## 后续更新
修改源码并提高 blender_manifest.toml 的 version，提交后创建对应版本标签（如 v1.1.1）并推送，自动重新构建并部署。也可手动运行 Actions。用户在 Blender 检查更新并安装；不强制静默更新。仅修改源码不提高版本号，不会产生可识别的新版本。

## 范围
集合限制、局部视图不包含在记录中。首次发布仍须验证 Pages 部署与 Blender 在线安装；本地构建成功不等于线上发布成功。
