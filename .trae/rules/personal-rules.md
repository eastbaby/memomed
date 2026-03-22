---
name: "personal-rules"
description: "个人编码规则和最佳实践，用于指导日常开发工作"
---
## 个人编码规则

## 后端

1. 不要在代码中间import，所有import都写在文件顶部
2. 写langgragh、langchain的代码需要使用skill
3. 使用中文注释

## 前端
1. 使用 vercel ai sdk skill
2. 使用 nextjs 项目结构的最佳实践


## 依赖管理

### 后端依赖
- **包管理器**: `uv` (永远使用uv，不要使用pip)
- **配置文件**: `backend/pyproject.toml`
- **安装依赖**: `cd backend && uv sync`
- **添加依赖**: `cd backend && uv add <package_name>`

### 前端依赖
- **包管理器**: `npm`
- **配置文件**: `frontend/package.json`
- **安装依赖**: `cd frontend && npm install`

## 开发流程

1. 克隆代码库
2. 启动后端服务: `./start-backend.sh`
3. 启动前端服务: `./start-frontend.sh`
4. 访问前端界面进行测试

这些规则旨在帮助我保持代码质量和开发效率，同时确保项目的可维护性和安全性。我会根据实际项目需求和技术发展不断更新这些规则。