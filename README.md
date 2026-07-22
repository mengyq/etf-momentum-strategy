# ETF动量策略 - 云端自动推送系统

基于 AlphaFeed 实时数据的 A 股 ETF 动量轮动策略，通过 GitHub Actions 实现免服务器 24/7 运行。

## 功能
- 每周一 09:30 生成买卖信号 → 推送到邮箱/微信
- 每天 15:00 检查持仓盈亏 → 止损预警
- 20 只精选 ETF，行业分散，Top 2 持仓

## 配置步骤

### 1. 创建 GitHub 仓库
1. 登录 github.com，点 "+" → New repository
2. 仓库名填 `etf-momentum-strategy`，选 Private
3. 创建后按下方命令行操作

### 2. 上传文件到仓库
```bash
git clone https://github.com/你的用户名/etf-momentum-strategy.git
cd etf-momentum-strategy
# 把本目录所有文件复制过去
# 然后提交推送
```

### 3. 添加密钥 (Settings → Secrets and variables → Actions)
| 密钥名 | 值 |
|--------|-----|
| ALPHAFEED_API_KEY | 你的 AlphaFeed API Key |
| SMTP_USER | 你的 QQ 邮箱 |
| SMTP_PASS | QQ邮箱授权码(设置→账户→生成) |
| SMTP_TO | 接收通知的邮箱 |

### 4. 启用 Actions
仓库 Actions 标签页 → 确认 workflow 已启用
首次可点 "Run workflow" 手动测试

## 文件说明
- `cloud_strategy.py` - 主策略脚本
- `portfolio.json` - 持仓记录（需手动更新）
- `.github/workflows/strategy.yml` - 自动执行配置
