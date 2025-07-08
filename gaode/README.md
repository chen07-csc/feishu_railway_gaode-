# 飞书机器人 + Dify集成

这是一个将飞书机器人与Dify
## 功能特点

- 支持飞书机器人消息接收和发送
- 支持Dify API集成
- 支持流式响应
- 支持会话管理
- 健康检查接口

## 环境要求

- Python 3.7+
- FastAPI
- 飞书开发者账号
- Dify API密钥

## 配置说明

1. 创建`.env`文件并配置以下环境变量：

```env
DIFY_API_KEY=你的Dify API密钥
DIFY_API_ENDPOINT=你的Dify API端点
FEISHU_APP_ID=你的飞书应用ID
FEISHU_APP_SECRET=你的飞书应用密钥
```

2. 安装依赖：

```bash
pip install -r requirements.txt
```

3. 运行服务：

```bash
python2 app.py
```

## 飞书配置

1. 在飞书开发者平台创建应用
2. 配置事件订阅
3. 开启机器人功能
4. 添加必要的权限
5. 发布应用

## API说明

- `GET /`: 健康检查接口
- `POST /feishu/webhook`: 处理飞书消息回调

## 注意事项

- 确保服务器有公网访问权限
- 正确配置飞书事件订阅地址
- 妥善保管API密钥 
