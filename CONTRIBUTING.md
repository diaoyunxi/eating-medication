# 贡献指南

感谢你对智能服药提醒系统的关注！以下是参与贡献的基本流程。

## 开发环境

```bash
# 克隆仓库
git clone https://github.com/diaoyunxi/eating-medication.git
cd eating-medication

# 安装依赖（使用项目安装脚本）
python common/install.py
```

## 代码风格

- Python 代码遵循 PEP 8，使用 [ruff](https://github.com/astral-sh/ruff) 进行检查
- 运行 `ruff check .` 验证代码风格
- 提交前确保所有测试通过：`pytest`

## 提交 PR 流程

1. Fork 本仓库
2. 创建功能分支：`git checkout -b feature/your-feature`
3. 提交变更：`git commit -m "feat: add your feature"`
4. 推送分支：`git push origin feature/your-feature`
5. 创建 Pull Request

## 提交信息规范

- `feat:` 新功能
- `fix:` 修复 Bug
- `docs:` 文档变更
- `refactor:` 代码重构
- `test:` 测试相关
- `chore:` 构建/工具变更

## 报告问题

请在 GitHub Issues 中报告 Bug 或提出功能建议，附上复现步骤和环境信息。
