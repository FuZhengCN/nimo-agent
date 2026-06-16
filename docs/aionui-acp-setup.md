# Nimo 接入 AionUi 配置指南

## 前提

- Nimo 项目已在本地通过 `python -m nimo.main` 正常启动（CLI 模式验证通过）
- AionUi 已安装
- config.yaml、bin/ 下 exe 均已就位

## 第一步：创建 ACP 启动包装脚本

在 Nimo 项目根目录（和 config.yaml 同级）新建 `nimo_acp.bat`：

```bat
@echo off
cd /d D:\your-path\Nimo
python -m nimo.main --acp
```

> `D:\your-path\Nimo` 替换为你实际的 Nimo 项目路径。

**验证**：双击 `nimo_acp.bat`，应看到黑窗闪过并立即退出（正常，因为 stdin 无输入时 ACP 服务自动退出）。如果报 "No module named nimo" 则说明 `pip install -e` 未执行或路径不对。

## 第二步：AionUi 添加自定义 Agent

1. 打开 AionUi
2. 进入 **设置（Settings）**
3. 找到 **Agent Management** → **Custom Agents**（自定义代理）
4. 点击 **Add Custom Agent**（添加自定义代理）
5. 填写以下信息：

   | 字段 | 内容 |
   |------|------|
   | **Display Name**（显示名称） | `Nimo` |
   | **Command**（命令） | `D:\your-path\Nimo\nimo_acp.bat` |
   | **Arguments**（参数） | 留空 |

   > Command 必须填写完整绝对路径，不能用相对路径。

6. 点击 **Save**（保存）

## 第三步：验证

1. 在 AionUi 主界面，打开或新建一个对话
2. 在 Agent 选择器（顶部下拉框）中应出现 **Nimo**
3. 选择 Nimo，输入一条测试消息，例如：
   - "帮我查一下 TAPD 中有哪些项目"
   - "看看当前 SVN 最近 5 条提交记录"
4. 如果正常返回结果，集成完成

## 故障排查

| 现象 | 可能原因 | 解决 |
|------|---------|------|
| AionUi 选不到 Nimo | 未保存或未刷新 | 确认已保存，重启 AionUi 试试 |
| 选中后一直转圈无响应 | ACP 握手失败 | 双击 bat 看是否有报错，检查路径 |
| 报 "config.yaml 未找到" | bat 中 cd 路径不对 | 确认 `cd /d` 的路径是 Nimo 项目根目录 |
| 报 "No module named nimo" | Python 环境未安装 nimo | `pip install -e ".[dev]"` |
| 工具调用失败 | bin/ 下缺 exe | 确保 tapd.exe、svn.exe、svnadmin.exe 在 bin/ 下 |
| API Key 报错 | config.yaml 配置问题 | 检查 api_key 是否正确 |
